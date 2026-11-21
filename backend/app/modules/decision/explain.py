"""What the citizen is told, and what the officer is handed. Templates only; no free text from a model.

Citizen text: at most three short sentences at about grade 5, keyed by a citizen-safe reason code, in
English and Urdu, with a next step, a pictogram and the audio files to play. It never mentions a score, a
threshold or why a document or record was flagged: those go to staff in the handoff package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.contracts.decision import Explanation, HandoffPackage, Hypothesis, UncertainField
from app.contracts.engine import DecisionInput, Fact
from app.modules.decision import facts as F
from app.modules.rules.dsl import RuleEvaluation

PICTOGRAMS: Final = frozenset({"yes", "no", "person-will-help", "document", "payment", "warning", "retry"})

# code: (pictogram, next step code, {lang: sentences})
CITIZEN_TEMPLATES: Final[dict[str, tuple[str, str, dict[str, tuple[str, ...]]]]] = {
    "approved": ("yes", "payment_soon", {
        "en": ("Good news. You can get the Rahat payment.", "The money will come to your account soon."),
        "ur": ("خوشخبری۔ آپ کو راحت کی رقم ملے گی۔", "رقم جلد آپ کے اکاؤنٹ میں آ جائے گی۔"),
    }),
    "rejected_income_over_cap": ("no", "ask_again", {
        "en": ("The records show your monthly income is above the limit.", "So you cannot get this payment now."),
        "ur": ("ریکارڈ کے مطابق آپ کی ماہانہ آمدنی حد سے زیادہ ہے۔", "اس لیے ابھی آپ کو یہ رقم نہیں مل سکتی۔"),
    }),
    "rejected_other_aid": ("no", "ask_again", {
        "en": ("The records show you already get another relief payment.", "So you cannot get this one too."),
        "ur": ("ریکارڈ کے مطابق آپ کو پہلے سے ایک اور امداد مل رہی ہے۔", "اس لیے آپ کو یہ رقم نہیں مل سکتی۔"),
    }),
    "rejected_rule": ("no", "ask_again", {
        "en": ("You do not meet one rule of this program.", "So you cannot get this payment now."),
        "ur": ("آپ اس پروگرام کی ایک شرط پوری نہیں کرتے۔", "اس لیے ابھی آپ کو یہ رقم نہیں مل سکتی۔"),
    }),
    "ask_income_proof": ("document", "send_income_proof", {
        "en": ("We could not check your monthly income.", "Please show one paper with your income, like a pay slip."),
        "ur": ("ہم آپ کی ماہانہ آمدنی کی تصدیق نہیں کر سکے۔", "براہ کرم آمدنی کا ایک کاغذ دکھائیں، جیسے تنخواہ کی پرچی۔"),
    }),
    "ask_rahat_id": ("document", "send_card_photo", {
        "en": ("We need a photo of your Rahat card.", "Please take a photo of the card and send it."),
        "ur": ("ہمیں آپ کے راحت کارڈ کی تصویر چاہیے۔", "براہ کرم کارڈ کی تصویر لے کر بھیجیں۔"),
    }),
    "ask_rahat_id_retake": ("retry", "retake_card_photo", {
        "en": ("The photo of your card was not clear.", "Please take it again in good light."),
        "ur": ("آپ کے کارڈ کی تصویر صاف نہیں تھی۔", "براہ کرم اچھی روشنی میں دوبارہ تصویر لیں۔"),
    }),
    "human_check": ("person-will-help", "wait_for_person", {
        "en": ("A person will check your application.", "This is a normal step.", "You do not need to do anything now."),
        "ur": ("ایک فرد آپ کی درخواست دیکھے گا۔", "یہ ایک عام مرحلہ ہے۔", "آپ کو ابھی کچھ نہیں کرنا۔"),
    }),
    "human_identity_check": ("person-will-help", "wait_for_person", {
        "en": ("We could not match your name with the records.", "A person will check it for you."),
        "ur": ("ہم آپ کا نام ریکارڈ سے نہیں ملا سکے۔", "ایک فرد آپ کے لیے اسے دیکھے گا۔"),
    }),
    "human_income_unverified": ("person-will-help", "wait_for_person", {
        "en": ("We could not check your monthly income.", "A person will look at your application."),
        "ur": ("ہم آپ کی ماہانہ آمدنی کی تصدیق نہیں کر سکے۔", "ایک فرد آپ کی درخواست دیکھے گا۔"),
    }),
    "human_registry_down": ("person-will-help", "wait_for_person", {
        "en": ("Our records service is not working right now.", "A person will check your application."),
        "ur": ("ہمارا ریکارڈ کا نظام ابھی کام نہیں کر رہا۔", "ایک فرد آپ کی درخواست دیکھے گا۔"),
    }),
    "human_consent_needed": ("warning", "give_consent", {
        "en": ("We need your permission to use your information.", "Without it we cannot check your application."),
        "ur": ("ہمیں آپ کی معلومات استعمال کرنے کی اجازت چاہیے۔", "اجازت کے بغیر ہم آپ کی درخواست نہیں دیکھ سکتے۔"),
    }),
}  # fmt: skip

NEXT_STEPS: Final[dict[str, dict[str, str]]] = {
    "payment_soon": {"en": "Wait for a message about your payment.", "ur": "اپنی رقم کے پیغام کا انتظار کریں۔"},
    "ask_again": {"en": "If this is wrong, ask a person to check again.", "ur": "اگر یہ غلط ہے تو کسی فرد سے دوبارہ جانچ کا کہیں۔"},
    "send_income_proof": {"en": "Take a photo of the paper and send it.", "ur": "کاغذ کی تصویر لیں اور بھیجیں۔"},
    "send_card_photo": {"en": "Put the card on a flat place and take the photo.", "ur": "کارڈ کو سیدھی جگہ پر رکھ کر تصویر لیں۔"},
    "retake_card_photo": {"en": "Put the card on a flat place and take the photo.", "ur": "کارڈ کو سیدھی جگہ پر رکھ کر تصویر لیں۔"},
    "wait_for_person": {"en": "We will send you a message when it is done.", "ur": "کام مکمل ہونے پر ہم آپ کو پیغام بھیجیں گے۔"},
    "give_consent": {"en": "Open the permission page and say yes.", "ur": "اجازت کا صفحہ کھولیں اور ہاں کہیں۔"},
}  # fmt: skip

# Guards whose reason must never reach the citizen (they would teach a fraudster what we check).
SILENT_GUARDS: Final = frozenset({
    "document_suspect", "card_id_mismatch", "document_needs_review", "identity_mismatch", "possible_duplicate",
    "duplicate_record", "anomaly_flag", "verified_sources_disagree", "rules_invalid",
})  # fmt: skip


def explanation_for(code: str, lang: str) -> Explanation:
    pictogram, next_code, texts = CITIZEN_TEMPLATES[code]
    used = lang if lang in texts else "ur"  # Sindhi falls back to Urdu until its templates are recorded
    return Explanation(
        reason_codes=[code], lang=used, sentences=list(texts[used]), next_step=NEXT_STEPS[next_code][used], ask_a_person=True,
        audio_keys=[f"reason.{code}", f"next.{next_code}"], pictogram=pictogram,
    )  # fmt: skip


def citizen_code(*, route: str, outcome: str, guards: Sequence[str], ask_proof: str | None, inp: DecisionInput,
                 failing: Sequence[RuleEvaluation], blockers: Sequence[RuleEvaluation]) -> str:  # fmt: skip
    if outcome == "approved":
        return "approved"
    if outcome == "rejected":
        variables = {v for e in failing for v in e.variables}
        if "verified_income_pkr" in variables:
            return "rejected_income_over_cap"
        if "receives_other_aid" in variables:
            return "rejected_other_aid"
        return "rejected_rule"
    if route == "ask_more":
        if ask_proof == "income_proof":
            return "ask_income_proof"
        cards = F.id_documents(inp)
        return "ask_rahat_id_retake" if cards and any(d.quality != "ok" for d in cards) else "ask_rahat_id"
    if "consent_missing" in guards:
        return "human_consent_needed"
    if any(g in SILENT_GUARDS for g in guards):
        return "human_check"
    if "registry_unavailable" in guards:
        return "human_registry_down"
    variables = {v for e in blockers for v in e.variables}
    if "identity_verified" in variables:
        return "human_identity_check"
    if "verified_income_pkr" in variables:
        return "human_income_unverified"
    return "human_check"


# --- the officer's handoff package ---------------------------------------------------------------------

SUGGESTED_QUESTIONS: Final[dict[str, str]] = {
    "income_proof": "Do you have a pay slip or a letter that shows your monthly income?",
    "rahat_id": "Can you show your Rahat card again, flat and in good light?",
    "identity_verified": "Please tell me your full name and date of birth exactly as written on your card.",
    "receives_other_aid": "Do you or anyone in your house get another relief payment now?",
    "duplicate": "Have you applied before, maybe with a different spelling of your name or another phone?",
    "document": "Can you bring the original card to the office so we can look at it together?",
    "registry_unavailable": "No question needed: check the registry again when it is back, then decide.",
    "consent_missing": "Would you like to give permission for the department to use your information for this application?",
}

_WHY_UNKNOWN: Final[dict[str, str]] = {
    "identity_verified": "identity_not_confirmed",
    "verified_income_pkr": "missing_in_registry",
}


def _why(variable: str, fact: Fact, inp: DecisionInput, floor: float) -> str:
    if not fact.known:
        if variable == "verified_income_pkr" and inp.registry_status == "unavailable":
            return "registry_unavailable"
        if variable == "identity_verified" and inp.identity is not None and inp.identity.status != "match":
            return f"identity_{inp.identity.status}"
        return _WHY_UNKNOWN.get(variable, "missing")
    if not fact.verified:
        return "declared_not_verified"
    if fact.confidence < floor:
        return "registry_stale" if variable == "verified_income_pkr" else "low_confidence"
    return "ok"


def _money(value: Any) -> str:
    return f"Rs {int(value):,}" if isinstance(value, int | float) and not isinstance(value, bool) else "unknown"


def understanding(inp: DecisionInput, facts: Mapping[str, Fact]) -> str:
    """What the engine believes, in plain words for an officer. No names or identifiers."""
    parts: list[str] = []
    identity = facts["identity_verified"]
    status = inp.identity.status if inp.identity else "not checked"
    if identity.known and identity.value:
        parts.append("Identity is confirmed by the signed card and the identity service.")
    elif identity.known:
        parts.append(f"Identity is contradicted (identity service: {status}; card signature or ID does not fit).")
    else:
        has_card = any(F.signed(d) for d in F.id_documents(inp))
        parts.append(f"Identity is not confirmed (identity service: {status}; signed card: {'yes' if has_card else 'no'}).")
    income = facts["verified_income_pkr"]
    band = inp.form.income_band.value or "not given"
    if income.known:
        age = F.income_age_days(inp)
        dated = f", {age} days old" if age is not None else ""
        parts.append(f"Verified income is {_money(income.value)} (from the {income.source}{dated}); declared band {band}.")
    else:
        parts.append(f"No verified income (registry: {inp.registry_status}); declared band {band}.")
    aid = facts["receives_other_aid"]
    if aid.known:
        parts.append(f"Other aid: {'yes' if aid.value else 'no'} ({'registry' if aid.verified else 'declared only'}).")
    else:
        parts.append("Other aid: unknown.")
    return " ".join(parts)


def build_handoff(*, inp: DecisionInput, facts: Mapping[str, Fact], evals: Sequence[RuleEvaluation], floor: float,
                  p_eligible: float, p_genuine: float, proof: str | None, guards: Sequence[str],
                  expected_costs: Mapping[str, float]) -> HandoffPackage:  # fmt: skip
    hard_unsettled = [e for e in evals if e.trace.hard and not e.settled("pass", floor)]
    uncertain: list[UncertainField] = []
    seen: set[str] = set()
    for e in hard_unsettled:
        for variable in e.variables:
            fact = facts.get(variable, F.UNKNOWN_FACT)
            why = _why(variable, fact, inp, floor)
            if why != "ok" and variable not in seen:
                seen.add(variable)
                uncertain.append(UncertainField(field=variable, value=fact.value, confidence=round(fact.confidence, 4), why=why))
    p_ok = round(p_eligible * p_genuine, 4)
    options = [
        Hypothesis(label="eligible_and_genuine", probability=p_ok),
        Hypothesis(label="not_eligible", probability=round((1 - p_eligible) * p_genuine, 4)),
        Hypothesis(label="not_genuine", probability=round(1 - p_genuine, 4)),
    ]
    order = {h.label: i for i, h in enumerate(options)}
    top = sorted(options, key=lambda h: (-h.probability, order[h.label]))[:2]
    rule_fired = hard_unsettled[0].rule_id if hard_unsettled else None
    question_key = proof
    if question_key is None:
        if "consent_missing" in guards:
            question_key = "consent_missing"
        elif any(g in ("possible_duplicate", "duplicate_record") for g in guards):
            question_key = "duplicate"
        elif any(g in ("document_suspect", "card_id_mismatch", "document_needs_review") for g in guards):
            question_key = "document"
        elif "registry_unavailable" in guards:
            question_key = "registry_unavailable"
        elif uncertain:
            question_key = uncertain[0].field
    evidence: dict[str, Any] = {
        "document_ids": [d.document_id for d in inp.documents],
        "document_signals": sorted({s.code for d in inp.documents for s in d.signals}),
        "identity_status": inp.identity.status if inp.identity else None,
        "registry_status": inp.registry_status,
    }
    if inp.duplicate is not None and inp.duplicate.band != "distinct":
        evidence["duplicate"] = {"band": inp.duplicate.band, "score": inp.duplicate.score, "other_person_ref": inp.duplicate.other_person_ref}
    if inp.anomaly is not None and inp.anomaly.flagged:
        evidence["anomaly"] = {"score": inp.anomaly.score, "reasons": list(inp.anomaly.reasons)}
    ocr = [d.ocr.raw_text for d in inp.documents if d.ocr.raw_text]
    if ocr:
        evidence["ocr_text"] = ocr
    return HandoffPackage(
        question=f"Should this {inp.program_slug} application be approved, and is it the real applicant?",
        understanding=understanding(inp, facts), uncertain_fields=uncertain, rule_fired=rule_fired, hypotheses=top,
        resolving_proof=proof, suggested_question=SUGGESTED_QUESTIONS.get(question_key or "", None), evidence=evidence,
        expected_costs=dict(expected_costs), guards=list(guards),
    )  # fmt: skip
