"""Turn a `DecisionInput` into the rule variables (`Fact` objects). Pure: no clock, no database.

Trust order, per variable:
- `identity_verified`: true only when a Rahat card carries a valid signed QR whose ID matches the form and
  the identity service says `match`. False on an invalid signature, a signed card for a different ID, or an
  identity `mismatch`. Anything else is unknown.
- `verified_income_pkr`: the registry's income record, or the income in a signed income proof. The declared
  income band is never used here; it is evidence for the model and for choosing which proof to ask for.
  An old registry record keeps its value but drops below the confidence floor.
- household facts: the registry value (verified) when present, else the declared value (not verified).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Final

from app.contracts.application import FieldValue
from app.contracts.documents import DocumentCheck
from app.contracts.engine import DecisionInput, Fact, RegistryRecord

DEFAULT_CONFIDENCE_FLOOR: Final = 0.9
DEFAULT_INCOME_MAX_AGE_DAYS: Final = 365
STALE_INCOME_CONFIDENCE: Final = 0.7  # below the default floor: an old record can never settle a rule alone

_PAYLOAD_ID_KEYS: Final = ("national_id", "id", "nid")
_PAYLOAD_NAME_KEYS: Final = ("full_name", "name")
_PAYLOAD_INCOME_KEYS: Final = ("monthly_income_pkr", "income_pkr", "verified_income_pkr")

UNKNOWN_FACT: Final = Fact()


def param(params: Mapping[str, Any] | None, name: str, default: float) -> float:
    value = (params or {}).get(name, default)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date() if "T" in value else date.fromisoformat(value[:10])
    except ValueError:
        return None


def payload_value(doc: DocumentCheck, keys: tuple[str, ...]) -> Any | None:
    payload = doc.qr.payload or {}
    for key in keys:
        if payload.get(key) not in (None, ""):
            return payload[key]
    return None


def signed(doc: DocumentCheck) -> bool:
    return doc.qr.found and doc.qr.signature_valid is True


def id_documents(inp: DecisionInput) -> list[DocumentCheck]:
    return [doc for doc in inp.documents if doc.kind == "rahat_id"]


def signed_card_id_mismatch(inp: DecisionInput) -> bool:
    """A validly signed card that belongs to a different ID than the one on the form."""
    form_id = (inp.form.national_id.value or "").strip()
    for doc in id_documents(inp):
        card_id = payload_value(doc, _PAYLOAD_ID_KEYS)
        if signed(doc) and form_id and card_id and str(card_id).strip() != form_id:
            return True
    return False


def signed_income_proofs(inp: DecisionInput) -> list[int]:
    out: list[int] = []
    for doc in inp.documents:
        if doc.kind != "income_proof" or not signed(doc):
            continue
        value = payload_value(doc, _PAYLOAD_INCOME_KEYS)
        try:
            amount = int(value) if value is not None and not isinstance(value, bool) else None
        except (TypeError, ValueError):
            amount = None
        if amount is not None and amount >= 0:
            out.append(amount)
    return out


def registry_record(inp: DecisionInput) -> RegistryRecord | None:
    return inp.registry if inp.registry_status == "found" and inp.registry is not None else None


def income_age_days(inp: DecisionInput) -> int | None:
    reg = registry_record(inp)
    as_of = parse_date(reg.income_as_of) if reg else None
    decided = parse_date(inp.decided_at)
    if as_of is None or decided is None:
        return None
    return max(0, (decided - as_of).days)


def _identity_fact(inp: DecisionInput) -> Fact:
    docs = id_documents(inp)
    status = inp.identity.status if inp.identity else None
    if any(doc.qr.signature_valid is False for doc in docs) or signed_card_id_mismatch(inp):
        return Fact(value=False, known=True, verified=True, confidence=1.0, source="document")
    if status == "mismatch":
        return Fact(value=False, known=True, verified=True, confidence=1.0, source="identity")
    if status == "match" and any(signed(doc) for doc in docs):
        return Fact(value=True, known=True, verified=True, confidence=1.0, source="identity")
    return UNKNOWN_FACT


def _income_fact(inp: DecisionInput, params: Mapping[str, Any] | None) -> Fact:
    reg = registry_record(inp)
    proofs = signed_income_proofs(inp)
    registry_fact: Fact | None = None
    if reg is not None and reg.verified_income_pkr is not None:
        age = income_age_days(inp)
        fresh = age is None or age <= param(params, "income_max_age_days", DEFAULT_INCOME_MAX_AGE_DAYS)
        registry_fact = Fact(value=reg.verified_income_pkr, known=True, verified=True,
                             confidence=1.0 if fresh else STALE_INCOME_CONFIDENCE, source="registry")  # fmt: skip
    if proofs and (registry_fact is None or registry_fact.confidence < 1.0):
        # A signed proof is fresh evidence; when two proofs disagree the higher income counts (conservative).
        return Fact(value=max(proofs), known=True, verified=True, confidence=1.0, source="document")
    return registry_fact or UNKNOWN_FACT


def _declared(field: FieldValue[Any]) -> Fact:
    if field.value is None:
        return UNKNOWN_FACT
    return Fact(value=field.value, known=True, verified=field.verified, confidence=field.confidence, source="form")


def _registry_or_declared(reg: RegistryRecord | None, name: str, field: FieldValue[Any]) -> Fact:
    value = getattr(reg, name) if reg is not None else None
    if value is not None:
        return Fact(value=value, known=True, verified=True, confidence=1.0, source="registry")
    return _declared(field)


def _dob(inp: DecisionInput) -> tuple[date | None, bool]:
    reg = registry_record(inp)
    if reg is not None and parse_date(reg.dob):
        return parse_date(reg.dob), True
    for doc in id_documents(inp):
        if signed(doc):
            card_dob = payload_value(doc, ("dob", "date_of_birth"))
            if isinstance(card_dob, str) and parse_date(card_dob):
                return parse_date(card_dob), True
    return parse_date(inp.form.dob.value), inp.form.dob.verified


def _age_fact(inp: DecisionInput) -> Fact:
    born, verified = _dob(inp)
    decided = parse_date(inp.decided_at)
    if born is None or decided is None:
        return UNKNOWN_FACT
    years = decided.year - born.year - ((decided.month, decided.day) < (born.month, born.day))
    if years < 0 or years > 130:
        return UNKNOWN_FACT
    confidence = 1.0 if verified else inp.form.dob.confidence
    return Fact(value=years, known=True, verified=verified, confidence=confidence, source="registry" if verified else "form")


def build_facts(inp: DecisionInput, params: Mapping[str, Any] | None = None) -> dict[str, Fact]:
    """Resolve every rule variable from the evidence. Unknown stays unknown; nothing is guessed."""
    reg = registry_record(inp)
    form = inp.form
    return {
        "identity_verified": _identity_fact(inp),
        "verified_income_pkr": _income_fact(inp, params),
        "receives_other_aid": _registry_or_declared(reg, "receives_other_aid", form.receives_other_aid),
        "is_widow": _registry_or_declared(reg, "is_widow", form.is_widow),
        "has_disability": _registry_or_declared(reg, "has_disability", form.has_disability),
        "household_size": _registry_or_declared(reg, "household_size", form.household_size),
        "district": _registry_or_declared(reg, "district", form.district),
        "gender": _registry_or_declared(reg, "gender", form.gender),
        "age_years": _age_fact(inp),
    }


# --- which proof would settle an unknown ---------------------------------------------------------------

PROOF_FOR_VARIABLE: Final[dict[str, str]] = {"verified_income_pkr": "income_proof", "identity_verified": "rahat_id"}


def resolvable_by(inp: DecisionInput, variable: str, fact: Fact) -> str | None:
    """The one document the citizen could supply to settle this variable, or None when only a person can.

    Income: a signed income proof settles a missing or old income record. Identity: a (new) photo of the
    card settles it only when the card is missing or unreadable; a partial name match, a missing record or
    a down identity service needs a person.
    """
    if variable == "verified_income_pkr":
        return "income_proof" if not fact.known or fact.confidence < 1.0 else None
    if variable == "identity_verified":
        if fact.known:
            return None
        status = inp.identity.status if inp.identity else None
        has_signed_card = any(signed(doc) for doc in id_documents(inp))
        if status == "match" and not has_signed_card:
            return "rahat_id"
        return None
    return None
