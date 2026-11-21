"""Server speech-to-text, optional. The citizen app uses the phone's own recogniser first and sends text.

Provider chain, first available wins:
1. Groq Whisper (`whisper-large-v3`) when `GROQ_API_KEY` is set. Hosted: the audio leaves the server.
2. Local faster-whisper, only with `AI_PROFILE=full` and the library installed (it is not in the image).
3. None: the endpoint answers 501 `use_device_speech`, and the app keeps using the phone and the pictures.

The audio is held in memory only, never written to disk or logs, and dropped after the call. Uploads are
capped by size; WAV and Ogg durations are read from the header before anything is sent, and any provider's
reported duration is checked again afterwards.
"""

from __future__ import annotations

import importlib.util
import io
import math
import struct
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("rahat.voice.stt")

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class VoiceSettings(BaseSettings):
    """Voice settings live here so the platform settings stay unchanged; same `.env` files."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    groq_api_key: str | None = None
    groq_stt_model: str = "whisper-large-v3"
    voice_max_audio_bytes: int = 1_000_000
    voice_max_audio_seconds: float = 30.0
    voice_local_whisper_model: str = "small"
    voice_stt_timeout_s: float = 20.0


@lru_cache(maxsize=1)
def voice_settings() -> VoiceSettings:
    return VoiceSettings()


@dataclass(frozen=True, slots=True)
class SttResult:
    text: str
    confidence: float | None
    lang: str
    provider: str
    duration_s: float | None


class NoProvider(Exception):
    """No speech-to-text provider is configured on this server."""


class ProviderFailed(Exception):
    """Every configured provider failed; the app falls back to the phone and the pictures."""


class AudioRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# --- the audio itself ----------------------------------------------------------------------------------

_MAGIC: tuple[tuple[str, int, bytes], ...] = (
    ("audio/wav", 0, b"RIFF"),
    ("audio/ogg", 0, b"OggS"),
    ("audio/webm", 0, b"\x1a\x45\xdf\xa3"),
    ("audio/flac", 0, b"fLaC"),
    ("audio/amr", 0, b"#!AMR"),
    ("audio/mpeg", 0, b"ID3"),
    ("audio/mp4", 4, b"ftyp"),
)
_EXTENSIONS = {"audio/wav": "wav", "audio/ogg": "ogg", "audio/webm": "webm", "audio/flac": "flac", "audio/amr": "amr",
               "audio/mpeg": "mp3", "audio/mp4": "m4a"}  # fmt: skip


def sniff(audio: bytes) -> str | None:
    """The real container type from the first bytes. The declared Content-Type is not trusted."""
    for mime, offset, magic in _MAGIC:
        if audio[offset : offset + len(magic)] == magic:
            if mime == "audio/wav" and audio[8:12] != b"WAVE":
                continue
            return mime
    if len(audio) > 2 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0:
        return "audio/mpeg"  # MPEG audio frame without an ID3 tag
    return None


def _wav_seconds(audio: bytes) -> float | None:
    pos, byte_rate, data_size = 12, None, None
    while pos + 8 <= len(audio):
        chunk, size = audio[pos : pos + 4], struct.unpack("<I", audio[pos + 4 : pos + 8])[0]
        if chunk == b"fmt " and pos + 20 <= len(audio):
            byte_rate = struct.unpack("<I", audio[pos + 16 : pos + 20])[0]
        elif chunk == b"data":
            data_size = size
            break
        pos += 8 + size + (size & 1)
    if not byte_rate or data_size is None:
        return None
    return float(data_size) / float(byte_rate)


def _ogg_seconds(audio: bytes) -> float | None:
    """Last page's granule position over the sample rate (48 kHz for Opus, from the header for Vorbis)."""
    rate: float | None = 48_000.0 if b"OpusHead" in audio[:200] else None
    vorbis = audio.find(b"\x01vorbis")
    if rate is None and vorbis >= 0 and vorbis + 16 <= len(audio):
        rate = float(struct.unpack("<I", audio[vorbis + 12 : vorbis + 16])[0]) or None
    last = audio.rfind(b"OggS")
    if rate is None or last < 0 or last + 14 > len(audio):
        return None
    granule = struct.unpack("<q", audio[last + 6 : last + 14])[0]
    return granule / rate if granule > 0 else None


def duration_seconds(audio: bytes, mime: str) -> float | None:
    """Exact for WAV and Ogg; None when the container does not say without decoding."""
    try:
        if mime == "audio/wav":
            return _wav_seconds(audio)
        if mime == "audio/ogg":
            return _ogg_seconds(audio)
    except (struct.error, ValueError):
        return None
    return None


def check_audio(audio: bytes) -> tuple[str, float | None]:
    """(mime, seconds) or AudioRejected. Size first, then type, then duration where it can be read."""
    settings = voice_settings()
    if not audio:
        raise AudioRejected("empty_audio", "The recording is empty.")
    if len(audio) > settings.voice_max_audio_bytes:
        raise AudioRejected("audio_too_large", f"Send at most {settings.voice_max_audio_bytes // 1000} KB of audio.")
    mime = sniff(audio)
    if mime is None:
        raise AudioRejected("unsupported_audio", "This is not an audio file we can read (WAV, Ogg, WebM, MP3, M4A, FLAC, AMR).")
    seconds = duration_seconds(audio, mime)
    if seconds is not None and seconds > settings.voice_max_audio_seconds:
        raise AudioRejected("audio_too_long", f"Keep the answer under {int(settings.voice_max_audio_seconds)} seconds.")
    return mime, seconds


# --- providers -----------------------------------------------------------------------------------------


def _local_whisper_available() -> bool:
    return get_settings().ai_profile == "full" and importlib.util.find_spec("faster_whisper") is not None


def providers() -> dict[str, str]:
    """For /v1/system/health: which speech providers are active right now."""
    settings = voice_settings()
    if importlib.util.find_spec("faster_whisper") is None:
        local = "not_installed"
    else:
        local = "available" if get_settings().ai_profile == "full" else "disabled_ai_profile_lite"
    return {
        "stt_device": "client",  # the phone's own recogniser; the server only interprets the text
        "stt_groq_whisper": "configured" if settings.groq_api_key else "no_key",
        "stt_local_whisper": local,
        "stt_server": "available" if (settings.groq_api_key or local == "available") else "none_use_device_speech",
    }


def _confidence_from_segments(segments: list[dict[str, Any]]) -> float | None:
    """Mean of exp(avg_logprob), discounted by the no-speech probability. A rough, uncalibrated signal."""
    values = []
    for seg in segments:
        logprob = seg.get("avg_logprob")
        if isinstance(logprob, int | float):
            no_speech = seg.get("no_speech_prob") or 0.0
            values.append(math.exp(min(0.0, float(logprob))) * (1.0 - float(no_speech)))
    return round(sum(values) / len(values), 4) if values else None


def _groq(audio: bytes, mime: str, lang: str, client: httpx.Client | None = None) -> SttResult:
    settings = voice_settings()
    files = {"file": (f"answer.{_EXTENSIONS.get(mime, 'bin')}", audio, mime)}  # a generic name: nothing about the person
    data = {"model": settings.groq_stt_model, "language": lang, "response_format": "verbose_json", "temperature": "0"}
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    own = client is None
    http = client or httpx.Client(timeout=settings.voice_stt_timeout_s)
    try:
        response = http.post(GROQ_URL, files=files, data=data, headers=headers)
    finally:
        if own:
            http.close()
    if response.status_code != 200:
        raise ProviderFailed(f"groq answered {response.status_code}")
    body = response.json()
    duration = body.get("duration")
    return SttResult(
        text=str(body.get("text") or "").strip(), confidence=_confidence_from_segments(body.get("segments") or []),
        lang=str(body.get("language") or lang), provider="groq_whisper",
        duration_s=float(duration) if isinstance(duration, int | float) else None,
    )  # fmt: skip


@lru_cache(maxsize=1)
def _local_model() -> Any:
    from faster_whisper import WhisperModel  # heavy and optional: imported only here

    return WhisperModel(voice_settings().voice_local_whisper_model, device="cpu", compute_type="int8")


def _local(audio: bytes, lang: str) -> SttResult:
    segments, info = _local_model().transcribe(io.BytesIO(audio), language=lang, beam_size=1, vad_filter=True)
    parts = list(segments)
    text = " ".join(s.text.strip() for s in parts).strip()
    conf = _confidence_from_segments([{"avg_logprob": s.avg_logprob, "no_speech_prob": s.no_speech_prob} for s in parts])
    return SttResult(text=text, confidence=conf, lang=lang, provider="local_whisper", duration_s=getattr(info, "duration", None))


def transcribe(audio: bytes, mime: str, lang: str, *, client: httpx.Client | None = None) -> SttResult:
    """Try each configured provider in order. Raises NoProvider or ProviderFailed; never returns a guess."""
    settings = voice_settings()
    chain: list[str] = []
    if settings.groq_api_key:
        chain.append("groq")
    if _local_whisper_available():
        chain.append("local")
    if not chain:
        raise NoProvider()
    for name in chain:
        try:
            result = _groq(audio, mime, lang, client) if name == "groq" else _local(audio, lang)
        except (httpx.HTTPError, ProviderFailed, ValueError, RuntimeError, OSError) as exc:
            log.warning("speech provider %s failed: %s", name, type(exc).__name__)
            continue
        if result.duration_s is not None and result.duration_s > settings.voice_max_audio_seconds:
            raise AudioRejected("audio_too_long", f"Keep the answer under {int(settings.voice_max_audio_seconds)} seconds.")
        return result
    raise ProviderFailed("every speech provider failed")
