"""Measure the voice interpreter on the synthetic set: accuracy, abstention, wrong-but-confident answers.

    uv run python -m app.modules.voice.evaluate          metrics for both splits and the floor sweep

Definitions, per transcript:
- correct: answered, and the answer equals the gold label; or the gold is "abstain" and it abstained.
- wrong (wrong-but-confident): answered with a different value, or answered where a person would ask again.
  An answer is only given above the confidence floor, so every wrong answer is a confident one.
- abstained: asked again when the gold had an answer. Safe, but it costs the person one more try.
The floor is chosen on the training families only; the test families are never used to pick it.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from app.modules.voice import interpret as I
from app.modules.voice.synth import Example, build, build_holdout, check_split, counts


@dataclass(frozen=True, slots=True)
class Outcome:
    example: Example
    choice: str | None
    raw: float  # the score before the floor; 0 when a hard rule abstained


def run_all(examples: list[Example]) -> list[Outcome]:
    out = []
    for e in examples:
        r = I.interpret(e.question_key, e.transcript, stt_confidence=e.stt_confidence, expected_name=e.expected_name, floor=0.0)
        out.append(Outcome(e, None if r.abstained else r.choice, r.raw_score if not r.abstained else 0.0))
    return out


def metrics(outcomes: list[Outcome], floor: float) -> dict[str, Any]:
    n = len(outcomes)
    correct = wrong = abstained = answerable = answered_correct = 0
    wrong_ids: list[dict[str, Any]] = []
    for o in outcomes:
        answered = o.choice is not None and o.raw >= floor
        gold = o.example.gold
        if gold != "abstain":
            answerable += 1
        if answered and o.choice == gold:
            correct += 1
            answered_correct += 1
        elif answered:
            wrong += 1
            wrong_ids.append({"family": o.example.family, "q": o.example.question_key, "text": o.example.transcript,
                              "gold": gold, "got": o.choice, "score": round(o.raw, 3)})  # fmt: skip
        elif gold == "abstain":
            correct += 1
        else:
            abstained += 1
    answered_total = answered_correct + wrong
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "abstention_rate_on_answerable": round(abstained / answerable, 4) if answerable else 0.0,
        "wrong_but_confident": wrong,
        "precision_when_answering": round(answered_correct / answered_total, 4) if answered_total else 1.0,
        "coverage_on_answerable": round(answered_correct / answerable, 4) if answerable else 0.0,
        "wrong_examples": wrong_ids[:20],
    }


def choose_floor(train: list[Outcome], grid: list[float] | None = None) -> float:
    """The lowest floor with no wrong-but-confident answer on the training families."""
    grid = grid or [round(0.50 + 0.01 * i, 2) for i in range(46)]
    for floor in grid:
        if metrics(train, floor)["wrong_but_confident"] == 0:
            return floor
    return grid[-1]


def report(per_family: int = 8) -> dict[str, Any]:
    examples = build(per_family=per_family)
    check_split(examples)
    outcomes = run_all(examples)
    train = [o for o in outcomes if o.example.split == "train"]
    test = [o for o in outcomes if o.example.split == "test"]
    holdout = run_all(build_holdout())
    chosen = choose_floor(train)
    sweep = []
    for floor in sorted({0.0, 0.5, 0.6, chosen, 0.65, I.CONFIDENCE_FLOOR, 0.75, 0.8, 0.85, 0.9}):
        m_train, m_test, m_hold = metrics(train, floor), metrics(test, floor), metrics(holdout, floor)
        sweep.append({"floor": floor, "train_wrong": m_train["wrong_but_confident"], "test_wrong": m_test["wrong_but_confident"],
                      "test_abstention": m_test["abstention_rate_on_answerable"], "test_accuracy": m_test["accuracy"],
                      "holdout_wrong": m_hold["wrong_but_confident"]})  # fmt: skip
    by_question: dict[str, list[Outcome]] = defaultdict(list)
    for o in test:
        by_question[o.example.question_key].append(o)
    by_family = Counter(o.example.family for o in test)
    return {
        "dataset": counts(examples),
        "floor_in_code": I.CONFIDENCE_FLOOR,
        "floor_chosen_on_train": chosen,
        "train": metrics(train, I.CONFIDENCE_FLOOR),
        "test": metrics(test, I.CONFIDENCE_FLOOR),
        "holdout": metrics(holdout, I.CONFIDENCE_FLOOR),
        "cost_of_floor": {
            "test_abstention_without_floor": metrics(test, 0.0)["abstention_rate_on_answerable"],
            "test_wrong_without_floor": metrics(test, 0.0)["wrong_but_confident"],
            "test_abstention_at_floor": metrics(test, I.CONFIDENCE_FLOOR)["abstention_rate_on_answerable"],
        },
        "test_by_question": {q: {k: v for k, v in metrics(os, I.CONFIDENCE_FLOOR).items() if k != "wrong_examples"}
                             for q, os in sorted(by_question.items())},  # fmt: skip
        "test_families": len(by_family),
        "floor_sweep": sweep,
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, ensure_ascii=True), file=sys.stdout)
