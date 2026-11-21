"""Pure rules about the application form: what a client may send, what is still missing, what a signed card adds.

Trust rule (docs/CONTRACTS.md): a client may send only provenance `tapped`, `typed` or `spoken`, and never
`verified`. Only server code sets `qr_signed` or `registry`, after it has checked a signature or called the
registry. A field that a signed card already verified cannot be overwritten by the client.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from pydantic import ValidationError

from app.contracts.application import FORM_FIELDS, ApplicationFormV1, FieldValue, apply_patch
from app.contracts.common import ConsentScope
from app.core.errors import Unprocessable
from app.core.mockdata import mock_id_shape_ok, mock_id_valid, normalise_mock_phone

CLIENT_PROVENANCE: Final[frozenset[str]] = frozenset({"tapped", "typed", "spoken"})
_FIELD_VALUE_KEYS: Final[frozenset[str]] = frozenset({"value", "confidence", "provenance", "verified"})
_LANGS: Final[frozenset[str]] = frozenset({"en", "ur", "sd"})
_GENDERS: Final[frozenset[str]] = frozenset({"female", "male", "other"})
_TEXT_LIMITS: Final[dict[str, int]] = {"full_name": 120, "district": 64, "payout_account": 40, "gender": 16}
_DIGIT_RUN = re.compile(r"\d{5,}")  # an ID or phone number typed into a name field
_MOCK_PAYOUT = re.compile(r"^MOCK-[A-Z0-9]{4,32}$")

# Which consent scope covers each form field. Writing a field needs that scope in the active consent.
FIELD_SCOPE: Final[dict[str, ConsentScope]] = {
    "full_name": "identity",
    "national_id": "identity",
    "dob": "identity",
    "gender": "identity",
    "phone": "contact",
    "payout_account": "contact",
    "district": "household",
    "household_size": "household",
    "is_widow": "household",
    "has_disability": "household",
    "income_band": "income",
    "receives_other_aid": "income",
}
assert set(FIELD_SCOPE) == set(FORM_FIELDS), "every form field needs a consent scope"

# Rule variables that are not form fields: map them to the field the citizen can answer, or skip them.
RULE_VAR_TO_FIELD: Final[dict[str, str | None]] = {
    "verified_income_pkr": "income_band",
    "identity_verified": None,  # comes from the signed card or the registry, never from a question
}


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    message: str
    code: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message, "code": self.code}


def raise_if_errors(errors: list[FieldError]) -> None:
    if errors:
        raise Unprocessable(
            "Check the fields listed in 'errors'.",
            code="invalid_form",
            extra={"errors": [e.as_dict() for e in errors]},
        )


def _value_errors(name: str, value: Any) -> list[FieldError]:
    """Format checks that keep real-looking data out (mock formats only) and dates sane."""
    if value is None:
        return []
    where = f"form_patch.{name}.value"
    if name == "national_id":
        if not isinstance(value, str) or not mock_id_shape_ok(value):
            return [FieldError(where, "Use the mock ID format 00000-NNNNNNN-C.", "mock_id_format")]
        if not mock_id_valid(value):
            return [FieldError(where, "The last digit of the ID does not match. Check the number.", "mock_id_check_digit")]
    if name == "phone" and (not isinstance(value, str) or normalise_mock_phone(value) is None):
        return [FieldError(where, "Use the mock phone format 0999-NNNNNNN.", "mock_phone_format")]
    if name == "dob":
        try:
            born = date.fromisoformat(str(value))
        except ValueError:
            return [FieldError(where, "Use a date like 1980-01-31.", "date_format")]
        if not date(1900, 1, 1) <= born <= date.today():
            return [FieldError(where, "That date of birth is not possible.", "date_range")]
    if name == "household_size" and isinstance(value, int) and not 1 <= value <= 30:
        return [FieldError(where, "A household has between 1 and 30 people.", "household_size_range")]
    if name in _TEXT_LIMITS:
        if not isinstance(value, str) or not value.strip() or len(value) > _TEXT_LIMITS[name]:
            return [FieldError(where, f"Use 1 to {_TEXT_LIMITS[name]} characters.", "text_length")]
        if name in ("full_name", "district") and _DIGIT_RUN.search(value):
            return [FieldError(where, "Numbers do not belong in this field.", "digits_not_allowed")]
        if name == "gender" and value not in _GENDERS:
            return [FieldError(where, "Choose female, male or other.", "invalid_choice")]
        if name == "payout_account" and normalise_mock_phone(value) is None and not _MOCK_PAYOUT.match(value):
            return [FieldError(where, "Use a mock wallet (0999-NNNNNNN) or a MOCK- account.", "mock_payout_format")]
    return []


def check_client_patch(patch: Mapping[str, Any], current: ApplicationFormV1) -> list[FieldError]:
    """Everything wrong with a client's form patch, as repairable field errors. Empty means acceptable."""
    errors: list[FieldError] = []
    for name, raw in patch.items():
        where = f"form_patch.{name}"
        if name == "language":
            if not isinstance(raw, str) or raw not in _LANGS:
                errors.append(FieldError(where, "Choose en or ur.", "invalid_language"))
            continue
        if name not in FORM_FIELDS:
            errors.append(FieldError(where, "This is not a field of the form.", "unknown_field"))
            continue
        if not isinstance(raw, Mapping):
            errors.append(FieldError(where, "Send an object with 'value' and 'provenance'.", "field_value_shape"))
            continue
        extra = set(raw) - _FIELD_VALUE_KEYS
        if extra:
            errors.append(FieldError(where, f"Unknown keys: {', '.join(sorted(extra))}.", "field_value_shape"))
            continue
        provenance = raw.get("provenance", "tapped")
        if not isinstance(provenance, str) or provenance not in CLIENT_PROVENANCE:
            errors.append(FieldError(f"{where}.provenance", "Use tapped, typed or spoken.", "provenance_not_allowed"))
        verified = raw.get("verified")
        if verified is not None and verified is not False:
            errors.append(FieldError(f"{where}.verified", "Only the department can mark a value as verified.", "verified_not_allowed"))
        existing: FieldValue[Any] = getattr(current, name)
        if existing.verified:
            errors.append(FieldError(where, "This was read from your signed card. Ask for a correction to change it.", "field_locked"))
        errors.extend(_value_errors(name, raw.get("value")))
    return errors


def check_client_form(form: ApplicationFormV1) -> list[FieldError]:
    """The same trust rule for a whole form sent at creation (already parsed by Pydantic)."""
    errors: list[FieldError] = []
    for name in FORM_FIELDS:
        field: FieldValue[Any] = getattr(form, name)
        where = f"form.{name}"
        if field.provenance not in CLIENT_PROVENANCE:
            errors.append(FieldError(f"{where}.provenance", "Use tapped, typed or spoken.", "provenance_not_allowed"))
        if field.verified:
            errors.append(FieldError(f"{where}.verified", "Only the department can mark a value as verified.", "verified_not_allowed"))
        errors.extend(FieldError(e.field.replace("form_patch.", "form."), e.message, e.code) for e in _value_errors(name, field.value))
    return errors


def merge_client_patch(current: ApplicationFormV1, patch: Mapping[str, Any]) -> ApplicationFormV1:
    """Validate and merge. Raises a repairable 422 listing every problem; never a 500."""
    raise_if_errors(check_client_patch(patch, current))
    normalised: dict[str, Any] = {}
    for name, raw in patch.items():
        if name == "language":
            normalised[name] = raw
            continue
        entry = dict(raw)
        if name == "phone" and entry.get("value"):
            entry["value"] = normalise_mock_phone(str(entry["value"]))
        # A tapped or typed answer is exactly what the person chose. Spoken answers carry the recogniser's own score.
        if "confidence" not in entry and entry.get("value") is not None and entry.get("provenance", "tapped") in ("tapped", "typed"):
            entry["confidence"] = 1.0
        normalised[name] = entry
    try:
        return apply_patch(current, normalised)
    except ValidationError as exc:
        raise_if_errors(
            [
                FieldError("form_patch." + ".".join(str(p) for p in e.get("loc", ())), e.get("msg", "invalid"), e.get("type", "invalid"))
                for e in exc.errors()
            ]
        )
        raise  # unreachable: there was at least one error
    except ValueError as exc:
        raise Unprocessable(str(exc), code="invalid_form") from exc


def scopes_needed(fields: Iterable[str]) -> set[str]:
    return {FIELD_SCOPE[name] for name in fields if name in FIELD_SCOPE}


def set_fields(form: ApplicationFormV1) -> list[str]:
    """Names of fields that hold a value."""
    return [name for name in FORM_FIELDS if getattr(form, name).value is not None]


def _vars(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, child in node.items():
            if key == "var":
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list) and child and isinstance(child[0], str):
                    yield child[0]
            else:
                yield from _vars(child)
    elif isinstance(node, list):
        for child in node:
            yield from _vars(child)


def required_fields(dsl: Mapping[str, Any] | None) -> list[str]:
    """Form fields that the rule version reads, in rule order, without duplicates."""
    out: list[str] = []
    for var in _vars(dict(dsl or {})):
        field = RULE_VAR_TO_FIELD.get(var, var)
        if field and field in FORM_FIELDS and field not in out:
            out.append(field)
    return out


def missing_fields(form: ApplicationFormV1, dsl: Mapping[str, Any] | None) -> list[str]:
    return form.missing(required_fields(dsl))


# --- signed card --------------------------------------------------------------------------------------

# Accepted names for each form field in a signed QR payload (Track C's specimen card).
_QR_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "full_name": ("full_name", "name"),
    "national_id": ("national_id", "id", "nid"),
    "dob": ("dob", "date_of_birth"),
    "gender": ("gender", "sex"),
    "district": ("district",),
}


def signed_fields(payload: Mapping[str, Any] | None) -> dict[str, str]:
    """Form values carried by a signed card, after the same format checks a typed value gets."""
    out: dict[str, str] = {}
    for field, keys in _QR_KEYS.items():
        value = next((payload[k] for k in keys if payload and isinstance(payload.get(k), str) and payload[k].strip()), None)
        if value is None:
            continue
        value = value.strip()
        if _value_errors(field, value):
            continue
        out[field] = value
    return out


def merge_signed(form: ApplicationFormV1, values: Mapping[str, str]) -> ApplicationFormV1:
    """Server only: put signature-checked values into the form as verified."""
    patch = {name: {"value": value, "confidence": 1.0, "provenance": "qr_signed", "verified": True} for name, value in values.items()}
    return apply_patch(form, patch)
