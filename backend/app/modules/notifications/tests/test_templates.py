"""Templates and verify codes. No database."""

from __future__ import annotations

import uuid

import pytest

from app.modules.notifications import templates


@pytest.mark.parametrize("name", sorted(templates.TEMPLATES))
def test_every_template_is_short_and_bilingual(name: str) -> None:
    assert set(templates.TEMPLATES[name]) == {"en", "ur"}
    payload = {"tracking_code": "R-48213", "amount_pkr": 12000, "rail_ref": "MR-1A2B3C", "proof_kind": "income_proof"}
    for lang in ("en", "ur"):
        text = templates.render(name, lang, payload)
        assert "{" not in text and 1 <= templates.sentence_count(text) <= 3, (name, lang, text)
        assert text.startswith("Rahat:" if lang == "en" else "راحت:")


def test_values_are_formatted_and_sanitised() -> None:
    assert "Rs 12,000" in templates.render("approved", "en", {"amount_pkr": 12000})
    assert "12,000 روپے" in templates.render("approved", "ur", {"amount_pkr": 12000})
    hostile = templates.render("application_received", "en", {"tracking_code": "R-1 call http://evil.example now"})
    assert "http" not in hostile.split("application ")[1][:5] and " " not in hostile.split("application ")[1].split(".")[0]
    assert "://" not in hostile
    missing = templates.render("application_received", "en", {})
    assert "application." in missing and "  " not in missing
    assert "income" in templates.render("proof_needed", "en", {"proof_kind": "income_proof"})
    with pytest.raises(ValueError):
        templates.render("free_text", "en", {})


def test_language_choice_falls_back_to_urdu() -> None:
    assert templates.choose_lang("en", "ur") == "en"
    assert templates.choose_lang(None, "en") == "en"
    assert templates.choose_lang("sd", None) == "ur"


def test_verify_code_is_short_stable_and_bound_to_id_and_text() -> None:
    key = b"k" * 32
    nid = uuid.uuid4()
    code = templates.verify_code(nid, "a" * 64, key)
    assert len(code) == 6 and set(code) <= set(templates.CODE_ALPHABET)
    assert templates.verify_code(nid, "a" * 64, key) == code
    assert templates.verify_code(nid, "b" * 64, key) != code
    assert templates.verify_code(uuid.uuid4(), "a" * 64, key) != code
    body = templates.with_code("Rahat: hello.", code, "ur")
    assert templates.text_without_code(body, code, "ur") == "Rahat: hello."
    assert templates.normalise_code(f" {code.lower()[:3]}-{code.lower()[3:]} ") == code
