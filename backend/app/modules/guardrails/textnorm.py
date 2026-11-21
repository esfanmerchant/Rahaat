"""Text normalisation for matching. Shared by the guards, the voice interpreter and retrieval.

The output is a "skeleton" used only to compare text, never to show it: Unicode compatibility forms are
folded, combining marks and invisible characters are dropped, Arabic letter variants become their Urdu
form, Urdu and Arabic-Indic digits become 0-9, look-alike Cyrillic and Greek letters become Latin, and
everything is case-folded. Both sides of every comparison go through the same function, so a lexicon
entry written in proper Urdu still matches a transcript that used Arabic code points.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Arabic code points that Urdu writes differently, the heh family (folded to one letter, because speech
# engines mix them), final forms, digits and punctuation.
_FOLD: dict[int, str | None] = {
    ord("ي"): "ی",  # Arabic yeh -> Farsi/Urdu yeh
    ord("ى"): "ی",  # alef maksura
    ord("ے"): "ی",  # yeh barree (final) -> yeh
    ord("ك"): "ک",  # Arabic kaf -> keheh
    ord("ه"): "ہ",  # Arabic heh -> heh goal
    ord("ھ"): "ہ",  # heh doachashmee -> heh goal (matching only)
    ord("ة"): "ہ",  # teh marbuta
    ord("ۃ"): "ہ",  # teh marbuta goal
    ord("ە"): "ہ",  # ae
    ord("ں"): "ن",  # noon ghunna -> noon
    ord("ٱ"): "ا",  # alef wasla
    ord("ء"): None,  # standalone hamza
    ord("،"): ",",
    ord("؛"): ";",
    ord("؟"): "?",
    ord("۔"): ".",
    ord("٫"): ".",
    ord("٬"): ",",
}
for _i in range(10):
    _FOLD[0x0660 + _i] = str(_i)  # Arabic-Indic digits
    _FOLD[0x06F0 + _i] = str(_i)  # Extended (Urdu) digits

# Look-alike letters used to slip words past a filter ("ignоre" with a Cyrillic o).
_CONFUSABLES = {
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "і": "i", "ї": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    "һ": "h", "ɡ": "g", "ɑ": "a", "ı": "i", "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v",
    "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ζ": "z", "η": "n", "μ": "m",
}  # fmt: skip
for _src, _dst in _CONFUSABLES.items():
    _FOLD[ord(_src)] = _dst
    _FOLD[ord(_src.upper())] = _dst.upper()

_SPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[a-z]+|[؀-ۿݐ-ݿ]+")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "l"})
_LEET_TOKEN = re.compile(r"[a-z0-9@$!|]+")


def has_hidden_characters(text: str) -> bool:
    """Zero-width, bidirectional-control and other format characters, often used to hide words."""
    return any(unicodedata.category(ch) == "Cf" for ch in text)


@lru_cache(maxsize=4096)
def skeleton(text: str) -> str:
    """The matching form of `text` (see the module docstring). Pure and cached."""
    decomposed = unicodedata.normalize("NFKD", text)
    kept = []
    for ch in decomposed:
        category = unicodedata.category(ch)
        if category in ("Mn", "Me", "Cf") or ch == "ـ":  # combining marks, invisible format chars, tatweel
            continue
        kept.append(ch)
    folded = "".join(kept).translate(_FOLD).casefold()
    return _SPACE.sub(" ", folded).strip()


def tokens(text: str) -> list[str]:
    """Words and numbers of the skeleton. Latin and Urdu letters never merge into one token."""
    return _TOKEN.findall(skeleton(text))


def deleet(text: str) -> str:
    """'1gn0re prev10us' -> 'ignore previous'. Only tokens that mix letters with digits or symbols change."""
    def fix(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.isdigit() or word.isalpha():
            return word
        return word.translate(_LEET)

    return _LEET_TOKEN.sub(fix, text)


def squash(text: str) -> str:
    """Letters only, no separators: catches 'i g n o r e' and 'ig.no.re'."""
    return "".join(ch for ch in skeleton(text) if ch.isalpha())


def collapse_repeats(word: str) -> str:
    """'nahiiii' -> 'nahi', 'haaan' -> 'han'. Used as a second chance before fuzzy matching."""
    out: list[str] = []
    for ch in word:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def script_of(text: str) -> str:
    """'ur' when Urdu letters outnumber Latin ones, 'latin' when Latin wins, 'none' without letters."""
    urdu = sum(1 for ch in text if "؀" <= ch <= "ۿ" or "ݐ" <= ch <= "ݿ")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if urdu == 0 and latin == 0:
        return "none"
    return "ur" if urdu >= latin else "latin"
