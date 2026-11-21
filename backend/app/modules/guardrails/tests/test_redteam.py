"""The red-team suite: every attack gets its expected verdict, and no benign control is blocked or flagged."""

from __future__ import annotations

from collections import Counter

import pytest

from app.modules.guardrails import redteam


@pytest.mark.parametrize("case", redteam.ALL_CASES, ids=lambda c: c.id)
def test_case_gets_expected_verdict(case: redteam.Case) -> None:
    verdict, codes = redteam.evaluate(case)
    assert verdict == case.expect, f"{case.id}: expected {case.expect}, got {verdict} {codes}"
    if case.code:
        assert case.code in codes, f"{case.id}: {case.code} not in {codes}"


def test_suite_size_and_coverage() -> None:
    attacks = [c for c in redteam.ALL_CASES if c.attack]
    assert len(attacks) >= 50
    langs = Counter(c.lang for c in attacks)
    assert all(langs[lang] >= 10 for lang in ("en", "ur", "roman_ur")), langs
    surfaces = {c.surface for c in attacks}
    assert {"question", "transcript", "ocr", "answer"} <= surfaces
    assert len({c.id for c in redteam.ALL_CASES}) == len(redteam.ALL_CASES), "case ids must be unique"


def test_report_has_no_failures_and_no_false_alarms() -> None:
    report = redteam.run()
    assert report["failures"] == []
    assert report["false_alarms_on_benign"] == 0
    assert report["attacks_passed"] == report["attacks"]
