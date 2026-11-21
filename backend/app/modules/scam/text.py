"""Text normalisation for English, Urdu (Arabic script) and Roman Urdu. Pure functions, no I/O.

Messages arrive with look-alike characters, zero-width joiners, Arabic instead of Urdu letter forms and
Urdu digits. Everything downstream (signals, the model, clustering) sees the same normalised form.
"""

from __future__ import annotations

import re
import unicodedata

# Zero-width and bidi control characters: scammers use them to split words past filters.
_INVISIBLE = re.compile("[­​-‏‪-‮⁠-⁤﻿ـ]")
_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
_LETTER_FORMS = str.maketrans(
    {
        "ي": "ی",  # Arabic yeh -> Urdu yeh
        "ى": "ی",  # alef maksura -> Urdu yeh
        "ك": "ک",  # Arabic kaf -> keheh
        "ه": "ہ",  # Arabic heh -> heh goal
        "ۃ": "ہ",
        "ة": "ہ",
    }
)
_DIGITS = str.maketrans({**{chr(0x0660 + i): str(i) for i in range(10)}, **{chr(0x06F0 + i): str(i) for i in range(10)}})
_SPACES = re.compile(r"[ \t\f\v  - 　]+")
_NEWLINES = re.compile(r"\s*\n\s*")

ARABIC_LETTER = re.compile("[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
LATIN_LETTER = re.compile(r"[A-Za-z]")
WORD = re.compile(r"[A-Za-z؀-ۿ]{2,}")

# Frequent Roman Urdu function words. Two or more of them in a Latin-script message mean Roman Urdu.
ROMAN_URDU_WORDS = frozenset(
    "aap ap apna apni apne hai hain he hy ho hoga hogi ka ki ke ko se par pe mein mai main me aur kar karein karen krein "
    "kren karain karo kare dein den dain do de liye liay lye raqam rakam rupay rupaye rupey paise paisay naam nam mubarak "
    "bhejein bhejen bhejain bhejo bhej jaldi foran fauran abhi nahi nahin nhi wapas warna hum ham hamare humein tasdeeq "
    "jama wala wali walay gaya gayi gaye hua hui hue bata batain batayen batadein yeh ye woh wo kya kia kyun kal aaj "
    "hasil wusool mosool milay milenge milegi inaam inam shamil apko aapko apke aapke hamari bhai ammi abbu beta beti".split()
)


def normalise(text: str) -> str:
    """NFKC, no invisible characters, one form per Urdu letter, ASCII digits, tidy whitespace. Case is kept."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = text.translate(_LETTER_FORMS).translate(_DIGITS)
    text = _DIACRITICS.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _NEWLINES.sub("\n", text)
    return text.strip()


def words(text: str) -> list[str]:
    return WORD.findall(text.lower())


def script_of(text: str) -> str:
    """'ur' for Arabic script, 'roman' for Roman Urdu, 'en' for English, 'mixed' when both scripts are heavy."""
    arabic = len(ARABIC_LETTER.findall(text))
    latin = len(LATIN_LETTER.findall(text))
    if arabic and latin and min(arabic, latin) / max(arabic, latin) > 0.4:
        return "mixed"
    if arabic > latin:
        return "ur"
    hits = sum(1 for w in words(text) if w in ROMAN_URDU_WORDS)
    return "roman" if hits >= 2 else "en"


def meaningful_words(text: str) -> int:
    """Words of two or more letters, after links, numbers and codes are taken out."""
    return len(words(text))
