"""Turn a retrieval score into the probability that the answer is right (Platt scaling on the labelled questions).

Fitted once, lazily, on the shipped corpus and every labelled question (answerable ones count as right when
the top section is acceptable; off-topic questions and attacks count as wrong at any score). Deterministic.
The probability is reported in the TypedDecision; the refusal itself uses the cost-chosen threshold.
"""

from __future__ import annotations

import math
from functools import lru_cache

from app.modules.rag.answer import answer_lang
from app.modules.rag.eval_set import QUESTIONS
from app.modules.rag.index import make_query


@lru_cache(maxsize=1)
def _coefficients() -> tuple[float, float]:
    from sklearn.linear_model import LogisticRegression

    from app.modules.rag.evaluate import indexes_from_files

    indexes = indexes_from_files()
    xs: list[list[float]] = []
    ys: list[int] = []
    for q in QUESTIONS:
        lang = answer_lang(q.question, q.lang)
        hits = indexes[lang].search(make_query(q.question, lang), k=1)
        score = hits[0].score if hits else 0.0
        right = bool(hits) and q.kind == "answerable" and (hits[0].passage.doc_key, hits[0].passage.section_id) in q.targets
        xs.append([score])
        ys.append(int(right))
    model = LogisticRegression(C=10.0).fit(xs, ys)
    return float(model.coef_[0][0]), float(model.intercept_[0])


def probability(score: float) -> float:
    try:
        a, b = _coefficients()
    except Exception:  # noqa: BLE001  (no corpus files on this host: report the raw score, clipped)
        return max(0.0, min(1.0, score))
    return round(1.0 / (1.0 + math.exp(-(a * score + b))), 4)
