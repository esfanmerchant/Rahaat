"""Choose the model's regularisation and the abstain rules without touching the test families.

    uv run python -m app.modules.scam.tune

Nested cross-validation over the training families: each outer fold of families is held out in turn, the
whole pipeline is trained on the rest, and every candidate is scored by expected cost per message with the
same costs the router uses (a missed scam 100, a false alarm 30, a person's look 3, the wrong kind of scam 1).
The chosen setting is the lowest expected cost among those with no wrong-side auto answer (no silent guess);
it goes into `model.PARAMS` and `engine.DEFAULT_RULES` by hand. Run on 21 Nov: text C 1.0, stacker C 0.3, the
text-agreement rule off, expected cost 0.90 per message, 0 wrong-side auto answers over 2,676 training messages.
"""

from __future__ import annotations

import hashlib
import itertools
import sys
from dataclasses import replace
from typing import Any

from app.modules.scam import corpus
from app.modules.scam.engine import DEFAULT_COSTS, DEFAULT_RULES, DecisionRules, ScamCosts, decide
from app.modules.scam.evaluate import SCAM, _verifier
from app.modules.scam.model import PARAMS, _folds, train
from app.modules.scam.signals import analyse

OUTER_FOLDS = 4
OUTER_SEED = 7


def cost(label: str, choice: str | None, route: str, costs: ScamCosts = DEFAULT_COSTS) -> float:
    if choice is None or route != "auto":
        return costs.human_review
    if (choice in SCAM) != (label in SCAM):
        return costs.missed_scam if label in SCAM else costs.false_alarm
    return costs.wrong_kind if choice != label else 0.0


def main(argv: list[str]) -> int:
    rows = corpus.load()
    train_rows = [r for r in rows if r["split"] == "train"]
    verify = _verifier(rows)
    outer = _folds(train_rows, OUTER_FOLDS, OUTER_SEED)
    data_hash = hashlib.sha256(corpus.corpus_bytes()).hexdigest()
    model_grid = [{"c_text": c_text, "c_stack": c_stack} for c_text, c_stack in itertools.product((1.0, 4.0), (0.3, 1.0))]
    rule_grid = [replace(DEFAULT_RULES, real_text_max=r, mixed_logit=m) for r, m in itertools.product((0.2, 0.35, 1.0), (1.5, 2.0))]
    signals = [analyse(str(r["text"]), r.get("sender")) for r in train_rows]
    results: list[tuple[float, dict[str, Any], DecisionRules, dict[str, float]]] = []
    for overrides in model_grid:
        params = PARAMS | overrides
        totals: dict[int, list[float]] = {i: [0.0, 0, 0, 0, 0, 0] for i in range(len(rule_grid))}
        for fold in range(OUTER_FOLDS):
            fit = [r for r, f in zip(train_rows, outer, strict=True) if f != fold]
            held = [(r, s) for r, s, f in zip(train_rows, signals, outer, strict=True) if f == fold]
            model = train(fit, data_hash=data_hash, params=params)
            for i, rules in enumerate(rule_grid):
                for row, sig in held:
                    res = decide(sig, model, verify=verify, rules=rules)
                    label, choice, route = str(row["label"]), res.decision.choice, res.decision.route
                    t = totals[i]
                    t[0] += cost(label, choice, route)
                    t[1] += 1
                    t[2] += choice is None
                    t[3] += route == "auto" and (choice in SCAM) != (label in SCAM)
                    t[4] += label not in SCAM and choice in SCAM
                    t[5] += label in SCAM and choice is not None and choice not in SCAM
        for i, rules in enumerate(rule_grid):
            t = totals[i]
            n = t[1]
            stats = {"cost_per_message": round(t[0] / n, 4), "abstained": round(t[2] / n, 4), "auto_wrong_side": int(t[3]),
                     "false_alarms": int(t[4]), "misses": int(t[5]), "messages": int(n)}  # fmt: skip
            results.append((stats["cost_per_message"], overrides, rules, stats))
            print(overrides, {"real_text_max": rules.real_text_max, "mixed_logit": rules.mixed_logit}, stats, flush=True)
    best = min(results, key=lambda item: item[0])
    print("\nlowest expected cost:", best[1], {"real_text_max": best[2].real_text_max, "mixed_logit": best[2].mixed_logit}, best[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
