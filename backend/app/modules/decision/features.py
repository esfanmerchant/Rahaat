"""Features for the evidence model, computed from a `DecisionInput` (and the rule version's parameters) alone.

Pure and deterministic. Income features are relative to the rule version's `income_cap`, so the model's
`p_eligible` moves with a published cap change instead of staying tied to the cap it was trained on.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Final

from rapidfuzz import fuzz

from app.contracts.common import INCOME_BAND_BOUNDS
from app.contracts.engine import DecisionInput, Fact
from app.modules.decision import facts as F

DEFAULT_INCOME_CAP: Final = 30_000
_BAND_TOP_FOR_OPEN_END: Final = 2.0  # "over 50k" counts as up to twice its lower bound

FEATURE_NAMES: Final[tuple[str, ...]] = (
    "card_present", "card_quality_ok", "card_signed", "card_signature_invalid", "card_no_qr", "card_p_genuine",
    "card_suspect", "card_name_similarity", "card_id_mismatch",
    "identity_match", "identity_partial", "identity_mismatch", "identity_not_found", "identity_missing", "identity_name_score",
    "registry_found", "registry_not_found",
    "reg_income_known", "reg_income_log_ratio_fresh", "reg_income_log_ratio_stale", "reg_income_over_cap_fresh",
    "reg_income_over_cap_stale", "reg_income_age_years",
    "proof_income_known", "proof_income_log_ratio", "proof_income_over_cap",
    "declared_band_missing", "declared_band_under_cap", "declared_band_over_cap", "declared_band_log_mid_ratio",
    "declared_disagrees_registry",
    "aid_registry_true", "aid_registry_false", "aid_declared_true", "aid_unknown",
    "household_disagrees", "widow_disagrees", "form_mean_confidence",
    "dup_possible", "dup_same", "dup_score", "anomaly_score", "anomaly_flagged",
)  # fmt: skip


def _log_ratio(value: float, cap: float) -> float:
    return max(-2.0, min(2.0, math.log(max(value, 500.0) / max(cap, 1.0))))


def _band(inp: DecisionInput) -> tuple[float, float] | None:
    band = inp.form.income_band.value
    if band is None or band not in INCOME_BAND_BOUNDS:
        return None
    low, high = INCOME_BAND_BOUNDS[band]
    return float(low), float(high if high is not None else low * _BAND_TOP_FOR_OPEN_END)


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").lower().replace(".", " ").split())


def compute_features(inp: DecisionInput, facts: Mapping[str, Fact], params: Mapping[str, Any] | None = None) -> dict[str, float]:
    cap = F.param(params, "income_cap", DEFAULT_INCOME_CAP)
    x: dict[str, float] = dict.fromkeys(FEATURE_NAMES, 0.0)

    cards = F.id_documents(inp)
    if cards:
        x["card_present"] = 1.0
        x["card_quality_ok"] = float(any(doc.quality == "ok" for doc in cards))
        x["card_signed"] = float(any(F.signed(doc) for doc in cards))
        x["card_signature_invalid"] = float(any(doc.qr.signature_valid is False for doc in cards))
        x["card_no_qr"] = float(not any(doc.qr.found for doc in cards))
        x["card_p_genuine"] = min(doc.authenticity.probabilities.get("genuine", 0.5) for doc in cards)
        x["card_id_mismatch"] = float(F.signed_card_id_mismatch(inp))
        names = [F.payload_value(doc, ("full_name", "name")) or doc.ocr.fields.get("name") for doc in cards]
        form_name = _norm_name(inp.form.full_name.value)
        scores = [fuzz.token_set_ratio(_norm_name(name), form_name) / 100.0 for name in names if name and form_name]
        x["card_name_similarity"] = max(scores) if scores else 0.5
    else:
        x["card_p_genuine"] = 0.5
        x["card_name_similarity"] = 0.5
    x["card_suspect"] = float(any(doc.authenticity.choice == "suspect" for doc in inp.documents))

    status = inp.identity.status if inp.identity else None
    x["identity_match"] = float(status == "match")
    x["identity_partial"] = float(status == "partial")
    x["identity_mismatch"] = float(status == "mismatch")
    x["identity_not_found"] = float(status == "not_found")
    x["identity_missing"] = float(status in (None, "unavailable"))
    score = inp.identity.name_score if inp.identity else None
    x["identity_name_score"] = score if score is not None else 0.5

    reg = F.registry_record(inp)
    x["registry_found"] = float(reg is not None)
    x["registry_not_found"] = float(inp.registry_status == "not_found")
    if reg is not None and reg.verified_income_pkr is not None:
        age = F.income_age_days(inp)
        stale = age is not None and age > F.param(params, "income_max_age_days", F.DEFAULT_INCOME_MAX_AGE_DAYS)
        ratio = _log_ratio(reg.verified_income_pkr, cap)
        over = float(reg.verified_income_pkr > cap)
        x["reg_income_known"] = 1.0
        x["reg_income_log_ratio_stale" if stale else "reg_income_log_ratio_fresh"] = ratio
        x["reg_income_over_cap_stale" if stale else "reg_income_over_cap_fresh"] = over
        x["reg_income_age_years"] = min(5.0, (age or 0) / 365.0)

    proofs = F.signed_income_proofs(inp)
    if proofs:
        x["proof_income_known"] = 1.0
        x["proof_income_log_ratio"] = _log_ratio(max(proofs), cap)
        x["proof_income_over_cap"] = float(max(proofs) > cap)

    band = _band(inp)
    if band is None:
        x["declared_band_missing"] = 1.0
    else:
        low, high = band
        x["declared_band_under_cap"] = float(high <= cap)
        x["declared_band_over_cap"] = float(low >= cap)
        x["declared_band_log_mid_ratio"] = _log_ratio((low + high) / 2.0, cap)
        if reg is not None and reg.verified_income_pkr is not None:
            x["declared_disagrees_registry"] = float(not low <= reg.verified_income_pkr <= high)

    aid = facts.get("receives_other_aid", F.UNKNOWN_FACT)
    if not aid.known:
        x["aid_unknown"] = 1.0
    elif aid.source == "registry":
        x["aid_registry_true" if aid.value else "aid_registry_false"] = 1.0
    elif aid.value:
        x["aid_declared_true"] = 1.0

    form = inp.form
    if reg is not None:
        if reg.household_size is not None and form.household_size.value is not None:
            x["household_disagrees"] = float(abs(reg.household_size - form.household_size.value) >= 2)
        if reg.is_widow is not None and form.is_widow.value is not None:
            x["widow_disagrees"] = float(reg.is_widow != form.is_widow.value)
    declared = [getattr(form, name).confidence for name in ("household_size", "income_band", "is_widow", "receives_other_aid")]
    x["form_mean_confidence"] = sum(declared) / len(declared)

    if inp.duplicate is not None:
        x["dup_possible"] = float(inp.duplicate.band == "possible")
        x["dup_same"] = float(inp.duplicate.band == "same")
        x["dup_score"] = inp.duplicate.score
    if inp.anomaly is not None:
        x["anomaly_score"] = inp.anomaly.score
        x["anomaly_flagged"] = float(inp.anomaly.flagged)
    return {name: round(float(value), 6) for name, value in x.items()}
