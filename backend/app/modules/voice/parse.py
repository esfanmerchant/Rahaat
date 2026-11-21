"""Turn a transcript into a sequence of typed items: numbers, yes, no, "I don't know", markers and noise.

Three passes:
1. Spelling: a token that is not a known word is matched to the closest known word ("paanc" -> "paanch",
   "nahiii" -> "nahi") when it is long enough and clearly closer to one meaning than to any other.
2. Phrases: the longest known phrase wins at each position, so "pata nahi" is "I don't know" and never "no".
3. Context: ambiguous words get their meaning from their neighbours ("do log" is two people, "kar do" is a
   verb; "saath hazaar" is sixty thousand, "mere saath" is "with me").
Numbers are then assembled the Indian way ("ek lakh bees hazaar" = 120,000; "sade teen hazaar" = 3,500).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final

from rapidfuzz import fuzz

from app.modules.guardrails.textnorm import collapse_repeats, tokens
from app.modules.voice import lexicon as L

FUZZY_MIN_LEN: Final = 4
FUZZY_MIN_SCORE: Final = 84.0
FUZZY_MARGIN: Final = 7.0
# A misread number is the worst mistake, so a number word must beat every other number word by more.
NUMBER_MARGIN: Final = 15.0
_CANDIDATE_FLOOR: Final = 60.0

# Item kinds that carry meaning for an answer.
CONTENT_KINDS: Final = frozenset({"NUM", "MULT", "YES", "NO", "UNKNOWN", "CONF_YES", "CONF_NO", "ZERO", "ALONE", "TOPIC", "AMBIG"})


@dataclass(slots=True)
class Item:
    kind: str
    start: int
    end: int  # exclusive token index
    text: str
    value: float | None = None
    fuzzy: float = 100.0  # lowest spelling-match score among the item's tokens (100 = exact)
    weak: float = 1.0  # below 1 when an ambiguous word was read as a number from thin context


@dataclass(slots=True)
class Parsed:
    tokens: list[str]
    items: list[Item]
    fuzzy_tokens: int = 0
    noise_tokens: int = 0
    filler_tokens: int = 0
    flags: set[str] = field(default_factory=set)

    def kinds(self) -> list[str]:
        return [i.kind for i in self.items]

    def has(self, kind: str) -> bool:
        return any(i.kind == kind for i in self.items)

    def content(self) -> list[Item]:
        return [i for i in self.items if i.kind in CONTENT_KINDS]


# --- tables --------------------------------------------------------------------------------------------

_PHRASE_TABLES: tuple[tuple[str, list[tuple[str, ...]]], ...] = (
    ("UNKNOWN", L.UNKNOWN),
    ("ZERO", L.ZERO_INCOME),
    ("CONF_NO", L.CONFIRM_NO),
    ("NO", L.NO),
    ("YES", L.YES),
    ("CONF_YES", L.CONFIRM_YES),
    ("CORR", L.CORRECTION),
    ("ALONE", L.ALONE),
    ("PERIOD", L.PERIOD_OTHER),
    ("MONTH", L.PERIOD_MONTH),
    ("BESIDES", L.BESIDES),
    ("APPROX", L.APPROX),
    ("HEDGE", L.HEDGE),
    ("MORE", L.MORE),
    ("LESS", L.LESS),
    ("ALT", L.ALTERNATIVE),
    ("AND", L.CONJUNCTION),
    ("UNIT", L.PEOPLE_UNITS),
    ("CHILD", L.CHILD_ADULT),
    ("CURRENCY", L.CURRENCY),
    ("LINK", L.RANGE_LINK),
    ("NAME_THIS", L.NAME_THIS),
    ("FILLER", L.FILLERS),
    ("NEUTRAL", L.NEUTRAL),
)
_NEGATOR_WORDS: Final = frozenset(p[0] for p in L.NEGATORS if len(p) == 1)
_ENGLISH_PRONOUN_AFTER_DO: Final = frozenset({"not", "you", "i", "we", "they", "it", "this", "that"})
_DIGITS = re.compile(r"^\d+(?:[.,]\d+)*$")
# Words that change an answer's meaning. An unreadable token that looks like one of them is a warning sign.
_DANGER_WORDS: Final = tuple(tokens(" ".join([
    "nahi", "nahin", "never", "not", "shayad", "maybe", "perhaps", "pata", "maloom", "malum", "matlab", "sorry", "galat",
    "ghalat", "wrong", "ilawa", "alawa", "siwa", "taqreeban", "lagbhag",
])))
DANGER_SCORE: Final = 72.0


@dataclass(frozen=True, slots=True)
class _Tables:
    by_first: dict[str, list[tuple[tuple[str, ...], str]]]
    numbers: dict[str, int]
    multipliers: dict[str, int]
    fractions: dict[str, float]
    fraction_prefix: dict[str, float]
    ambiguous: dict[str, int]
    topics: dict[str, dict[str, list[tuple[str, ...]]]]
    vocabulary: dict[str, tuple[str, str]]  # word -> meaning (kind, value) for spelling correction


@lru_cache(maxsize=1)
def tables() -> _Tables:
    by_first: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    vocabulary: dict[str, tuple[str, str]] = {}

    def add_vocab(word: str, meaning: tuple[str, str]) -> None:
        vocabulary.setdefault(word, meaning)

    for kind, phrases in _PHRASE_TABLES:
        for phrase in phrases:
            by_first.setdefault(phrase[0], []).append((phrase, kind))
            for word in phrase:
                add_vocab(word, (kind, "") if len(phrase) == 1 else ("PART", word))
    numbers = L.number_words()
    multipliers = L.multiplier_words()
    fractions = {tokens(k)[0]: v for k, v in L.FRACTION_WORDS.items()}
    prefix = {tokens(k)[0]: v for k, v in L.FRACTION_PREFIX.items()}
    ambiguous = {tokens(k)[0]: v for k, v in L.AMBIGUOUS.items()}
    for word, value in numbers.items():
        vocabulary[word] = ("NUM", str(value))
    for word, value in multipliers.items():
        vocabulary[word] = ("MULT", str(value))
    for word, fvalue in {**fractions, **prefix}.items():
        vocabulary[word] = ("FRAC", str(fvalue))
    for word in ambiguous:
        vocabulary[word] = ("AMBIG", word)
    topics: dict[str, dict[str, list[tuple[str, ...]]]] = {}
    for question, phrases in L.TOPIC_WORDS.items():
        for phrase in phrases:
            topics.setdefault(phrase[0], {}).setdefault(question, []).append(phrase)
            for word in phrase:
                add_vocab(word, ("TOPIC", question))
    for first in by_first:
        by_first[first].sort(key=lambda entry: -len(entry[0]))
    return _Tables(by_first, numbers, multipliers, fractions, prefix, ambiguous, topics, vocabulary)


# --- pass 1: spelling ----------------------------------------------------------------------------------


def _correct(token: str, t: _Tables) -> tuple[str, float]:
    """(word, score). Unknown tokens that are close to exactly one meaning become that word."""
    if token in t.vocabulary or _DIGITS.match(token):
        return token, 100.0
    squeezed = collapse_repeats(token)
    if squeezed in t.vocabulary:
        return squeezed, 95.0
    if len(token) < FUZZY_MIN_LEN:
        return token, 0.0
    best: dict[tuple[str, str], tuple[float, str]] = {}
    for word, meaning in t.vocabulary.items():
        if len(word) < FUZZY_MIN_LEN - 1 or abs(len(word) - len(token)) > 2:
            continue
        score = max(fuzz.ratio(token, word), fuzz.ratio(squeezed, word))
        if score >= _CANDIDATE_FLOOR and score > best.get(meaning, (0.0, ""))[0]:
            best[meaning] = (score, word)
    if not best:
        return token, 0.0
    ranked = sorted(((score, word, meaning) for meaning, (score, word) in best.items()), reverse=True)
    top_score, top_word, top_meaning = ranked[0]
    if top_score < FUZZY_MIN_SCORE:
        return token, 0.0
    for score, _, meaning in ranked[1:]:
        margin = NUMBER_MARGIN if (top_meaning[0] == "NUM" and meaning[0] == "NUM") else FUZZY_MARGIN
        if top_score - score < margin:
            return token, -1.0  # close to two different meanings ("tene": teen or ten?): refuse to guess
    return top_word, top_score


_SINGLE_FILLERS: Final = frozenset(p[0] for p in L.FILLERS if len(p) == 1 and p[0] != "so")


def _looks_dangerous(word: str) -> bool:
    return any(fuzz.ratio(word, danger) >= DANGER_SCORE for danger in _DANGER_WORDS if abs(len(danger) - len(word)) <= 2)


# --- pass 2 and 3 --------------------------------------------------------------------------------------


def _digits_value(token: str) -> float | None:
    if "," in token:
        head, *rest = token.split(",")
        if all(len(part) == 3 for part in rest) or (len(rest) == 1 and len(rest[0]) == 2):
            # 15,000 and the South Asian 1,50,000 both read as plain thousands separators.
            return float(token.replace(",", ""))
        return None
    try:
        return float(token)
    except ValueError:
        return None


def parse(text: str, *, question: str | None = None) -> Parsed:
    t = tables()
    raw = tokens(text)
    corrected: list[str] = []
    scores: list[float] = []
    parsed = Parsed(tokens=[], items=[])
    for token in raw:
        word, score = _correct(token, t)
        if word in _SINGLE_FILLERS:
            parsed.filler_tokens += 1
            continue
        if score <= 0 and len(word) >= 3 and _looks_dangerous(word):
            parsed.flags.add("possible_negation_or_hedge")
        corrected.append(word)
        scores.append(score)
        if score == -1.0:
            parsed.flags.add("ambiguous_spelling")
        elif 0 < score < 100:
            parsed.fuzzy_tokens += 1
    parsed.tokens = corrected

    i = 0
    n = len(corrected)
    while i < n:
        word = corrected[i]
        score = scores[i]
        matched = False
        # topic phrases (question-specific statements) first, only for the question being asked
        for q, phrases in t.topics.get(word, {}).items():
            if q != question:
                continue
            for phrase in sorted(phrases, key=len, reverse=True):
                if tuple(corrected[i : i + len(phrase)]) == phrase:
                    parsed.items.append(Item("TOPIC", i, i + len(phrase), " ".join(phrase), fuzzy=min(scores[i : i + len(phrase)])))
                    i += len(phrase)
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue
        for phrase, kind in t.by_first.get(word, []):
            if tuple(corrected[i : i + len(phrase)]) == phrase:
                if len(phrase) == 1 and (word in t.numbers or word in t.multipliers or word in t.ambiguous):
                    break  # a single word that is also a number is decided below
                parsed.items.append(Item(kind, i, i + len(phrase), " ".join(phrase), fuzzy=min(scores[i : i + len(phrase)])))
                i += len(phrase)
                matched = True
                break
        if matched:
            continue
        if _DIGITS.match(word):
            value = _digits_value(word)
            parsed.items.append(Item("NUM" if value is not None else "NOISE", i, i + 1, word, value=value))
            if value is None:
                parsed.flags.add("unreadable_number")
        elif word in t.numbers:
            parsed.items.append(Item("NUM", i, i + 1, word, value=float(t.numbers[word]), fuzzy=score))
        elif word in t.multipliers:
            parsed.items.append(Item("MULT", i, i + 1, word, value=float(t.multipliers[word]), fuzzy=score))
        elif word in t.fractions:
            parsed.items.append(Item("NUM", i, i + 1, word, value=t.fractions[word], fuzzy=score))
        elif word in t.fraction_prefix:
            parsed.items.append(Item("FRACP", i, i + 1, word, value=t.fraction_prefix[word], fuzzy=score))
        elif word in t.ambiguous:
            parsed.items.append(Item("AMBIG", i, i + 1, word, value=float(t.ambiguous[word]), fuzzy=score))
        elif word in _NEGATOR_WORDS:
            parsed.items.append(Item("NEG", i, i + 1, word, fuzzy=score))
        else:
            parsed.items.append(Item("NOISE", i, i + 1, word, fuzzy=score))
            parsed.noise_tokens += 1
        i += 1
    _resolve_ambiguous(parsed, question)
    _polite_particles(parsed)
    return parsed


_POLITE: Final = frozenset({"ji", "jee", "jii", "g", "\u062c\u06cc"})


def _polite_particles(parsed: Parsed) -> None:
    """A lone "ji" next to "nahi" or "pata nahi" is politeness, not a yes ("nahi... ji", "ji, pata nahi")."""
    items = parsed.items
    for idx, item in enumerate(items):
        if item.kind != "YES" or item.text not in _POLITE:
            continue
        neighbours = [items[k] for k in (idx - 1, idx + 1) if 0 <= k < len(items)]
        if any(n.kind in ("NO", "NEG", "UNKNOWN", "CONF_NO") for n in neighbours):
            item.kind = "FILLER"


_AFTER_NUMBER_KINDS: Final = frozenset({"UNIT", "MULT", "CHILD", "CURRENCY", "ALT", "NEG", "NO", "CORR", "AND", "LINK", "LESS", "MORE"})


def _resolve_ambiguous(parsed: Parsed, question: str | None) -> None:
    items = parsed.items
    t = tables()
    numeric = question in ("household_size", "income_band")
    others_content = [i for i in items if i.kind in CONTENT_KINDS and i.kind not in ("AMBIG", "YES", "CONF_YES")]
    for idx, item in enumerate(items):
        if item.kind != "AMBIG":
            continue
        prev = items[idx - 1] if idx > 0 else None
        nxt = items[idx + 1] if idx + 1 < len(items) else None
        word = item.text
        prev_token = parsed.tokens[item.start - 1] if item.start > 0 else ""
        next_token = parsed.tokens[item.end] if item.end < len(parsed.tokens) else ""
        alone = not others_content
        unit_next = nxt is not None and nxt.kind in ("UNIT", "MULT", "CURRENCY", "CHILD")
        if word == "no":
            if numeric and unit_next:
                item.kind = "NOISE"  # "no log": nine people (nau), or "no people"? Never guessed.
                parsed.flags.add("nine_or_no")
            else:
                item.kind = "NO"
            continue
        if word in ("saath", "sath"):
            item.kind = "NUM" if (nxt is not None and nxt.kind == "MULT") else "NEUTRAL"
            continue
        if word == "so":
            item.kind = "MULT" if (prev is not None and prev.kind == "NUM") else "FILLER"
            continue
        if word in ("do", "دو"):
            if prev_token in L.VERB_STEMS or next_token in _ENGLISH_PRONOUN_AFTER_DO:
                item.kind = "NEUTRAL"  # the verb "give" ("kar do", "paise do") or English "do"
            elif (nxt is not None and nxt.kind in _AFTER_NUMBER_KINDS) or next_token in ("hain", "ہین", "hi", "ہی"):
                item.kind = "NUM"
            elif prev is not None and prev.kind in ("ALT", "LINK", "NEG", "NO", "CORR") and numeric:
                item.kind = "NUM"
            elif alone and numeric:
                item.kind, item.weak = "NUM", 0.80
                parsed.flags.add("ambiguous_number_word")
            else:
                item.kind = "NOISE"
                parsed.flags.add("ambiguous_number_word")
            continue
        if word in ("tera", "bara"):
            if unit_next:
                item.kind, item.weak = "NUM", 0.90
            elif alone and numeric:
                item.kind, item.weak = "NUM", 0.75
                parsed.flags.add("ambiguous_number_word")
            else:
                item.kind = "NEUTRAL"  # "your", "big"
            continue
        if word in ("ek", "ik"):
            if (nxt is not None and nxt.kind in _AFTER_NUMBER_KINDS) or next_token in ("hi", "ہی"):
                item.kind = "NUM"
            elif alone and numeric:
                item.kind, item.weak = "NUM", 0.85
            else:
                item.kind = "NEUTRAL"  # "ek baat", "ek dafa": the article, not a count
            continue
        item.kind = "NOISE"
    for item in items:
        if item.kind == "NUM" and item.value is None:
            item.value = float(t.ambiguous.get(item.text, 0))


# --- numbers -------------------------------------------------------------------------------------------


@dataclass(slots=True)
class Mention:
    value: float
    start: int  # index into Parsed.items
    end: int
    has_multiplier: bool = False
    fuzzy: float = 100.0
    weak: float = 1.0  # lowest context multiplier of its words (see Item.weak)


def numbers(parsed: Parsed) -> list[Mention]:
    """Assemble number items into values. Fillers inside a number are skipped ("pandrah... umm... hazaar")."""
    items = parsed.items
    mentions: list[Mention] = []
    i = 0
    while i < len(items):
        item = items[i]
        if item.kind not in ("NUM", "MULT", "FRACP"):
            i += 1
            continue
        start = i
        total = 0.0
        current: float | None = None
        prefix = 0.0
        has_mult = False
        fuzzy_min = 100.0
        weak = 1.0
        last_kind = ""
        j = i
        while j < len(items):
            it = items[j]
            if it.kind == "FILLER":
                j += 1
                continue
            if it.kind == "FRACP" and last_kind in ("", "MULT"):
                prefix = it.value or 0.0
            elif it.kind == "NUM":
                v = it.value or 0.0
                if last_kind == "NUM" and current is not None and current in (20, 30, 40, 50, 60, 70, 80, 90) and 1 <= v <= 9 \
                        and items[j - 1].text in L.ENGLISH_TENS and it.text in L.ENGLISH_UNITS:
                    current += v  # English "twenty five"
                elif last_kind == "NUM":
                    break  # two bare numbers in a row are two mentions ("paanch chhe", "bees pachees")
                else:
                    current = v + prefix
                    prefix = 0.0
                weak = min(weak, it.weak)
            elif it.kind == "MULT":
                m = it.value or 1.0
                base = current if current is not None else 1.0
                if m >= 1000:
                    total += base * m
                    current = None
                else:
                    current = base * m
                has_mult = True
            else:
                break
            fuzzy_min = min(fuzzy_min, it.fuzzy if it.fuzzy > 0 else 100.0)
            last_kind = it.kind
            j += 1
        value = total + (current or 0.0)
        if last_kind:
            mentions.append(Mention(value, start, j, has_mult, fuzzy_min, weak))
        i = max(j, i + 1)
    return mentions
