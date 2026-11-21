"""Hand-written decision inputs with known right answers: the golden set, the demo personas, the test fixtures.

`base_input()` is a clean, fully verified application (a widow with a signed card, a recent registry income
well under the cap and no other aid). Every other case changes one or two things about it.
`GOLDEN` maps a name to (input, allowed routes, allowed outcomes). Ambiguous inputs only allow human or
ask_more; only verified evidence allows an automatic answer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from app.contracts.application import ApplicationFormV1, FieldValue
from app.contracts.decision import TypedDecision
from app.contracts.documents import Authenticity, DocumentCheck, DocumentSignal, OcrResult, QrResult
from app.contracts.engine import AnomalyEvidence, DecisionInput, DuplicateEvidence, IdentityCheck, RegistryRecord
from app.core.mockdata import make_mock_id

MOCK_ID: Final = make_mock_id(1_000_201)
OTHER_ID: Final = make_mock_id(1_000_777)
DECIDED_AT: Final = "2026-11-21T10:00:00+00:00"


def _auth(choice: Authenticity | None, p: float, route: str = "auto") -> TypedDecision[Authenticity]:
    return TypedDecision[Authenticity](choice=choice, probabilities={"genuine": p, "suspect": round(1 - p, 3)}, confidence=max(p, 1 - p),
                                       route=route, abstained=choice is None, model_version="golden")  # type: ignore[arg-type]  # fmt: skip


def card(*, signed: bool | None = True, quality: str = "ok", national_id: str = MOCK_ID, name: str = "Zainab Bibi",
         doc_id: str = "doc-card-1") -> DocumentCheck:  # fmt: skip
    """A Rahat card check. signed: True valid QR, False tampered QR, None no QR found."""
    if signed is None:
        qr = QrResult(found=False)
        auth = _auth(None, 0.5, "ask_more") if quality != "ok" else _auth("genuine", 0.85)
    else:
        qr = QrResult(found=True, signature_valid=signed, issuer_key_id="mock-issuer-1",
                      payload={"national_id": national_id, "name": name, "dob": "1978-03-14"})  # fmt: skip
        auth = _auth("genuine", 0.98) if signed else _auth("suspect", 0.05, "human")
    signals = [DocumentSignal(code="qr_signature_valid" if signed else "qr_signature_invalid", weight=-2.0 if signed else 3.0,
                              staff_detail="signature check")] if signed is not None else []  # fmt: skip
    return DocumentCheck(document_id=doc_id, kind="rahat_id", quality=quality, qr=qr,  # type: ignore[arg-type]
                         ocr=OcrResult(fields={"name": name.upper()}, mean_confidence=0.92, raw_text=f"RAHAT CARD SPECIMEN {name.upper()}"),
                         authenticity=auth, signals=signals, model_version="golden")  # fmt: skip


def income_proof(amount: int, doc_id: str = "doc-income-1") -> DocumentCheck:
    return DocumentCheck(document_id=doc_id, kind="income_proof", quality="ok",
                         qr=QrResult(found=True, signature_valid=True, issuer_key_id="mock-employer-1", payload={"monthly_income_pkr": amount}),
                         authenticity=_auth("genuine", 0.96), model_version="golden")  # fmt: skip


def form(**changes: Any) -> ApplicationFormV1:
    values: dict[str, Any] = {
        "full_name": FieldValue[str](value="Zainab Bibi", confidence=0.95, provenance="spoken"),
        "national_id": FieldValue[str](value=MOCK_ID, confidence=0.99, provenance="typed"),
        "dob": FieldValue[str](value="1978-03-14", confidence=0.95, provenance="typed"),
        "gender": FieldValue[str](value="female", confidence=1.0, provenance="tapped"),
        "district": FieldValue[str](value="Karachi East", confidence=1.0, provenance="tapped"),
        "household_size": FieldValue[int](value=5, confidence=0.85, provenance="spoken"),
        "income_band": FieldValue(value="15k_30k", confidence=0.9, provenance="tapped"),
        "is_widow": FieldValue[bool](value=True, confidence=1.0, provenance="tapped"),
        "has_disability": FieldValue[bool](value=False, confidence=1.0, provenance="tapped"),
        "receives_other_aid": FieldValue[bool](value=False, confidence=0.95, provenance="tapped"),
        "language": "ur",
    }
    values.update(changes)
    return ApplicationFormV1(**values)


def registry(**changes: Any) -> RegistryRecord:
    values: dict[str, Any] = {
        "national_id": MOCK_ID, "full_name": "Zainab Bibi", "dob": "1978-03-14", "gender": "female", "district": "Karachi East",
        "household_size": 5, "verified_income_pkr": 18_000, "income_as_of": "2026-06-01", "receives_other_aid": False,
        "is_widow": True, "has_disability": False,
    }  # fmt: skip
    values.update(changes)
    return RegistryRecord(**values)


def base_input(**changes: Any) -> DecisionInput:
    values: dict[str, Any] = {
        "application_id": "golden-app", "program_slug": "rahat", "lang": "ur", "form": form(), "documents": [card()],
        "identity": IdentityCheck(status="match", name_score=0.97), "registry_status": "found", "registry": registry(),
        "duplicate": DuplicateEvidence(band="distinct", score=0.12), "anomaly": AnomalyEvidence(score=0.08, flagged=False),
        "consent_ok": True, "queue_days": 1.0, "decided_at": DECIDED_AT,
    }  # fmt: skip
    values.update(changes)
    return DecisionInput(**values)


AUTO = frozenset({"auto"})
NOT_AUTO = frozenset({"human", "ask_more"})
HUMAN = frozenset({"human"})
ASK = frozenset({"ask_more"})

# name: (builder, allowed routes, allowed outcomes or None for any outcome of those routes)
GOLDEN: Final[dict[str, tuple[Callable[[], DecisionInput], frozenset[str], frozenset[str] | None]]] = {
    "clean_verified": (lambda: base_input(), AUTO, frozenset({"approved"})),
    "registry_income_missing": (lambda: base_input(registry=registry(verified_income_pkr=None, income_as_of=None)), NOT_AUTO, None),
    "registry_income_stale": (lambda: base_input(registry=registry(income_as_of="2024-01-10")), NOT_AUTO, None),
    "stale_income_over_cap": (lambda: base_input(registry=registry(verified_income_pkr=45_000, income_as_of="2023-05-01")), NOT_AUTO, None),
    "income_over_cap_verified": (lambda: base_input(registry=registry(verified_income_pkr=48_000)), AUTO, frozenset({"rejected"})),
    "other_aid_in_registry": (lambda: base_input(registry=registry(receives_other_aid=True)), AUTO, frozenset({"rejected"})),
    "other_aid_only_declared": (lambda: base_input(registry=registry(receives_other_aid=None),
                                                   form=form(receives_other_aid=FieldValue[bool](value=True, confidence=1.0))), NOT_AUTO, None),
    "aid_missing_everywhere": (lambda: base_input(registry=registry(receives_other_aid=None),
                                                  form=form(receives_other_aid=FieldValue[bool]())), NOT_AUTO, None),
    "declared_over_50k_no_registry_income": (lambda: base_input(registry=registry(verified_income_pkr=None, income_as_of=None),
                                                                form=form(income_band=FieldValue(value="over_50k", confidence=1.0))), NOT_AUTO, None),
    "over_cap_but_identity_unconfirmed": (lambda: base_input(registry=registry(verified_income_pkr=60_000),
                                                             identity=IdentityCheck(status="partial", name_score=0.7)), NOT_AUTO, None),
    "forged_card_signature_invalid": (lambda: base_input(documents=[card(signed=False)]), HUMAN, None),
    "signed_card_for_another_id": (lambda: base_input(documents=[card(national_id=OTHER_ID)]), HUMAN, None),
    "identity_mismatch": (lambda: base_input(identity=IdentityCheck(status="mismatch", name_score=0.31)), HUMAN, None),
    "identity_partial": (lambda: base_input(identity=IdentityCheck(status="partial", name_score=0.74)), HUMAN, None),
    "identity_service_down": (lambda: base_input(identity=IdentityCheck(status="unavailable")), HUMAN, None),
    "no_identity_check": (lambda: base_input(identity=None), HUMAN, None),
    "possible_duplicate": (lambda: base_input(duplicate=DuplicateEvidence(band="possible", score=0.74, other_person_ref="P00012")), HUMAN, None),
    "same_person_twice": (lambda: base_input(duplicate=DuplicateEvidence(band="same", score=0.97, other_person_ref="P00012")), HUMAN, None),
    "anomaly_flagged": (lambda: base_input(anomaly=AnomalyEvidence(score=0.91, flagged=True, reasons=["shared_payout_account"])), HUMAN, None),
    "registry_down": (lambda: base_input(registry_status="unavailable", registry=None), HUMAN, None),
    "not_in_registry": (lambda: base_input(registry_status="not_found", registry=None), NOT_AUTO, None),
    "consent_missing": (lambda: base_input(consent_ok=False), HUMAN, None),
    "no_card_uploaded": (lambda: base_input(documents=[]), NOT_AUTO, None),
    "blurry_card_no_qr": (lambda: base_input(documents=[card(signed=None, quality="blurry")]), NOT_AUTO, None),
    "card_without_qr_looks_fine": (lambda: base_input(documents=[card(signed=None)]), NOT_AUTO, None),
    "signed_income_proof_fills_gap": (lambda: base_input(registry=registry(verified_income_pkr=None, income_as_of=None),
                                                         documents=[card(), income_proof(17_500)]), frozenset({"auto", "human", "ask_more"}),
                                      frozenset({"approved", "needs_human"})),
    "verified_incomes_disagree": (lambda: base_input(documents=[card(), income_proof(45_000)]), HUMAN, None),
    "forged_card_and_registry_down": (lambda: base_input(documents=[card(signed=False)], registry_status="unavailable", registry=None), HUMAN, None),
}  # fmt: skip
