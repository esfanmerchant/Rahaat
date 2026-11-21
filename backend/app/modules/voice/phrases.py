"""What the app says back: the read-back of an answer and the request to say it again.

Every sentence is a sequence of fixed clips, so it can be played from recordings: `voice_you_said`, then
the answer's own clip (`digit_5`, `count_12`, `answer_yes`, `income_15k_30k`), then `voice_is_that_right`.
The words for numbers, answers and income bands are the frontend's own strings (`shared/i18n/en.ts` and
`ur.ts`), so the text shown and the recording played always agree. The `voice_*` keys are new and need
recordings (listed in VOICE_KEYS for the audio script).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel

# New clips this module needs. English and Urdu, grade 5, at most three short sentences.
VOICE_KEYS: Final[dict[str, dict[str, str]]] = {
    "voice_you_said": {"en": "You said", "ur": "آپ نے کہا"},
    "voice_people": {"en": "people", "ur": "لوگ"},
    "voice_person": {"en": "person", "ur": "فرد"},
    "voice_is_that_right": {"en": "Is that right?", "ur": "کیا یہ ٹھیک ہے؟"},
    "voice_say_again": {
        "en": "Sorry, I did not understand. Please say it again, or tap a picture.",
        "ur": "معاف کیجیے، سمجھ نہیں آیا۔ دوبارہ بولیں، یا تصویر دبائیں۔",
    },
    "voice_one_answer": {
        "en": "I heard two different answers. Please say only one, or tap a picture.",
        "ur": "مجھے دو مختلف جواب سنائی دیے۔ صرف ایک جواب بولیں، یا تصویر دبائیں۔",
    },
    "voice_monthly": {
        "en": "Please say the money for one whole month, or tap a picture.",
        "ur": "پورے ایک مہینے کے پیسے بتائیں، یا تصویر دبائیں۔",
    },
    "voice_use_pictures": {
        "en": "Let us use the pictures. Tap the answer that is right for you.",
        "ur": "آئیے تصویروں سے جواب دیں۔ جو جواب ٹھیک ہو، اس کی تصویر دبائیں۔",
    },
}

# The frontend's existing strings (keep identical to shared/i18n/en.ts and ur.ts).
_EXISTING: Final[dict[str, dict[str, str]]] = {
    **{f"digit_{i}": {"en": en, "ur": ur} for i, (en, ur) in enumerate(zip(
        ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
        ("صفر", "ایک", "دو", "تین", "چار", "پانچ", "چھ", "سات", "آٹھ", "نو"), strict=True))},
    **{f"count_{i}": {"en": en, "ur": ur} for i, en, ur in zip(
        range(10, 21),
        ("ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"),
        ("دس", "گیارہ", "بارہ", "تیرہ", "چودہ", "پندرہ", "سولہ", "سترہ", "اٹھارہ", "انیس", "بیس"), strict=True)},
    "answer_yes": {"en": "Yes", "ur": "ہاں"},
    "answer_no": {"en": "No", "ur": "نہیں"},
    "answer_unknown": {"en": "I do not know", "ur": "مجھے نہیں معلوم"},
    "income_under_15k": {"en": "Less than 15,000 rupees", "ur": "15,000 روپے سے کم"},
    "income_15k_30k": {"en": "15,000 to 30,000 rupees", "ur": "15,000 سے 30,000 روپے"},
    "income_30k_50k": {"en": "30,000 to 50,000 rupees", "ur": "30,000 سے 50,000 روپے"},
    "income_over_50k": {"en": "More than 50,000 rupees", "ur": "50,000 روپے سے زیادہ"},
}  # fmt: skip

TEXT: Final[dict[str, dict[str, str]]] = {**_EXISTING, **VOICE_KEYS}


class SpeechClip(BaseModel):
    """One clip, the same shape as the frontend's `SpeechItem`: a recording key and its words."""

    key: str
    text: str


class Spoken(BaseModel):
    """A sentence to show and to play. `audio` is the clip sequence; `audio_keys` the same keys alone."""

    text: str
    lang: str
    audio: list[SpeechClip]
    audio_keys: list[str]

    @classmethod
    def of(cls, clips: list[SpeechClip], text: str, lang: str) -> Spoken:
        return cls(text=text, lang=lang, audio=clips, audio_keys=[c.key for c in clips])


def _lang(lang: str) -> str:
    return "en" if lang == "en" else "ur"


def _clip(key: str, lang: str) -> SpeechClip:
    return SpeechClip(key=key, text=TEXT[key][_lang(lang)])


def number_key(n: int) -> str | None:
    if 0 <= n <= 9:
        return f"digit_{n}"
    if 10 <= n <= 20:
        return f"count_{n}"
    return None


def _join(clips: list[SpeechClip], lang: str) -> str:
    """'You said: five people. Is that right?' / 'آپ نے کہا: پانچ لوگ۔ کیا یہ ٹھیک ہے؟'"""
    head, *middle, tail = [c.text for c in clips]
    stop = "." if _lang(lang) == "en" else "۔"
    return f"{head}: {' '.join(middle)}{stop} {tail}"


def readback(expected: str, choice: str, lang: str) -> Spoken | None:
    """The sentence that confirms an answer, or None when there is nothing to read back."""
    lang = _lang(lang)
    answer: list[SpeechClip]
    if choice == "unknown":
        answer = [_clip("answer_unknown", lang)]
    elif expected == "number":
        n = int(choice)
        key = number_key(n)
        if key is None:
            return None
        answer = [_clip(key, lang), _clip("voice_person" if n == 1 else "voice_people", lang)]
    elif expected == "income_band":
        answer = [_clip(f"income_{choice}", lang)]
    else:
        answer = [_clip("answer_yes" if choice == "yes" else "answer_no", lang)]
    clips = [_clip("voice_you_said", lang), *answer, _clip("voice_is_that_right", lang)]
    return Spoken.of(clips, _join(clips, lang), lang)


_ONE_ANSWER = frozenset({"two_different_numbers", "mixed_answers", "sum_of_numbers", "counted_in_parts", "range_spans_bands",
                         "contradicts_statement", "unknown_with_number", "alternatives_disagree"})  # fmt: skip
_MONTHLY = frozenset({"income_not_monthly", "income_unit_missing", "approximate_near_boundary", "unclear_bound"})
MAX_SPOKEN_TRIES: Final = 3


def ask_again(reasons: list[str], lang: str, attempt: int) -> tuple[Spoken, str]:
    """What to say after an abstention, and the fallback the screen should offer ('say_again' or 'use_pictures')."""
    lang = _lang(lang)
    if attempt >= MAX_SPOKEN_TRIES or "number_out_of_range" in reasons:
        key, fallback = "voice_use_pictures", "use_pictures"
    elif _ONE_ANSWER & set(reasons):
        key, fallback = "voice_one_answer", "say_again"
    elif _MONTHLY & set(reasons):
        key, fallback = "voice_monthly", "say_again"
    else:
        key, fallback = "voice_say_again", "say_again"
    clip = _clip(key, lang)
    return Spoken.of([clip], clip.text, lang), fallback
