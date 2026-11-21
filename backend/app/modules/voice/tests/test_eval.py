"""The measured guarantees: no wrong-but-confident answer on unseen families, and honest abstention numbers."""

from __future__ import annotations

from app.modules.voice import evaluate
from app.modules.voice.interpret import CONFIDENCE_FLOOR
from app.modules.voice.synth import build, build_holdout, check_split


def test_dataset_is_large_split_by_family_and_deterministic() -> None:
    examples = build()
    assert len(examples) >= 300
    check_split(examples)
    train_families = {e.family for e in examples if e.split == "train"}
    test_families = {e.family for e in examples if e.split == "test"}
    assert train_families.isdisjoint(test_families)
    assert len(test_families) >= 30
    assert [e.transcript for e in build()] == [e.transcript for e in examples]  # fixed seed


def test_no_wrong_but_confident_answer_on_test_and_holdout() -> None:
    report = evaluate.report()
    assert report["test"]["wrong_but_confident"] == 0, report["test"]["wrong_examples"]
    assert report["holdout"]["wrong_but_confident"] == 0, report["holdout"]["wrong_examples"]
    assert report["train"]["wrong_but_confident"] == 0
    # The floor is not bought with silence: most answerable transcripts still get an answer.
    assert report["test"]["abstention_rate_on_answerable"] < 0.20
    assert report["test"]["accuracy"] > 0.85
    assert report["floor_chosen_on_train"] <= CONFIDENCE_FLOOR


def test_floor_sweep_shows_the_trade_off() -> None:
    report = evaluate.report()
    sweep = {row["floor"]: row for row in report["floor_sweep"]}
    assert sweep[0.0]["test_wrong"] > 0  # without a floor the interpreter does make confident mistakes
    assert sweep[CONFIDENCE_FLOOR]["test_wrong"] == 0
    assert sweep[0.9]["test_abstention"] > sweep[CONFIDENCE_FLOOR]["test_abstention"]


def test_holdout_is_separate() -> None:
    holdout = build_holdout()
    assert {e.split for e in holdout} == {"holdout"}
    assert {e.family for e in holdout}.isdisjoint({e.family for e in build()})
