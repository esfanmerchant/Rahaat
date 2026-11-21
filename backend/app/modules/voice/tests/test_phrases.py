"""Read-back sentences use the frontend's own words, so the text shown and the recording played agree."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.voice import phrases
from app.modules.voice.stt import duration_seconds, sniff

I18N = Path(__file__).resolve().parents[5] / "frontend" / "src" / "shared" / "i18n"


def _strings(lang: str) -> dict[str, str]:
    text = (I18N / f"{lang}.ts").read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in re.finditer(r"^\s{2}(\w+): '([^']*)',", text, flags=re.M)}


@pytest.mark.skipif(not I18N.is_dir(), reason="frontend sources not present")
@pytest.mark.parametrize("lang", ["en", "ur"])
def test_existing_keys_match_the_frontend(lang: str) -> None:
    frontend = _strings(lang)
    for key, by_lang in phrases._EXISTING.items():
        assert frontend.get(key) == by_lang[lang], key


def test_readbacks() -> None:
    five = phrases.readback("number", "5", "en")
    assert five is not None and five.text == "You said: five people. Is that right?"
    one = phrases.readback("number", "1", "ur")
    assert one is not None and one.audio_keys == ["voice_you_said", "digit_1", "voice_person", "voice_is_that_right"]
    twelve = phrases.readback("number", "12", "ur")
    assert twelve is not None and "count_12" in twelve.audio_keys
    band = phrases.readback("income_band", "15k_30k", "ur")
    assert band is not None and band.text == "آپ نے کہا: 15,000 سے 30,000 روپے۔ کیا یہ ٹھیک ہے؟"
    yes = phrases.readback("yes_no", "yes", "ur")
    assert yes is not None and yes.audio_keys == ["voice_you_said", "answer_yes", "voice_is_that_right"]
    assert phrases.readback("number", "25", "ur") is None  # no recording for 25; the interpreter never gives it anyway


def test_every_clip_has_both_languages() -> None:
    for key, by_lang in phrases.TEXT.items():
        assert by_lang.get("en") and by_lang.get("ur"), key
        assert len(re.split(r"[.!?۔؟]\s", by_lang["en"])) <= 3, key


def test_ask_again_choice() -> None:
    assert phrases.ask_again(["two_different_numbers"], "en", 1)[0].audio_keys == ["voice_one_answer"]
    assert phrases.ask_again(["income_not_monthly"], "ur", 1)[0].audio_keys == ["voice_monthly"]
    assert phrases.ask_again(["low_confidence"], "ur", 3) == (phrases.ask_again(["anything"], "ur", 5)[0], "use_pictures")
    assert phrases.ask_again(["number_out_of_range"], "ur", 1)[1] == "use_pictures"


def test_audio_sniffing_and_duration() -> None:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000 * 2)
    data = buf.getvalue()
    assert sniff(data) == "audio/wav" and duration_seconds(data, "audio/wav") == pytest.approx(2.0)
    assert sniff(b"OggS" + b"\0" * 60) == "audio/ogg"
    assert sniff(b"\x1a\x45\xdf\xa3" + b"\0" * 10) == "audio/webm"
    assert sniff(b"\0\0\0\x18ftypM4A ") == "audio/mp4"
    assert sniff(b"<html>") is None
