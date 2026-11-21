"""Voice endpoints' work: interpret, transcribe, audit. The interpreter itself is pure (interpret.py).

Model output never acts on its own: an interpreted answer is returned for read-back, and only the person's
own confirmation makes the app save it (`PATCH` with provenance `spoken`, never `verified`). Every answer is
audited with the transcript redacted; every non-allow guard verdict gets its own `guardrail.verdict` row.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.decision import TypedDecision
from app.core import audit
from app.core.errors import AppError, NotFound, TooManyRequests, Unprocessable
from app.db import models
from app.modules.guardrails import service as guard_service
from app.modules.guardrails.limits import SlidingWindow
from app.modules.people.context import PersonContext
from app.modules.voice import phrases, stt
from app.modules.voice.interpret import EXPECTED_FOR, FORM_FIELD_FOR, INTERPRETER_VERSION, interpret
from app.modules.voice.schemas import FormValueOut, SttOut, VoiceInterpretIn, VoiceInterpretOut

# Per person: generous for a person answering questions, tight enough to stop a script.
_interpret_limit = SlidingWindow(limit=60, window_s=60)
_stt_limit = SlidingWindow(limit=12, window_s=60)


class UseDeviceSpeech(AppError):
    status, code, title = 501, "use_device_speech", "Speech recognition is not available on the server"


class SpeechUnavailable(AppError):
    status, code, title = 503, "speech_unavailable", "Speech recognition is not answering. Use the phone or tap a picture."


class AudioTooLarge(AppError):
    status, code, title = 413, "audio_too_large", "That recording is too large"


class UnsupportedAudio(AppError):
    status, code, title = 415, "unsupported_audio", "This kind of recording is not supported"


def _limit(limiter: SlidingWindow, key: str) -> None:
    wait = limiter.hit(key)
    if wait is not None:
        raise TooManyRequests("Too many tries in a short time. Wait a moment.", headers={"Retry-After": str(int(wait) + 1)})


def resolve_lang(explicit: str | None, accept_language: str | None) -> str:
    if explicit in ("ur", "en"):
        return explicit
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in ("ur", "en"):
            return code
    return "ur"


def _check_application(db: Session, ctx: PersonContext, application_id: UUID | None) -> None:
    if application_id is None:
        return
    row = db.get(models.Application, application_id)  # RLS: only the person's own (or delegated) applications are visible
    if row is None or row.person_id != ctx.person_id:
        raise NotFound("That application was not found.", code="application_not_found")


def interpret_answer(db: Session, ctx: PersonContext, body: VoiceInterpretIn, *, lang: str) -> VoiceInterpretOut:
    if EXPECTED_FOR[body.question_key] != body.expected:
        raise Unprocessable(
            f"The question {body.question_key} expects {EXPECTED_FOR[body.question_key]}, not {body.expected}.",
            code="expected_type_mismatch",
        )
    _limit(_interpret_limit, str(ctx.person_id))
    _check_application(db, ctx, body.application_id)
    result = interpret(body.question_key, body.transcript, expected=body.expected, stt_confidence=body.stt_confidence,
                       expected_name=body.expected_name, alternatives=tuple(body.alternatives))  # fmt: skip
    decision = TypedDecision[str](
        choice=result.choice, probabilities=result.probabilities, confidence=result.confidence, route=result.route,
        reasons=result.reasons, model_version=INTERPRETER_VERSION, abstained=result.abstained,
    )  # fmt: skip
    field = FORM_FIELD_FOR[body.question_key]
    form_patch = None
    readback = ask_again = None
    fallback = "none"
    if not result.abstained and result.choice is not None:
        if field is not None:
            form_patch = {field: FormValueOut(value=result.value, confidence=result.confidence if result.value is not None else 0.0)}
        if body.question_key != "confirm":
            readback = phrases.readback(body.expected, result.choice, lang)
    else:
        ask_again, fallback = phrases.ask_again(result.reasons, lang, body.attempt)

    _audit(db, ctx, body, result.redacted_transcript, decision, lang)
    if result.guard_verdict is not None:
        guard_service.record(db, result.guard_verdict, tenant_id=ctx.tenant_id, **ctx.audit_fields(),
                             object_type="voice_answer", object_id=body.application_id or ctx.person_id,
                             context={"question_key": body.question_key})  # fmt: skip
    db.commit()
    return VoiceInterpretOut(
        decision=decision, question_key=body.question_key, expected=body.expected, field=field,
        value=None if result.abstained else result.value, unknown=result.unknown, form_patch=form_patch,
        needs_confirmation=not result.abstained and body.question_key != "confirm", readback=readback, ask_again=ask_again,
        fallback=fallback,
    )  # fmt: skip


def _audit(db: Session, ctx: PersonContext, body: VoiceInterpretIn, redacted: str, decision: TypedDecision[str], lang: str) -> None:
    details: dict[str, Any] = {
        "question_key": body.question_key, "expected": body.expected, "transcript_redacted": redacted[:400],
        "alternatives": len(body.alternatives), "engine": body.engine, "stt_confidence": body.stt_confidence,
        "choice": decision.choice, "confidence": decision.confidence, "abstained": decision.abstained,
        "route": decision.route, "attempt": body.attempt, "lang": lang, "provenance": "spoken",
    }  # fmt: skip
    audit.write(
        db, tenant_id=ctx.tenant_id, action="voice.interpreted", actor_type="user", **ctx.audit_fields(),
        object_type="application" if body.application_id else "person", object_id=body.application_id or ctx.person_id,
        result="abstained" if decision.abstained else "ok", reason=",".join(decision.reasons)[:200],
        input_hash=hashlib.sha256(body.transcript.encode("utf-8")).hexdigest(), model_version=INTERPRETER_VERSION, details=details,
    )  # fmt: skip


def transcribe_audio(db: Session, ctx: PersonContext, audio: bytes, *, lang: str) -> SttOut:
    """Check, transcribe, forget. Raises the problem the app needs to fall back gracefully."""
    _limit(_stt_limit, str(ctx.person_id))
    size = len(audio)
    outcome = "ok"
    provider = None
    try:
        mime, seconds = stt.check_audio(audio)
        result = stt.transcribe(audio, mime, lang)
        provider = result.provider
        return SttOut(transcript=result.text, confidence=result.confidence, lang=result.lang, provider=result.provider,
                      duration_s=result.duration_s if result.duration_s is not None else seconds)  # fmt: skip
    except stt.AudioRejected as exc:
        outcome = exc.code
        if exc.code == "unsupported_audio":
            raise UnsupportedAudio(exc.detail) from None
        if exc.code == "empty_audio":
            raise Unprocessable(exc.detail, code="empty_audio") from None
        raise AudioTooLarge(exc.detail, code=exc.code) from None
    except stt.NoProvider:
        outcome = "use_device_speech"
        raise UseDeviceSpeech("Use the phone's own speech recognition, or tap a picture.") from None
    except stt.ProviderFailed:
        outcome = "provider_failed"
        raise SpeechUnavailable() from None
    finally:
        # The audio is never kept: it lives in this request's memory only, and the audit row holds its size alone.
        audit.write(db, tenant_id=ctx.tenant_id, action="voice.transcribed", actor_type="user", **ctx.audit_fields(),
                    object_type="person", object_id=ctx.person_id, result="ok" if outcome == "ok" else "failed",
                    reason=None if outcome == "ok" else outcome,
                    details={"bytes": size, "lang": lang, "provider": provider, "audio_stored": False})  # fmt: skip
        db.commit()


def providers() -> dict[str, str]:
    """For /v1/system/health."""
    return {**stt.providers(), "voice_interpreter": INTERPRETER_VERSION}
