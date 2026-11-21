"""Citizen explanations and the officer's handoff package."""

from __future__ import annotations

import re

import pytest

from app.contracts.decision import CostMatrix
from app.contracts.engine import RuleSetSnapshot
from app.modules.decision import explain
from app.modules.decision.engine import decide
from app.modules.decision.model import get_model
from app.seed import RULES_V1
from app.synth.golden import GOLDEN

RULES = RuleSetSnapshot(rule_version_id="v1", version_no=1, dsl=RULES_V1)
FORBIDDEN = re.compile(r"\d|%|score|threshold|probab|confiden|forg|fake|fraud|suspect|anomal|duplicate|signature|QR", re.IGNORECASE)


@pytest.mark.parametrize("code", sorted(explain.CITIZEN_TEMPLATES))
@pytest.mark.parametrize("lang", ["en", "ur", "sd"])
def test_every_template_is_short_safe_and_voiced(code: str, lang: str) -> None:
    e = explain.explanation_for(code, lang)
    assert 1 <= len(e.sentences) <= 3
    assert e.lang in ("en", "ur")
    assert e.pictogram in explain.PICTOGRAMS
    assert e.audio_keys[0] == f"reason.{code}" and e.audio_keys[1].startswith("next.")
    assert all(k == k.lower() for k in e.audio_keys)
    assert e.next_step and e.ask_a_person
    for sentence in [*e.sentences, e.next_step]:
        assert not FORBIDDEN.search(sentence), (code, sentence)
        if e.lang == "en":
            assert len(sentence.split()) <= 14, sentence  # short sentences for a grade-5 reader


def test_urdu_text_is_in_urdu_script() -> None:
    for code in explain.CITIZEN_TEMPLATES:
        for sentence in explain.explanation_for(code, "ur").sentences:
            assert re.search(r"[؀-ۿ]", sentence) and not re.search(r"[A-Za-z]", sentence)


def test_citizen_never_learns_why_a_case_was_flagged() -> None:
    model = get_model()
    for name in ("forged_card_signature_invalid", "signed_card_for_another_id", "identity_mismatch", "possible_duplicate",
                 "same_person_twice", "anomaly_flagged", "verified_incomes_disagree"):  # fmt: skip
        result = decide(GOLDEN[name][0](), RULES, CostMatrix(), model)
        assert result.explanation.reason_codes == ["human_check"], name
        assert result.handoff is not None and result.handoff.guards, name  # staff still see the reason


def test_handoff_package_is_complete_for_an_unsettled_income() -> None:
    result = decide(GOLDEN["registry_income_missing"][0](), RULES, CostMatrix(), get_model())
    handoff = result.handoff
    assert handoff is not None
    assert handoff.question and handoff.understanding and "No verified income" in handoff.understanding
    assert handoff.rule_fired == "income_cap"
    assert [f.field for f in handoff.uncertain_fields] == ["verified_income_pkr"]
    assert handoff.uncertain_fields[0].why == "missing_in_registry"
    assert len(handoff.hypotheses) == 2 and handoff.hypotheses[0].probability >= handoff.hypotheses[1].probability
    assert handoff.resolving_proof == "income_proof" and handoff.suggested_question
    assert set(handoff.expected_costs) >= {"human", "ask_proof"}
    assert "Zainab" not in handoff.understanding  # no names in the summary


def test_every_citizen_code_is_reachable_from_the_golden_set() -> None:
    model = get_model()
    seen = {decide(build(), RULES, CostMatrix(), model).explanation.reason_codes[0] for build, _, _ in GOLDEN.values()}
    missing = set(explain.CITIZEN_TEMPLATES) - seen - {"rejected_rule"}  # no rule in v1 maps to the generic rejection
    assert not missing, missing
