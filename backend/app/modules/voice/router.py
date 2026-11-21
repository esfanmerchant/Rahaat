"""Voice answers: interpret a spoken answer, and (optionally) transcribe a short recording on the server."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.deps import get_db
from app.modules.people.context import PersonContext, acting_person
from app.modules.voice import service
from app.modules.voice.schemas import SttOut, VoiceInterpretIn, VoiceInterpretOut
from app.modules.voice.stt import voice_settings

router = APIRouter(prefix="/v1/voice", tags=["voice"])

_interpret = acting_person("voice:interpret", "apply", description="Turn a spoken answer into a typed form value, read back before saving")
_transcribe = acting_person("voice:transcribe", "apply", description="Transcribe a short spoken answer; the audio is never stored")

_AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/flac", "audio/amr")


@router.post("/interpret", response_model=VoiceInterpretOut, summary="Interpret a spoken answer against the type the question expects",
             responses={422: {"description": "invalid_input or expected_type_mismatch"}, 404: {"description": "application_not_found"},
                        429: {"description": "too_many_requests"}})  # fmt: skip
def interpret_answer(
    body: VoiceInterpretIn,
    ctx: PersonContext = Depends(_interpret),
    db: Session = Depends(get_db),
    accept_language: str | None = Header(default=None),
) -> VoiceInterpretOut:
    """Returns a TypedDecision. Below the confidence floor it abstains (route `ask_more`) and says what to ask.

    An answer is never saved here. Read `readback` to the person; when they confirm, send `form_patch` in
    `PATCH /v1/applications/{id}`.
    """
    return service.interpret_answer(db, ctx, body, lang=service.resolve_lang(body.lang, accept_language))


@router.post(
    "/stt", response_model=SttOut, summary="Transcribe a short recording (optional; the app uses the phone's recogniser first)",
    responses={413: {"description": "audio_too_large or audio_too_long"}, 415: {"description": "unsupported_audio"},
               422: {"description": "empty_audio"}, 429: {"description": "too_many_requests"},
               501: {"description": "use_device_speech: no server provider is configured"},
               503: {"description": "speech_unavailable: the provider did not answer"}},
    openapi_extra={"requestBody": {"required": True, "description": "The raw recording, at most 1 MB and 30 seconds",
                                   "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in _AUDIO_TYPES}}},
)  # fmt: skip
async def transcribe(
    request: Request,
    ctx: PersonContext = Depends(_transcribe),
    db: Session = Depends(get_db),
    lang: Literal["ur", "en"] = Query(default="ur"),
) -> SttOut:
    limit = voice_settings().voice_max_audio_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise service.AudioTooLarge(f"Send at most {limit // 1000} KB of audio.")
    chunks: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise service.AudioTooLarge(f"Send at most {limit // 1000} KB of audio.")
        chunks.append(chunk)
    audio = b"".join(chunks)
    chunks.clear()
    return await run_in_threadpool(service.transcribe_audio, db, ctx, audio, lang=lang)
