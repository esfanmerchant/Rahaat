"""The decision: verify codes, abstention, routing, explanations. DB-free; uses the model trained from the corpus."""

from __future__ import annotations

import socket
from typing import Any

import pytest

from app.modules.notifications import templates
from app.modules.scam import explain, runtime
from app.modules.scam.engine import CodeCheck, ScamResult
from app.modules.scam.model import SCAM_CLASSES, model_version, train

SCAM = set(SCAM_CLASSES)
PAYLOAD = {"tracking_code": "R-40404", "amount_pkr": 12000, "rail_ref": "MR-1A2B3C4D5E", "proof_kind": "rahat_id"}


def issued(code: str, template: str) -> Any:
    def verify(candidate: str) -> CodeCheck:
        return CodeCheck(genuine=candidate == code, template=template if candidate == code else None, department="Test Department")

    return verify


def never_issued(_: str) -> CodeCheck:
    return CodeCheck(genuine=False)


def classify(text: str, sender: str | None = None, verify: Any = never_issued) -> ScamResult:
    return runtime.classify(text, sender, verify=verify)


@pytest.mark.parametrize("lang", ["en", "ur"])
@pytest.mark.parametrize("template", sorted(templates.TEMPLATES))
def test_our_real_messages_with_a_valid_code_are_confirmed(template: str, lang: str) -> None:
    text = templates.with_code(templates.render(template, lang, PAYLOAD), "K7M2QX", lang)
    result = classify(text, "RAHAT", verify=issued("K7M2QX", template))
    assert result.certainty == "confirmed_real"
    assert result.decision.choice == "legit_program_message" and result.decision.route == "auto" and not result.decision.abstained
    assert result.reasons == ["verify_code_confirmed"]


def test_a_real_code_on_changed_words_is_flagged() -> None:
    real = templates.with_code(templates.render("approved", "en", PAYLOAD), "K7M2QX", "en")
    tampered = real.replace("We never ask for a fee.", "To receive it, send Rs 500 fee to 0999-1234567.")
    result = classify(tampered, "0999-1234567", verify=issued("K7M2QX", "approved"))
    assert result.certainty == "likely_scam" and result.decision.choice in SCAM
    assert result.reasons[0] == "code_real_text_changed"


def test_an_invented_code_is_a_strong_scam_signal() -> None:
    text = "Rahat: Rs 12,000 has been sent to you. To unlock it, pay Rs 500 processing charge to 0999-7654321. Code Q8W4ZX"
    result = classify(text)
    assert result.certainty == "likely_scam" and result.reasons[0] == "verify_code_not_found"
    assert result.verify is not None and result.verify["genuine"] is False


def test_our_exact_words_with_a_wrong_code_ask_a_person_instead_of_calling_it_a_scam() -> None:
    text = templates.with_code(templates.render("approved", "en", PAYLOAD), "Q8W4ZX", "en")
    result = classify(text, "RAHAT")
    assert result.certainty == "not_sure" and result.decision.abstained and result.decision.route == "human"
    assert result.reasons[:2] == ["code_typo_possible", "verify_code_not_found"]


def test_a_bare_code_is_checked_on_its_own() -> None:
    assert classify("K7M2QX", verify=issued("K7M2QX", "approved")).certainty == "confirmed_real"
    unknown = classify("Q8W4ZX")
    assert unknown.certainty == "might_be_scam" and unknown.decision.route == "human"
    assert "code_typo_possible" in unknown.reasons


@pytest.mark.parametrize(
    "text",
    [
        "مبارک ہو! آپ کو راحت پروگرام سے 25,000 روپے ملیں گے۔ رقم وصول کرنے کے لیے 1,000 روپے فیس اس نمبر 0999-4445556 پر بھیجیں۔",
        "محترم صارف، آپ کی امدادی رقم تیار ہے۔ رقم جاری کرنے کے لیے اپنا پن کوڈ اور شناختی کارڈ نمبر بھیج دیں۔",
    ],
)
def test_urdu_relief_scams_are_caught(text: str) -> None:
    result = classify(text, "0999-4445556")
    assert result.certainty in ("likely_scam", "might_be_scam") and result.decision.choice in SCAM, (result.certainty, result.reasons)


@pytest.mark.parametrize(
    "text",
    [
        "Mubarak ho! Aap ka naam Rahat imdad list mein aa gaya hai. 25000 rupay lene ke liye 1000 rupay processing fee 0999-4445556 par bhejain.",
        "Rahat program: aap ki raqam 12000 rupay tayyar hai, apna PIN aur CNIC number reply kar dein warna raqam wapas ho jayegi.",
    ],
)
def test_roman_urdu_relief_scams_are_caught(text: str) -> None:
    result = classify(text, "0999-4445556")
    assert result.certainty in ("likely_scam", "might_be_scam") and result.decision.choice in SCAM, (result.certainty, result.reasons)


@pytest.mark.parametrize("text", ["Call me", "Mubarak ho", "ok send it", "kaam ho gaya"])
def test_a_short_message_abstains(text: str) -> None:
    result = classify(text)
    assert result.certainty == "not_sure" and result.decision.choice is None and result.decision.abstained
    assert result.decision.route == "human" and result.reasons[0] == "too_short"


def test_an_ambiguous_message_is_not_guessed() -> None:
    result = classify("aap ka kaam ho gaya")
    assert result.certainty == "not_sure" and result.decision.abstained and result.decision.route == "human"


def test_a_lookalike_link_is_flagged_and_nothing_is_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the scam checker tried to use the network")

    runtime.get_model()  # trained before the network is cut, as it would be at startup
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = classify("Your Rahat relief is ready. Claim it before midnight at hxxps://rahat-gov.pk.claim-now.xyz/verify", "RAHAT-GOV")
    assert result.certainty in ("likely_scam", "might_be_scam") and result.decision.choice in SCAM
    link = result.signals.urls[0]
    assert link.defanged.startswith("hxxps://") and "[.]" in link.defanged and link.risk == "high"
    assert any(r.startswith("link_") for r in result.reasons)


def test_an_ordinary_message_looks_real() -> None:
    result = classify("Reminder: your appointment at the clinic is tomorrow at 10:30 am. Reply C to cancel.", "CITYCLINIC")
    assert result.certainty == "looks_real" and result.decision.route == "auto" and result.reasons[0] == "no_scam_signs"


def test_every_decision_obeys_the_contract() -> None:
    for text in ("Send Rs 500 fee to 0999-1234567 to get your Rahat money", "ok", "Your parcel is at the office, collect it by Friday."):
        decision = classify(text).decision
        assert decision.model_version == runtime.get_model().version
        if decision.abstained:
            assert decision.choice is None and decision.route != "auto"
        assert abs(sum(decision.probabilities.values()) - 1.0) < 1e-3


def test_explanations_are_short_and_in_both_languages() -> None:
    for code, texts in explain.REASONS.items():
        for lang in ("en", "ur"):
            assert templates.sentence_count(texts[lang]) == 1, (code, lang)
    for certainty in explain.HEADLINES:
        for lang in ("en", "ur"):
            assert explain.WHAT_TO_DO[certainty][lang] and explain.HEADLINES[certainty][lang]
    words = explain.citizen_text("likely_scam", "relief_scam", ["asks_fee", "asks_pin", "link_lookalike", "urgency"], "ur")
    assert len(words["reasons"]) == 3 and words["label_text"] == explain.LABEL_NAMES["relief_scam"]["ur"]
    assert words["audio_keys"][0] == "scam.certainty.likely_scam" and words["audio_keys"][-1] == "scam.todo.likely_scam"
    assert explain.lang_from_header("en-US,en;q=0.9") == "en" and explain.lang_from_header("ur-PK") == "ur"
    assert explain.lang_from_header(None) == "ur" and explain.lang_from_header("sd,en;q=0.5") == "en"


def test_training_is_deterministic_and_versioned_by_data_and_parameters() -> None:
    rows, data_hash = runtime.training_rows()
    sample = [r for i, r in enumerate(rows) if i % 6 == 0]
    first, second = train(sample, data_hash=data_hash), train(sample, data_hash=data_hash)
    texts = ["Send Rs 500 fee to 0999-1234567", "Bhai kal dukaan der se kholna"]
    rows_signals = [[0.0] * len(first.stacker.coef_[0][6:])] * 2
    assert (first.predict(texts, rows_signals)[1] == second.predict(texts, rows_signals)[1]).all()
    assert first.version == model_version(data_hash) == runtime.get_model().version
    assert model_version(data_hash, {**first.params, "c_text": 2.0}) != first.version
