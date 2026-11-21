"""Campaigns: reports whose text is one template with different numbers, links, names and spellings.

A message is reduced to its template (placeholders for links, phones, numbers and codes; one spelling per
common Roman Urdu word), cut into 5-character shingles and summarised by a 64-value MinHash. Two messages
with a MinHash agreement of `JOIN_AT` or more join the same campaign. A campaign's signature is taken from
its first message and never changes, so it is stable across restarts and replays. Pure functions.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any

from app.modules.scam.signals import EMAIL_IN_TEXT, PHONE_IN_TEXT, URL_PATTERN
from app.modules.scam.text import normalise

NUM_PERM = 64
SHINGLE = 5
JOIN_AT = 0.6
SIGNATURE_PREFIX = "mh1:"
_PRIME = 4294967311  # the first prime above 2**32
_CODE = re.compile(r"(?i)(?:\bcode|\bkod|(?<![؀-ۿ])کوڈ)\s*[:#.-]?\s*[A-Za-z0-9]{3}[\s-]?[A-Za-z0-9]{3}(?![A-Za-z0-9])")
_PUNCT = re.compile(r"[^\w\s<>#]+")
_SPACE = re.compile(r"\s+")
_CANONICAL = {
    "he": "hai", "hy": "hai", "ap": "aap", "k": "ke", "ky": "ke", "kay": "ke", "rupees": "rupay", "rupaye": "rupay", "rs": "rupay",
    "bhejen": "bhejein", "bhejain": "bhejein", "karen": "karein", "krein": "karein", "karain": "karein", "mubarik": "mubarak",
    "rakam": "raqam", "nam": "naam", "haasil": "hasil", "fauran": "foran", "abi": "abhi", "main": "mein", "me": "mein", "mai": "mein",
    "pe": "par", "per": "par", "or": "aur", "jamaa": "jama", "hen": "hain", "hn": "hain", "nmbr": "number", "no": "number",
}  # fmt: skip


def template_text(text: str) -> str:
    value = normalise(text).lower()
    value = URL_PATTERN.sub(" <u> ", value)
    value = EMAIL_IN_TEXT.sub(" <e> ", value)
    value = PHONE_IN_TEXT.sub(" <p> ", value)
    value = _CODE.sub(" ", value)
    value = re.sub(r"\d[\d,./-]*", "#", value)
    value = _PUNCT.sub(" ", value)
    return " ".join(_CANONICAL.get(word, word) for word in _SPACE.split(value) if word)


def template_hash(text: str) -> str:
    return hashlib.sha256(template_text(text).encode()).hexdigest()[:32]


@lru_cache(maxsize=1)
def _coefficients() -> tuple[Any, Any]:
    import numpy as np

    rng = np.random.default_rng(20261121)
    return rng.integers(1, 2**31, NUM_PERM, dtype=np.uint64), rng.integers(0, 2**31, NUM_PERM, dtype=np.uint64)


def minhash(text: str) -> list[int]:
    import numpy as np

    template = template_text(text) or "<empty>"
    shingles = {template[i: i + SHINGLE] for i in range(max(1, len(template) - SHINGLE + 1))}
    hashes = np.array(sorted(int.from_bytes(hashlib.blake2b(s.encode(), digest_size=4).digest(), "big") for s in shingles), dtype=np.uint64)
    a, b = _coefficients()
    values = (a[:, None] * hashes[None, :] + b[:, None]) % np.uint64(_PRIME)
    return [int(v) for v in values.min(axis=1)]


def similarity(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(1 for x, y in zip(left, right, strict=True) if x == y) / len(left)


def signature(values: list[int]) -> str:
    return SIGNATURE_PREFIX + "".join(f"{v:09x}" for v in values[:8])


def best_match(values: list[int], candidates: list[tuple[Any, list[int]]]) -> tuple[Any, float] | None:
    """The most similar candidate at or above JOIN_AT, as (key, similarity)."""
    best: tuple[Any, float] | None = None
    for key, other in candidates:
        score = similarity(values, other)
        if score >= JOIN_AT and (best is None or score > best[1]):
            best = (key, score)
    return best
