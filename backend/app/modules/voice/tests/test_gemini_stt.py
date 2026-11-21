"""Gemini speech-to-text through httpx.MockTransport only: no network, no real key."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.modules.voice import stt
from app.modules.voice.interpret import interpret

KEY = "gemini-test-key-not-real"
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 40


def _gemini_body(transcript: str, audible: bool = True, language: str = "ur") -> dict[str, Any]:
    inner = json.dumps({"transcript": transcript, "language": language, "audible": audible}, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": inner}]}}]}


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt.voice_settings(), "gemini_api_key", KEY)
    monkeypatch.setattr(stt.voice_settings(), "groq_api_key", None)
    monkeypatch.setattr(stt, "_local_whisper_available", lambda: False)


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_success_sends_key_only_in_header_and_returns_no_confidence() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, json.loads(request.content)
        return httpx.Response(200, json=_gemini_body("ہم پانچ لوگ ہیں"))

    result = stt.transcribe(WAV, "audio/wav", "ur", client=_client(handler))
    assert result.text == "ہم پانچ لوگ ہیں" and result.provider == "gemini" and result.confidence is None
    assert seen["headers"]["x-goog-api-key"] == KEY and KEY not in seen["url"] and KEY not in json.dumps(seen["body"])
    assert ":generateContent" in seen["url"] and seen["url"].startswith("https://generativelanguage.googleapis.com/v1beta/models/")
    cfg = seen["body"]["generationConfig"]
    assert cfg["temperature"] == 0 and cfg["responseMimeType"] == "application/json"
    assert set(cfg["responseSchema"]["properties"]) == {"transcript", "language", "audible"}
    assert seen["body"]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "audio/wav"


def test_not_audible_gives_empty_text_and_the_say_it_again_outcome() -> None:
    result = stt.transcribe(WAV, "audio/wav", "ur", client=_client(lambda r: httpx.Response(200, json=_gemini_body("something", audible=False))))
    assert result.text == "" and result.provider == "gemini"
    assert interpret("household_size", result.text, stt_confidence=result.confidence).reasons == ["empty_transcript"]


def test_missing_confidence_always_goes_to_read_back() -> None:
    result = interpret("household_size", "paanch", stt_confidence=None)
    assert result.choice is not None and "read_back_required" in result.reasons and "speech_confidence_missing" in result.reasons


@pytest.mark.parametrize("failure", ["429", "500", "timeout", "badjson", "wrongshape"])
def test_failure_falls_through_to_groq(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.setattr(stt.voice_settings(), "groq_api_key", "groq-test-key")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "api.groq.com":
            return httpx.Response(200, json={"text": "paanch", "language": "ur", "duration": 1.0, "segments": []})
        if failure == "timeout":
            raise httpx.ReadTimeout("slow")
        if failure == "badjson":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json {"}]}}]})
        if failure == "wrongshape":
            return httpx.Response(200, json={"candidates": []})
        return httpx.Response(int(failure))

    result = stt.transcribe(WAV, "audio/wav", "ur", client=_client(handler))
    assert result.provider == "groq_whisper" and calls == ["generativelanguage.googleapis.com", "api.groq.com"]


def test_all_failing_raises_provider_failed() -> None:
    with pytest.raises(stt.ProviderFailed):
        stt.transcribe(WAV, "audio/wav", "ur", client=_client(lambda r: httpx.Response(503)))


def test_failure_log_has_provider_and_error_class_only(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"), pytest.raises(stt.ProviderFailed):
        stt.transcribe(WAV, "audio/wav", "ur", client=_client(lambda r: httpx.Response(429)))
    text = " ".join(caplog.messages)
    assert "gemini" in text and "ProviderFailed" in text and KEY not in text


def test_no_key_means_chain_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stt.voice_settings(), "gemini_api_key", None)
    with pytest.raises(stt.NoProvider):
        stt.transcribe(WAV, "audio/wav", "ur")
    assert stt.providers()["stt_gemini"] == "no_key" and stt.providers()["stt_server"] == "none_use_device_speech"


def test_health_reports_gemini() -> None:
    report = stt.providers()
    assert report["stt_gemini"] == "configured" and report["stt_server"] == "available"
