"""The mock identity service's matching rule: name similarity plus date of birth. Pure functions."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Literal

from rapidfuzz import fuzz

from app.mocks.registry import MockPerson

MatchStatus = Literal["match", "partial", "mismatch"]

STRONG_NAME = 0.90
WEAK_NAME = 0.70

_NOISE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    text = _NOISE.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def name_similarity(a: str | None, b: str | None) -> float:
    """0..1, insensitive to case, punctuation and word order ("Bibi Zainab" equals "Zainab Bibi")."""
    if not a or not b:
        return 0.0
    left, right = normalise_name(a), normalise_name(b)
    if not left or not right:
        return 0.0
    return round(fuzz.token_sort_ratio(left, right) / 100.0, 4)


def _same_day(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    try:
        return date.fromisoformat(a.strip()[:10]) == date.fromisoformat(b.strip()[:10])
    except ValueError:
        return False


def match(record: MockPerson, full_name: str | None, dob: str | None) -> tuple[MatchStatus, float]:
    """match: the name is close and the date of birth agrees. partial: one of the two is uncertain. mismatch: neither."""
    score = max(name_similarity(full_name, record.full_name), name_similarity(full_name, record.full_name_ur))
    dob_ok = _same_day(dob, record.dob)
    if score >= STRONG_NAME and dob_ok:
        return "match", score
    if score >= STRONG_NAME or (score >= WEAK_NAME and dob_ok):
        return "partial", score
    return "mismatch", score
