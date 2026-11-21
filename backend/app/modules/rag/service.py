"""The rules assistant's work: load the tenant's approved corpus, answer, verify citations, audit.

Anonymous questions are allowed with strict limits (per address and in total); they read one department's
approved policy text through a narrow system session and append one audit row to that department's chain.
Signed-in callers use their own department through their own RLS session.
"""

from __future__ import annotations

import hashlib
import importlib.util
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.decision import TypedDecision
from app.core import audit
from app.core.config import get_settings
from app.core.db import session_scope, system_session
from app.core.deps import Principal
from app.core.errors import NotFound, TooManyRequests
from app.db import models
from app.modules.guardrails import pii
from app.modules.guardrails import service as guard_service
from app.modules.guardrails.limits import SlidingWindow
from app.modules.guardrails.output_guard import CitedSentence, KnownChunk, check_answer
from app.modules.rag import calibration
from app.modules.rag.answer import ANSWER_VERSION, MESSAGES, THRESHOLD, Answer, compose
from app.modules.rag.corpus import split_sentences
from app.modules.rag.index import LexicalIndex, Passage
from app.modules.rag.schemas import AnswerSentenceOut, AskIn, AskOut, Citation, KbDocumentOut, KbSectionOut, SpokenText

# Anonymous: a person asking a few questions is fine; a script is not.
_anon_per_ip = SlidingWindow(limit=6, window_s=60)
_anon_per_ip_hour = SlidingWindow(limit=40, window_s=3600)
_anon_total = SlidingWindow(limit=120, window_s=60)
_per_user = SlidingWindow(limit=30, window_s=60)

_cache: dict[UUID, tuple[str, dict[str, LexicalIndex]]] = {}


def reset_limits() -> None:
    for limiter in (_anon_per_ip, _anon_per_ip_hour, _anon_total, _per_user):
        limiter.reset()


def _limit(principal: Principal | None, client_ip: str) -> None:
    checks = [(_per_user, str(principal.user_id))] if principal else [
        (_anon_per_ip, client_ip or "unknown"), (_anon_per_ip_hour, client_ip or "unknown"), (_anon_total, "all")]  # fmt: skip
    for limiter, key in checks:
        wait = limiter.hit(key)
        if wait is not None:
            raise TooManyRequests("Too many questions in a short time. Wait a little, or sign in.",
                                  headers={"Retry-After": str(int(wait) + 1)})  # fmt: skip


def lang_from_header(accept_language: str | None) -> str | None:
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in ("ur", "en"):
            return code
    return None


def _rows(db: Session, tenant_id: UUID) -> list[Any]:
    return list(db.execute(
        select(models.KbChunk.id, models.KbChunk.document_id, models.KbChunk.section, models.KbChunk.text, models.KbChunk.meta,
               models.KbDocument.title, models.KbDocument.version_no, models.KbDocument.lang, models.KbDocument.status,
               models.KbDocument.content_hash, models.KbDocument.source)
        .join(models.KbDocument, models.KbDocument.id == models.KbChunk.document_id)
        .where(models.KbChunk.tenant_id == tenant_id, models.KbDocument.tenant_id == tenant_id, models.KbDocument.status == "approved")
        .order_by(models.KbDocument.source, models.KbChunk.ordinal)
    ).all())  # fmt: skip


def _passage(row: Any) -> Passage:
    meta = row.meta or {}
    sentences = tuple(meta.get("sentences") or split_sentences(row.text))
    return Passage(chunk_id=str(row.id), document_id=str(row.document_id), doc_key=str(meta.get("doc_key") or row.source),
                   title=row.title, version=row.version_no, section_id=str(meta.get("section_id") or row.section),
                   heading=str(meta.get("heading") or row.section), lang=row.lang, sentences=sentences, status=row.status)  # fmt: skip


def indexes_for(db: Session, tenant_id: UUID) -> dict[str, LexicalIndex]:
    """Built from the database, cached per department until a document version changes."""
    rows = _rows(db, tenant_id)
    signature = hashlib.sha256("|".join(f"{r.id}:{r.content_hash}" for r in rows).encode()).hexdigest()
    cached = _cache.get(tenant_id)
    if cached and cached[0] == signature:
        return cached[1]
    passages = [_passage(r) for r in rows]
    indexes = {lang: LexicalIndex.build([p for p in passages if p.lang == lang]) for lang in ("en", "ur")}
    _cache[tenant_id] = (signature, indexes)
    return indexes


def _public_tenant(db: Session, slug: str | None) -> UUID:
    query = select(models.Tenant.id).where(models.Tenant.kind == "department", models.Tenant.status == "active")
    if slug:
        found = db.scalar(query.where(models.Tenant.slug == slug))
        if found is None:
            raise NotFound("That department was not found.", code="department_not_found")
        return found
    first = db.scalar(query.order_by(models.Tenant.created_at, models.Tenant.slug).limit(1))
    if first is None:
        raise NotFound("No department publishes rules here yet.", code="department_not_found")
    return first


def _verify_citations(db: Session, tenant_id: UUID, result: Answer) -> None:
    """Every cited chunk must exist now, be approved, and still hold the sentence. Otherwise the answer is refused."""
    ids = [UUID(p.chunk_id) for p in result.passages]
    rows = {str(r.id): r for r in db.execute(
        select(models.KbChunk.id, models.KbChunk.document_id, models.KbChunk.text, models.KbDocument.version_no, models.KbDocument.status)
        .join(models.KbDocument, models.KbDocument.id == models.KbChunk.document_id)
        .where(models.KbChunk.id.in_(ids), models.KbChunk.tenant_id == tenant_id)
    ).all()} if ids else {}  # fmt: skip
    known = {cid: KnownChunk(cid, str(r.document_id), r.version_no, r.text, r.status) for cid, r in rows.items()}
    verdict = check_answer([CitedSentence(s.text, s.passage.chunk_id, s.passage.document_id, s.passage.version) for s in result.sentences],
                           known)  # fmt: skip
    if verdict.blocked:
        result.answered, result.reason, result.sentences, result.message_key = False, "output_blocked", [], "ask_not_sure"
    result.output_verdict = verdict


def _spoken(key: str | None, lang: str) -> SpokenText | None:
    if key is None:
        return None
    return SpokenText(key=key, text=MESSAGES[key]["en" if lang == "en" else "ur"], lang=lang)


def _respond(db: Session, tenant_id: UUID, body: AskIn, requested_lang: str | None, principal: Principal | None) -> AskOut:
    result = compose(indexes_for(db, tenant_id), body.question, requested_lang)
    if result.answered:
        _verify_citations(db, tenant_id, result)
    passages = result.passages
    citations = [Citation(chunk_id=UUID(p.chunk_id), document_id=UUID(p.document_id), doc_key=p.doc_key, title=p.title, version=p.version,
                          section_id=p.section_id, section=p.heading, lang=p.lang) for p in passages]  # fmt: skip
    position = {p.chunk_id: i for i, p in enumerate(passages)}
    sentences = [AnswerSentenceOut(text=s.text, citation=position[s.passage.chunk_id]) for s in result.sentences]
    p_right = calibration.probability(result.top_score)
    guard_codes = [c for v in (result.input_verdict, result.output_verdict) if v is not None for c in v.codes]
    decision = TypedDecision[str](
        choice="answer" if result.answered else None, probabilities={"answer": p_right, "refuse": round(1 - p_right, 4)},
        confidence=p_right, route="auto" if result.answered else "human",
        reasons=[result.reason, *(["no_promise_notice"] if result.answered and result.message_key else []), *guard_codes],
        model_version=f"{ANSWER_VERSION}@{THRESHOLD}", abstained=not result.answered,
    )  # fmt: skip
    _audit(db, tenant_id, body, result, principal, [str(c.chunk_id) for c in citations])
    return AskOut(
        decision=decision, answered=result.answered, lang=result.lang, sentences=sentences, citations=citations,
        notice=_spoken(result.message_key, result.lang) if result.answered else None,
        refusal=None if result.answered else _spoken(result.message_key or "ask_not_sure", result.lang),
        reason=result.reason, retrieval={"top_score": result.top_score, "threshold": THRESHOLD},
    )  # fmt: skip


def _audit(db: Session, tenant_id: UUID, body: AskIn, result: Answer, principal: Principal | None, chunk_ids: list[str]) -> None:
    actor: dict[str, Any] = (
        {"actor_type": "user", "actor_id": principal.user_id, "actor_role": principal.role} if principal else {"actor_type": "anonymous"}
    )
    verdicts = [v for v in (result.input_verdict, result.output_verdict) if v is not None]
    audit.write(
        db, tenant_id=tenant_id, action="rag.asked", **actor, object_type="kb", object_id=chunk_ids[0] if chunk_ids else None,
        result="ok" if result.answered else "refused", reason=result.reason,
        input_hash=hashlib.sha256(body.question.encode("utf-8")).hexdigest(), model_version=f"{ANSWER_VERSION}@{THRESHOLD}",
        details={"question_redacted": pii.redact_for_storage(body.question, limit=300), "lang": result.lang, "citations": chunk_ids,
                 "top_score": result.top_score, "threshold": THRESHOLD, "personal": result.personal,
                 "guards": [v.summary() for v in verdicts], "anonymous": principal is None},
    )  # fmt: skip
    for verdict in verdicts:
        guard_service.record(db, verdict, tenant_id=tenant_id, **actor, object_type="kb_question", context={"reason": result.reason})


def ask(body: AskIn, *, principal: Principal | None, accept_language: str | None, client_ip: str) -> AskOut:
    _limit(principal, client_ip)
    requested = body.lang or lang_from_header(accept_language)
    if principal is None:
        with system_session() as db:  # narrow: one department's approved policy text, and one audit row in its chain
            return _respond(db, _public_tenant(db, body.tenant_slug), body, requested, None)
    with session_scope(principal.rls()) as db:  # a signed-in caller always uses their own department
        return _respond(db, principal.tenant_id, body, requested, principal)


def list_documents(db: Session, tenant_id: UUID) -> list[KbDocumentOut]:
    docs = db.scalars(select(models.KbDocument).where(models.KbDocument.tenant_id == tenant_id)
                      .order_by(models.KbDocument.source, models.KbDocument.version_no)).all()  # fmt: skip
    chunks = db.scalars(select(models.KbChunk).where(models.KbChunk.tenant_id == tenant_id).order_by(models.KbChunk.ordinal)).all()
    by_doc: dict[UUID, list[models.KbChunk]] = {}
    for chunk in chunks:
        by_doc.setdefault(chunk.document_id, []).append(chunk)
    out = []
    for doc in docs:
        sections = [KbSectionOut(chunk_id=c.id, section_id=str((c.meta or {}).get("section_id") or c.section), section=c.section or "",
                                 sentences=len((c.meta or {}).get("sentences") or [])) for c in by_doc.get(doc.id, [])]  # fmt: skip
        doc_key = (doc.source or "").split(":")[1] if (doc.source or "").count(":") >= 2 else (doc.source or "")
        out.append(KbDocumentOut(id=doc.id, doc_key=doc_key, title=doc.title, lang=doc.lang, version=doc.version_no, status=doc.status,
                                 content_hash=doc.content_hash, sections=sections))  # fmt: skip
    return out


def providers() -> dict[str, str]:
    """For /v1/system/health."""
    if importlib.util.find_spec("fastembed") is None:
        embeddings = "not_installed"
    else:
        embeddings = "available_not_wired" if get_settings().ai_profile == "full" else "disabled_ai_profile_lite"
    return {"retrieval_lexical": "char_tfidf_bm25", "retrieval_embeddings": embeddings, "rag_answers": "extractive_with_citations"}
