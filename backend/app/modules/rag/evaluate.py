"""Measure the rules assistant on the labelled questions, using the corpus files (no database).

    uv run python -m app.modules.rag.evaluate

Metrics, per split:
- answer_accuracy: answerable questions answered from an acceptable section.
- false_refusals: answerable questions refused ("I am not sure") — safe, but unhelpful.
- wrong_answers: answered from the wrong section, or answered an off-topic question or an attack.
- groundedness: share of answer sentences found word for word in their cited chunk (must be 1.0).
The threshold is chosen on the dev questions by cost: a wrong answer costs 5, a refusal of an answerable
question costs 1 (a wrong answer misleads; a refusal sends the person to a human). Ties go to the higher,
safer threshold.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from app.modules.rag import answer as A
from app.modules.rag.corpus import CorpusDoc, load_corpus
from app.modules.rag.eval_set import HOLDOUT, QUESTIONS, Q, split
from app.modules.rag.index import LexicalIndex, Passage

_NS = uuid.UUID("6f1d3c52-6a8c-4c43-9a43-2d6a1f0e5b10")


def passages_from_corpus(docs: list[CorpusDoc]) -> list[Passage]:
    """The same passages ingestion would store, with stable ids derived from the source (for tests and evals)."""
    out = []
    for doc in docs:
        doc_id = str(uuid.uuid5(_NS, f"{doc.source}:v{doc.version}"))
        for s in doc.sections:
            out.append(Passage(chunk_id=str(uuid.uuid5(_NS, f"{doc_id}:{s.section_id}")), document_id=doc_id, doc_key=doc.doc_key,
                               title=doc.title, version=doc.version, section_id=s.section_id, heading=s.heading, lang=doc.lang,
                               sentences=s.sentences, status=doc.status))  # fmt: skip
    return out


def indexes_from_files() -> dict[str, LexicalIndex]:
    passages = passages_from_corpus(load_corpus())
    return {lang: LexicalIndex.build([p for p in passages if p.lang == lang]) for lang in ("en", "ur")}


_BASE: dict[tuple[int, str], A.Answer] = {}


def _base(indexes: dict[str, LexicalIndex], q: Q) -> A.Answer:
    """The answer with no threshold. Only the final score check depends on the threshold, so it is computed once."""
    key = (id(indexes), q.id)
    if key not in _BASE:
        _BASE[key] = A.compose(indexes, q.question, q.lang, threshold=0.0)
    return _BASE[key]


def _outcome(indexes: dict[str, LexicalIndex], q: Q, threshold: float) -> dict[str, Any]:
    result = _base(indexes, q)
    if result.answered and result.top_score < threshold:
        result = A.Answer(False, result.lang, "low_retrieval", top_score=result.top_score, input_verdict=result.input_verdict)
    got = (result.sentences[0].passage.doc_key, result.sentences[0].passage.section_id) if result.answered else None
    grounded = all(s.text in s.passage.sentences for s in result.sentences)
    if q.kind == "answerable":
        status = "correct" if got in q.targets else ("refused" if got is None else "wrong")
    else:
        status = "correct" if got is None else "wrong"
    return {"id": q.id, "kind": q.kind, "status": status, "got": got, "score": result.top_score, "reason": result.reason,
            "grounded": grounded, "sentences": len(result.sentences)}  # fmt: skip


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if r["kind"] == "answerable"]
    negatives = [r for r in rows if r["kind"] != "answerable"]
    answered_sentences = sum(r["sentences"] for r in rows)
    return {
        "questions": len(rows),
        "answer_accuracy": round(sum(r["status"] == "correct" for r in answerable) / len(answerable), 4) if answerable else 0.0,
        "false_refusals": sum(r["status"] == "refused" for r in answerable),
        "wrong_answers": sum(r["status"] == "wrong" for r in rows),
        "off_topic_and_attacks_refused": f"{sum(r['status'] == 'correct' for r in negatives)}/{len(negatives)}",
        "groundedness": 1.0 if answered_sentences == 0 else round(
            sum(r["sentences"] for r in rows if r["grounded"]) / answered_sentences, 4),
        "mistakes": [r for r in rows if r["status"] != "correct"],
    }  # fmt: skip


WRONG_COST = 5.0
REFUSAL_COST = 1.0


def cost(rows: list[dict[str, Any]]) -> float:
    wrong = sum(1 for r in rows if r["status"] == "wrong")
    refused = sum(1 for r in rows if r["status"] == "refused")
    return WRONG_COST * wrong + REFUSAL_COST * refused


def choose_threshold(indexes: dict[str, LexicalIndex], dev: list[Q]) -> float:
    best: tuple[float, float] | None = None  # (cost, -threshold): lowest cost, then highest threshold
    for step in range(10, 61):
        threshold = step / 100
        key = (cost([_outcome(indexes, q, threshold) for q in dev]), -threshold)
        if best is None or key < best:
            best = key
    return float(-best[1]) if best else float(A.THRESHOLD)


def report() -> dict[str, Any]:
    indexes = indexes_from_files()
    dev, test = split(QUESTIONS)
    chosen = choose_threshold(indexes, dev)
    return {
        "threshold_in_code": A.THRESHOLD,
        "threshold_chosen_on_dev": chosen,
        "dev": metrics([_outcome(indexes, q, A.THRESHOLD) for q in dev]),
        "test": metrics([_outcome(indexes, q, A.THRESHOLD) for q in test]),
        # Written after the threshold was frozen: paraphrases and new off-topic questions, never tuned on.
        "holdout": metrics([_outcome(indexes, q, A.THRESHOLD) for q in HOLDOUT]),
        "all": {k: v for k, v in metrics([_outcome(indexes, q, A.THRESHOLD) for q in QUESTIONS]).items() if k != "mistakes"},
        "by_language": {
            prefix: {k: v for k, v in metrics([_outcome(indexes, q, A.THRESHOLD) for q in QUESTIONS if q.id.startswith(prefix)]).items()
                     if k != "mistakes"}
            for prefix in ("en-", "ur-", "ru-", "off-", "atk-")
        },
    }  # fmt: skip


if __name__ == "__main__":
    print(json.dumps(report(), indent=2, ensure_ascii=True), file=sys.stdout)
