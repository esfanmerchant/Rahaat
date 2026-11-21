"""Names as Pakistani records spell them: normalise, transliterate, key and compare. Pure functions.

    parse_name("Mst. Zenab Bibi d/o Muhammad Ali")  -> ParsedName(tokens=("zenab",), ...)
    name_similarity("Mohammad Aslam", "محمد اسلم")   -> 1.0
    name_key("Muhammed Aslam Khan")                 -> "aslm+kn"   (blocking key)

What is normalised away, and why:
- Unicode: NFKC, case folding, accents; in Arabic script the diacritics, the tatweel and the letters that
  have two code points (Arabic and Urdu yeh, kaf and heh, alef forms) are unified.
- Relations: everything after "son of", "s/o", "d/o", "w/o", "bin", "bint", "walad", "ولد", "بنت", "زوجہ"
  is the father's or husband's name, not this person's.
- Honorifics and prefixes: Mst., Mrs., Syed, Haji, Mian, Hafiz, Dr. ... and their Urdu forms are dropped.
- Common name parts that carry almost no identity: every spelling of Muhammad (Mohammad, Muhammed, Mohd,
  Md, M., محمد ...) and the female suffixes Bibi, Bi Bi, Bb, Begum, Khatoon. They are kept apart as
  `common` tokens: two names never match because they share only these.

Urdu script is transliterated letter by letter into Latin. Short vowels are not written in Urdu, so the
result is a consonant skeleton (زینب -> "zynb"); the phonetic key then compares skeletons: vowels after the
first letter go, aspirated pairs (kh, gh, bh ...) and look-alike letters (q/k, v/w, z/dh) merge, doubled
letters collapse. "Zainab", "Zenab", "Zaynab" and "زینب" all have the key "znb".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

# --- Arabic-script normalisation and transliteration ----------------------------------------------------

_ARABIC_DIACRITICS: Final = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ARABIC_FOLD: Final = str.maketrans({
    "ي": "ی", "ى": "ی", "ے": "ی", "ۓ": "ی",  # yeh forms -> Urdu yeh
    "ك": "ک",  # Arabic kaf -> Urdu kaf
    "ه": "ہ", "ة": "ہ", "ۀ": "ہ", "ە": "ہ",  # heh, teh marbuta -> Urdu heh
    "أ": "ا", "إ": "ا", "ٱ": "ا", "آ": "ا",  # alef forms -> alef
    "ؤ": "و",  # waw with hamza -> waw
    "ء": "",  # hamza on its own
})  # fmt: skip
_URDU_TO_LATIN: Final[dict[str, str]] = {
    "ا": "a", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch",
    "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z",
    "ژ": "zh", "س": "s", "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a",
    "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n",
    "ں": "n", "و": "w", "ہ": "h", "ھ": "h", "ی": "y", "ئ": "i",
}  # fmt: skip
_ARABIC_LETTER: Final = re.compile("[؀-ۿ]")


def is_arabic_script(text: str) -> bool:
    return bool(_ARABIC_LETTER.search(text))


_ALEF, _WAW, _YEH, _HEH = "ا", "و", "ی", "ہ"


def transliterate(token: str) -> str:
    """Urdu-script token to a Latin consonant skeleton. Latin input is returned unchanged.

    Waw and yeh inside a word are vowels (o, i) unless a vowel letter follows them (پروین: parween);
    a final heh is the vowel a (فاطمہ: fatma) except after alef (شاہ: shah).
    """
    if not is_arabic_script(token):
        return token
    letters = [ch for ch in token if ch in _URDU_TO_LATIN]
    out: list[str] = []
    for i, ch in enumerate(letters):
        latin = _URDU_TO_LATIN[ch]
        nxt = letters[i + 1] if i + 1 < len(letters) else ""
        if i > 0 and ch == _WAW:
            latin = "w" if nxt in (_ALEF, _YEH) else "o"
        elif i > 0 and ch == _YEH:
            latin = "y" if nxt == _ALEF else "i"
        elif i > 0 and ch == _HEH and not nxt:
            latin = "h" if letters[i - 1] == _ALEF else "a"
        out.append(latin)
    return "".join(out)


# --- tokens that are not part of a person's own name ---------------------------------------------------

_RELATION_PATTERN: Final = re.compile(r"\b(?:s|d|w)\s*/\s*o\b|\b(?:son|daughter|wife)\s+of\b", re.IGNORECASE)
RELATION_WORDS: Final = frozenset({"bin", "bint", "binte", "walad", "ولد", "بنت", "بنت‌", "زوجہ", "زوجۂ", "دختر", "ابن", "بن"})
HONORIFICS: Final = frozenset({
    "mst", "musammat", "mussammat", "mrs", "mr", "ms", "miss", "syed", "syeda", "sayed", "sayyid", "haji", "hajji", "hajjan",
    "mian", "hafiz", "hafiza", "dr", "doctor", "maulana", "molana", "janab", "sahib", "sahiba", "sahab", "mohtarma",
    "مسماۃ", "مسمات", "محترمہ", "سید", "سیدہ", "حاجی", "حاجن", "میاں", "حافظ", "ڈاکٹر", "مولانا", "جناب", "صاحب", "صاحبہ",
})  # fmt: skip
MUHAMMAD: Final = frozenset({
    "muhammad", "mohammad", "muhammed", "mohammed", "mohamad", "muhamad", "mohamed", "muhamed", "mohammod", "mohd", "muhd",
    "mhd", "md", "m", "محمد",
})  # fmt: skip
FEMALE_SUFFIX: Final = frozenset({"bibi", "bb", "begum", "begam", "khatoon", "khatun", "bi", "بی", "بیگم", "خاتون", "بیبی"})
_SPLIT: Final = re.compile(r"[^\w؀-ۿ]+", re.UNICODE)


def _fold(text: str) -> str:
    """NFKC, case folding, accents off Latin letters; Arabic-script letters unified but never decomposed
    (NFKD would split hamza-yeh into yeh and a mark)."""
    text = unicodedata.normalize("NFKC", text)
    text = _ARABIC_DIACRITICS.sub("", text).translate(_ARABIC_FOLD)
    out: list[str] = []
    for ch in text.casefold():
        if is_arabic_script(ch):
            out.append(ch)
        else:
            out.extend(part for part in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(part))
    return "".join(out)


@dataclass(frozen=True, slots=True)
class ParsedName:
    """A name split into what identifies the person and what does not."""

    tokens: tuple[str, ...]  # the person's own name parts, in Latin (transliterated when written in Urdu)
    common: tuple[str, ...]  # Muhammad and female suffixes: kept, but never enough to match on
    dropped: tuple[str, ...]  # honorifics and the relation part ("d/o ...")
    script: str  # latin | arabic | mixed
    from_urdu: tuple[bool, ...] = ()  # per token: written in Urdu script (a consonant skeleton)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(phonetic_key(token) for token in self.tokens)


@lru_cache(maxsize=8192)
def parse_name(text: str | None) -> ParsedName:
    if not text or not text.strip():
        return ParsedName((), (), (), "latin", ())
    raw = text.strip()
    arabic = is_arabic_script(raw)
    latin = bool(re.search(r"[A-Za-z]", raw))
    script = "mixed" if arabic and latin else ("arabic" if arabic else "latin")
    folded = _fold(raw)
    dropped: list[str] = []
    relation = _RELATION_PATTERN.search(folded)
    if relation:
        dropped.append(folded[relation.start():].strip())
        folded = folded[: relation.start()]
    words = [w for w in _SPLIT.split(folded) if w]
    for i, word in enumerate(words):
        if word in RELATION_WORDS and i > 0:
            dropped.append(" ".join(words[i:]))
            words = words[:i]
            break
    tokens: list[str] = []
    urdu: list[bool] = []
    common: list[str] = []
    for i, word in enumerate(words):
        if word in HONORIFICS:
            dropped.append(word)
        elif word in MUHAMMAD and (word != "m" or i < len(words) - 1):
            common.append("muhammad")
        elif word in FEMALE_SUFFIX:
            if word == "bi" and common and common[-1] == "bibi":
                continue  # "Bi Bi" is one word written in two
            common.append("bibi")
        elif word.isdigit():
            dropped.append(word)
        else:
            latin_form = transliterate(word)
            if latin_form:
                tokens.append(latin_form)
                urdu.append(is_arabic_script(word))
    return ParsedName(tuple(tokens), tuple(common), tuple(dropped), script, tuple(urdu))


# --- phonetic key ----------------------------------------------------------------------------------------

_DIGRAPHS: Final = (("ph", "f"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("th", "t"), ("jh", "j"), ("ch", "c"),
                    ("sh", "s"), ("zh", "z"), ("ck", "k"), ("ee", "i"), ("oo", "u"))  # fmt: skip
_LETTER_MAP: Final = str.maketrans({"q": "k", "v": "w", "x": "k"})
_VOWELS: Final = frozenset("aeiouy")


@lru_cache(maxsize=16384)
def phonetic_key(token: str) -> str:
    """A consonant skeleton for South Asian names in Latin letters. Same key: probably the same name part."""
    word = re.sub(r"[^a-z]", "", transliterate(token).lower())
    if not word:
        return ""
    for pair, single in _DIGRAPHS:
        word = word.replace(pair, single)
    word = word.translate(_LETTER_MAP)
    if len(word) > 4 and word.endswith("h") and word[-2] in _VOWELS:
        word = word[:-1]  # Fatimah, Khadijah, Hajrah (but not Shah)
    first = "a" if word[0] in "aeiou" else word[0]  # a leading y is a consonant (Yasmin)
    out = [first]
    for i, ch in enumerate(word[1:], start=1):
        if ch in _VOWELS or ch == out[-1]:
            continue
        if ch == "h" and word[i - 1] in _VOWELS:
            continue  # an h after a vowel is written in one script and not the other (Ahmed/احمد, Chaudhry/چوہدری)
        out.append(ch)
    return "".join(out)


def name_key(text: str | None) -> str | None:
    """Blocking key: the sorted phonetic keys of the name's own parts. None when nothing identifying is left."""
    parsed = parse_name(text)
    keys = sorted({key for key in parsed.keys if key})
    return "+".join(keys)[:120] if keys else None


# --- similarity -----------------------------------------------------------------------------------------

PHONETIC_MATCH: Final = 0.95  # two parts with the same phonetic key count as at least this similar ...
PHONETIC_MIN_SPELLING: Final = 0.75  # ... when their spelling is not far apart (Shahid and Sadia share a key)


def token_similarity(a: str, b: str, *, cross_script: bool = False) -> float:
    """Jaro-Winkler, raised to PHONETIC_MATCH when the phonetic keys agree. Across scripts the spelling
    check is skipped: an Urdu skeleton has no short vowels, so its spelling is always far from the Latin."""
    if a == b:
        return 1.0
    score = float(JaroWinkler.normalized_similarity(a, b))
    key_a, key_b = phonetic_key(a), phonetic_key(b)
    if key_a and key_a == key_b and len(key_a) >= 2 and (cross_script or score >= PHONETIC_MIN_SPELLING):
        score = max(score, PHONETIC_MATCH)
    return score


def _aligned(short: ParsedName, long: ParsedName) -> float:
    """Each part of the shorter name paired with a different part of the longer one (greedy, best first).

    The weakest pair counts most: a shared family name must not carry a different given name
    ("Aslam Khan" against "Akram Khan").
    """
    pairs = sorted(
        ((token_similarity(a, b, cross_script=short.from_urdu[i] != long.from_urdu[j]), i, j)
         for i, a in enumerate(short.tokens) for j, b in enumerate(long.tokens)),
        reverse=True,
    )  # fmt: skip
    used_short: set[int] = set()
    used_long: set[int] = set()
    scores: list[float] = []
    for score, i, j in pairs:
        if i in used_short or j in used_long:
            continue
        used_short.add(i)
        used_long.add(j)
        scores.append(score)
    if not scores:
        return 0.0
    return 0.4 * (sum(scores) / len(scores)) + 0.6 * min(scores)


def _coverage(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Share of the longer name the shorter one has, counted in phonetic-key letters (the same in both scripts)."""
    letters_a = sum(max(1, len(phonetic_key(t))) for t in a)
    letters_b = sum(max(1, len(phonetic_key(t))) for t in b)
    return min(letters_a, letters_b) / max(letters_a, letters_b) if letters_a and letters_b else 0.0


@dataclass(frozen=True, slots=True)
class NameScore:
    score: float  # 0..1
    aligned: float  # word-by-word Jaro-Winkler with phonetic keys
    token_set: float  # rapidfuzz token-set ratio on the cleaned names
    coverage: float  # how much of the longer name the shorter one covers
    common_only: bool  # the names share nothing but Muhammad or a female suffix


def _score_parsed(a: ParsedName, b: ParsedName) -> NameScore:
    if not a.tokens or not b.tokens:
        return NameScore(0.0, 0.0, 0.0, 0.0, bool(set(a.common) & set(b.common)))
    short, long = (a, b) if len(a.tokens) <= len(b.tokens) else (b, a)
    aligned = min(_aligned(short, long), _aligned(long, short) if len(short.tokens) == len(long.tokens) else _aligned(short, long))
    coverage = _coverage(a.tokens, b.tokens)
    token_set = fuzz.token_set_ratio(" ".join(sorted(a.tokens)), " ".join(sorted(b.tokens))) / 100.0
    factor = 0.75 + 0.25 * coverage  # a dropped part lowers the score, at most by a quarter
    score = max(aligned, token_set) * factor
    return NameScore(round(score, 4), round(aligned, 4), round(token_set, 4), round(coverage, 4), False)


def score_names(a: str | None, b: str | None) -> NameScore:
    return _score_parsed(parse_name(a), parse_name(b))


def name_similarity(a: str | None, b: str | None) -> float:
    """0..1. Symmetric; 1.0 for the same name in another spelling, order, script or with honorifics."""
    return score_names(a, b).score


def best_name_score(names_a: tuple[str | None, ...], names_b: tuple[str | None, ...]) -> NameScore:
    """The best score over every pair of known forms (Latin and Urdu) of two people's names."""
    best = NameScore(0.0, 0.0, 0.0, 0.0, False)
    for left in names_a:
        for right in names_b:
            if left and right:
                current = score_names(left, right)
                if (current.score, current.aligned) > (best.score, best.aligned):
                    best = current
    return best
