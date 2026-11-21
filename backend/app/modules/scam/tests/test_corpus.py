"""The committed synthetic corpus: reproducible, split by family, mock data only, real messages exact. DB-free."""

from __future__ import annotations

import re
from collections import defaultdict

from app.modules.scam import corpus
from app.modules.scam.signals import match_template

REAL_PHONE = re.compile(r"\b03\d{2}[- ]?\d{7}\b|\+92 ?3\d{2}[- ]?\d{7}")  # mock-lint: allow
REAL_ID = re.compile(r"\b(?!00000-)\d{5}-\d{7}-\d\b")


def test_the_committed_corpus_is_exactly_what_the_seeded_generator_writes() -> None:
    assert corpus.serialise(corpus.generate()) == corpus.corpus_bytes(), "run: uv run python -m app.modules.scam.corpus"


def test_train_and_test_share_no_family_and_every_class_is_tested() -> None:
    rows = corpus.load()
    splits: dict[str, set[str]] = defaultdict(set)
    tested: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        splits[row["family"]].add(row["split"])
        if row["split"] == "test":
            tested[row["label"]].add(row["lang"])
    assert all(len(s) == 1 for s in splits.values()), "a family is in one split only"
    for label in corpus.SCAM_LABELS:
        assert tested[label] == {"en", "ur", "roman"}, (label, tested[label])
    assert tested["legit_program_message"] and tested["unknown"]
    assert {r["label"] for r in rows if r["split"] == "train"} == set(corpus.SCAM_LABELS) | set(corpus.LEGIT_LABELS)


def test_every_message_is_synthetic_and_uses_mock_numbers_only() -> None:
    for row in corpus.load():
        assert row["synthetic"] is True
        for value in (row["text"], row.get("sender") or ""):
            assert not REAL_PHONE.search(value) and not REAL_ID.search(value), row["id"]


def test_real_rahat_messages_are_written_exactly_as_we_send_them() -> None:
    program = [r for r in corpus.load() if r["label"] == "legit_program_message"]
    assert len(program) == 560
    for row in program:
        match = match_template(row["text"])
        assert match is not None and match.template == row["family"].split(".", 1)[1], row["id"]
        if row["code"]:
            assert match.code == row["code"]["value"] and row["code"]["genuine"]
