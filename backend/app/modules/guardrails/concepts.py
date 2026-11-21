"""Concept matching in English, Urdu and Roman Urdu.

A rule is a set of concepts that must all appear within a short window of tokens, in any order. Order does
not matter because Urdu puts the verb last ("پچھلی ہدایات بھول جاؤ") and English puts it first ("ignore
previous instructions"). Words are compared on the text skeleton; long words also match with small typos,
and letter-digit swaps ("1gn0re") are undone in a second view of the text.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from app.modules.guardrails.textnorm import collapse_repeats, deleet, skeleton, tokens

FUZZY_MIN_LEN = 6
FUZZY_SCORE = 88.0


@dataclass(frozen=True, slots=True)
class Concept:
    name: str
    words: frozenset[str]
    phrases: tuple[tuple[str, ...], ...] = ()


def concept(name: str, entries: Iterable[str]) -> Concept:
    """Entries are written naturally; single words and multi-word phrases are separated here."""
    words: set[str] = set()
    phrases: list[tuple[str, ...]] = []
    for entry in entries:
        parts = tuple(tokens(entry))
        if not parts:
            continue
        if len(parts) == 1:
            words.add(parts[0])
        else:
            phrases.append(parts)
    return Concept(name, frozenset(words), tuple(phrases))


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    needs: tuple[str, ...]
    window: int = 8
    # Each entry is a group of concepts of which at least one must also appear (within the window).
    any_of: tuple[tuple[str, ...], ...] = ()
    # The rule does not fire when one of these concepts is anywhere in the text (for example a question word)...
    unless: tuple[str, ...] = ()
    # ...unless one of these is present too (an imperative overrides the question exemption).
    unless_overridden_by: tuple[str, ...] = ()


@dataclass(slots=True)
class Hits:
    """Where each concept occurs in one token view of the text."""

    positions: dict[str, list[int]] = field(default_factory=dict)

    def has(self, name: str) -> bool:
        return bool(self.positions.get(name))


def word_matches(token: str, words: frozenset[str]) -> bool:
    if token in words:
        return True
    squeezed = collapse_repeats(token)
    if squeezed != token and (squeezed in words or any(collapse_repeats(w) == squeezed for w in words)):
        return True
    if len(token) >= FUZZY_MIN_LEN:
        for word in words:
            if len(word) >= FUZZY_MIN_LEN and abs(len(word) - len(token)) <= 2 and fuzz.ratio(token, word) >= FUZZY_SCORE:
                return True
    return False


@lru_cache(maxsize=2048)
def views(text: str) -> tuple[tuple[str, ...], ...]:
    """The token list of the text, and of its de-leeted form when that differs."""
    base = tuple(tokens(text))
    unleet = tuple(tokens(deleet(skeleton(text))))
    return (base,) if unleet == base else (base, unleet)


def find(view: tuple[str, ...], concepts: Mapping[str, Concept]) -> Hits:
    hits = Hits()
    for name, item in concepts.items():
        found: list[int] = []
        for i, token in enumerate(view):
            if word_matches(token, item.words):
                found.append(i)
        for phrase in item.phrases:
            n = len(phrase)
            for i in range(len(view) - n + 1):
                if i not in found and all(word_matches(view[i + k], frozenset({phrase[k]})) for k in range(n)):
                    found.append(i)
        if found:
            hits.positions[name] = sorted(found)
    return hits


def _within_window(groups: list[list[int]], window: int) -> bool:
    """True when one position can be picked from every group so that all lie within `window` tokens."""
    if any(not g for g in groups):
        return False
    for anchor in sorted({p for g in groups for p in g}):
        if all(any(anchor <= p <= anchor + window for p in g) for g in groups):
            return True
    return False


def fired(hits: Hits, rules: Iterable[Rule]) -> list[str]:
    codes: list[str] = []
    for rule in rules:
        if rule.unless and any(hits.has(c) for c in rule.unless) and not any(hits.has(c) for c in rule.unless_overridden_by):
            continue
        groups = [hits.positions.get(name, []) for name in rule.needs]
        for alternatives in rule.any_of:
            groups.append(sorted({p for name in alternatives for p in hits.positions.get(name, [])}))
        if _within_window(groups, rule.window) and rule.code not in codes:
            codes.append(rule.code)
    return codes


def match(text: str, concepts: Mapping[str, Concept], rules: Iterable[Rule], *, present: Iterable[str] = ()) -> list[str]:
    """Codes of every rule that fires on any view of the text.

    `present` names concepts the caller already knows are in the text (a question mark, a phone number);
    they count for `unless` checks only, not for windows.
    """
    rule_list = list(rules)
    flags = list(present)
    codes: list[str] = []
    for view in views(text):
        hits = find(view, concepts)
        for name in flags:
            hits.positions.setdefault(name, [-1_000])
        for code in fired(hits, rule_list):
            if code not in codes:
                codes.append(code)
    return codes
