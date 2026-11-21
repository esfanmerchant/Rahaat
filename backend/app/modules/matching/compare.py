"""Are two person records the same person? Field comparisons, one score, three bands. Pure functions.

    compare(a, b) -> Comparison(score=0.97, band="possible", fields={"phone": "different", ...})

The score is a Fellegi-Sunter style match probability: each field adds the log-odds that its agreement
or disagreement carries, on top of a prior for two records that share a blocking key. The weights are set
from what each field means in Pakistani records and stated below; the bands are then measured on labelled
messy fixtures (fixtures.py), and the numbers are reported, not tuned to look good.

Bands:
- same: score >= LINK_SCORE, the names agree (>= NAME_LINK), a corroborating identifier agrees (the same
  national ID, or the same date of birth and the same phone) and no identifier contradicts. Linked
  automatically, logged, reversible by an officer.
- possible: score >= REVIEW_SCORE, or any pair that shares a national ID. A person decides
  (duplicate_review case); the engine treats it as a guard.
- distinct: everything else.

A name alone can never reach `same`: without an agreeing identifier the best a pair can get is `possible`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Final, Literal

from app.modules.matching.names import NameScore, best_name_score, name_key

Agreement = Literal["same", "near", "different", "unknown"]
Band = Literal["same", "possible", "distinct"]

PRIOR: Final = -3.0  # log-odds that two records sharing a blocking key are one person (about 5 %)
LINK_SCORE: Final = 0.95
REVIEW_SCORE: Final = 0.5
NAME_LINK: Final = 0.90
# Name weight by name score, linear between the knots.
NAME_KNOTS: Final = ((0.0, -6.0), (0.55, -5.0), (0.70, -2.0), (0.80, 0.5), (0.88, 2.5), (0.92, 4.0), (0.97, 5.0), (1.0, 5.0))
WEIGHTS: Final[dict[str, dict[str, float]]] = {
    # A person has one national ID; a typo in one digit still points at the same person.
    "national_id": {"same": 6.0, "near": 2.5, "different": -3.5},
    # Dates of birth are rarely shared by two people with similar names; typos happen.
    "dob": {"same": 4.0, "near": 1.5, "different": -3.5},
    # Phones are shared in households and by helpers, and change often: weak either way.
    "phone": {"same": 1.5, "different": -0.5},
    "gender": {"same": 0.3, "different": -3.0},
    "district": {"same": 0.4, "different": -0.4},
}
CONFLICTING: Final = ("national_id", "dob", "phone", "gender")


@dataclass(frozen=True, slots=True)
class PersonRecord:
    """What dedupe compares. Identifiers stay inside the server: they are never logged or returned."""

    ref: str
    names: tuple[str | None, ...] = ()
    dob: str | None = None
    gender: str | None = None
    district: str | None = None
    national_id: str | None = None  # clear value, when known, so a one-digit typo can be recognised
    national_id_hash: str | None = None  # blind index, when only that is known
    phone: str | None = None
    phone_hash: str | None = None


@dataclass(frozen=True, slots=True)
class Comparison:
    name: NameScore
    fields: dict[str, Agreement]
    weights: dict[str, float]
    score: float
    band: Band
    corroborated: bool
    conflicts: tuple[str, ...]
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def evidence(self) -> dict[str, object]:
        """For staff and the audit trail: what agreed and what did not. No names or identifiers."""
        return {
            "name_score": self.name.score, "name_aligned": self.name.aligned, "name_token_set": self.name.token_set,
            "fields": dict(self.fields), "weights": {k: round(v, 3) for k, v in self.weights.items()}, "score": self.score,
            "band": self.band, "corroborated": self.corroborated, "conflicts": list(self.conflicts), "reasons": list(self.reasons),
        }  # fmt: skip


# --- field comparisons -----------------------------------------------------------------------------------


def valid_dob(value: str | None, today: date | None = None) -> date | None:
    """A real date between 1900 and today, or None. Impossible dates (30 February, the future) are unknown."""
    if not value:
        return None
    text = str(value).strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        return None
    limit = today or date(2026, 11, 21)
    return day if date(1900, 1, 1) <= day <= limit else None


def compare_dob(a: str | None, b: str | None) -> Agreement:
    left, right = valid_dob(a), valid_dob(b)
    if left is None or right is None:
        return "unknown"
    if left == right:
        return "same"
    digits_a, digits_b = left.strftime("%Y%m%d"), right.strftime("%Y%m%d")
    one_digit = sum(x != y for x, y in zip(digits_a, digits_b, strict=True)) == 1
    swapped = left.year == right.year and left.month == right.day and left.day == right.month
    if one_digit or swapped or abs((left - right).days) <= 1:
        return "near"
    return "different"


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def compare_national_id(a: PersonRecord, b: PersonRecord) -> Agreement:
    left, right = _digits(a.national_id), _digits(b.national_id)
    if left and right:
        if left == right:
            return "same"
        if len(left) == len(right):
            diffs = [i for i, (x, y) in enumerate(zip(left, right, strict=True)) if x != y]
            transposed = len(diffs) == 2 and diffs[1] == diffs[0] + 1 and left[diffs[0]] == right[diffs[1]] and left[diffs[1]] == right[diffs[0]]
            if len(diffs) == 1 or transposed:
                return "near"  # a typo or a wrong check digit
        return "different"
    if a.national_id_hash and b.national_id_hash:
        return "same" if a.national_id_hash == b.national_id_hash else "different"
    return "unknown"


def compare_phone(a: PersonRecord, b: PersonRecord) -> Agreement:
    left, right = _digits(a.phone), _digits(b.phone)
    if left and right:
        return "same" if left == right else "different"
    if a.phone_hash and b.phone_hash:
        return "same" if a.phone_hash == b.phone_hash else "different"
    return "unknown"


_GENDER: Final = {"m": "male", "male": "male", "man": "male", "mard": "male", "مرد": "male", "f": "female", "female": "female",
                  "woman": "female", "aurat": "female", "عورت": "female", "خاتون": "female"}  # fmt: skip


def compare_plain(a: str | None, b: str | None, mapping: dict[str, str] | None = None) -> Agreement:
    def norm(value: str | None) -> str:
        text = " ".join(str(value or "").casefold().split())
        return mapping.get(text, text) if mapping else text

    left, right = norm(a), norm(b)
    if not left or not right:
        return "unknown"
    return "same" if left == right else "different"


def name_weight(score: float) -> float:
    for (x0, y0), (x1, y1) in zip(NAME_KNOTS, NAME_KNOTS[1:], strict=False):
        if score <= x1:
            return y0 + (y1 - y0) * (score - x0) / (x1 - x0) if x1 > x0 else y1
    return NAME_KNOTS[-1][1]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, z))))


def compare(a: PersonRecord, b: PersonRecord) -> Comparison:
    """Compare two records. Symmetric: compare(a, b) and compare(b, a) give the same score and band."""
    name = best_name_score(a.names, b.names)
    fields: dict[str, Agreement] = {
        "national_id": compare_national_id(a, b), "dob": compare_dob(a.dob, b.dob), "phone": compare_phone(a, b),
        "gender": compare_plain(a.gender, b.gender, _GENDER), "district": compare_plain(a.district, b.district),
    }  # fmt: skip
    has_names = name.score > 0 or name.aligned > 0
    weights: dict[str, float] = {"prior": PRIOR}
    if has_names:
        weights["name"] = name_weight(name.score)
    for key, agreement in fields.items():
        weights[key] = WEIGHTS[key].get(agreement, 0.0)
    score = round(_sigmoid(sum(weights.values())), 4)
    corroborated = fields["national_id"] == "same" or (fields["dob"] == "same" and fields["phone"] == "same")
    conflicts = tuple(key for key in CONFLICTING if fields[key] == "different")
    reasons: list[str] = []
    band: Band
    if score >= LINK_SCORE and name.score >= NAME_LINK and corroborated and not conflicts:
        band = "same"
        reasons.append("names_agree_and_identifier_agrees")
    elif score >= REVIEW_SCORE or fields["national_id"] == "same":
        band = "possible"
        if fields["national_id"] == "same" and name.score < NAME_LINK:
            reasons.append("same_national_id_different_name")
        elif score >= LINK_SCORE and not corroborated:
            reasons.append("names_agree_without_identifier")
        elif conflicts:
            reasons.append("identifier_conflict:" + ",".join(conflicts))
        else:
            reasons.append("middle_score")
    else:
        band = "distinct"
        reasons.append("low_score")
    return Comparison(name=name, fields=fields, weights=weights, score=score, band=band, corroborated=corroborated,
                      conflicts=conflicts, reasons=tuple(reasons))  # fmt: skip


# --- blocking --------------------------------------------------------------------------------------------


def blocking_keys(record: PersonRecord) -> set[str]:
    """Cheap keys; only records sharing at least one are compared. Several passes, so one bad field is not fatal."""
    keys: set[str] = set()
    digits = _digits(record.national_id)
    if digits:
        keys.add(f"id:{digits}")
    elif record.national_id_hash:
        keys.add(f"idh:{record.national_id_hash}")
    phone = _digits(record.phone)
    if phone:
        keys.add(f"ph:{phone}")
    elif record.phone_hash:
        keys.add(f"phh:{record.phone_hash}")
    born = valid_dob(record.dob)
    if born is not None:
        keys.add(f"dob:{born.isoformat()}")
    for text in record.names:
        key = name_key(text)
        if key:
            keys.add(f"nk:{key}")
    return keys


def candidate_pairs(records: Iterable[PersonRecord]) -> set[tuple[int, int]]:
    """Index pairs that share a blocking key: the only pairs dedupe ever scores."""
    index: dict[str, list[int]] = {}
    items = list(records)
    for i, record in enumerate(items):
        for key in blocking_keys(record):
            index.setdefault(key, []).append(i)
    pairs: set[tuple[int, int]] = set()
    for members in index.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pairs.add((members[x], members[y]))
    return pairs


BAND_ORDER: Final[dict[str, int]] = {"distinct": 0, "possible": 1, "same": 2}


def worst(comparisons: Iterable[Comparison]) -> Comparison | None:
    """The comparison that matters most: the highest band, then the highest score."""
    best: Comparison | None = None
    for item in comparisons:
        if best is None or (BAND_ORDER[item.band], item.score) > (BAND_ORDER[best.band], best.score):
            best = item
    return best
