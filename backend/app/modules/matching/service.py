"""Dedupe against the department's register (B8), and the officer's link and unlink.

    check_duplicates(db, tenant_id=..., person_id=..., application_id=None) -> DuplicateEvidence | None

Called by the submit pipeline in the applicant's own session. Steps:
1. The applicant's blocking keys: national ID and phone blind indexes, date of birth, phonetic name key.
2. Candidates: only people who share a key (blocking), read as the department's `worker` role so that
   a person who withdrew consent is not compared. Pending sign-ups and deleted records are ignored.
3. Each candidate is scored (compare.py); identifiers are decrypted in memory for the comparison only.
4. `same` (high score, agreeing identifier, nothing contradicting) is linked and logged; `possible` gets a
   `duplicate_review` case for a person to decide; `distinct` leaves no trace except the audit counts.
   An officer's earlier answer for a pair (linked, rejected, unlinked) is respected.
Two person rows are never merged into one: a link is a record that an officer can reverse.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.contracts.decision import HandoffPackage, Hypothesis, UncertainField
from app.contracts.engine import DuplicateEvidence
from app.core import audit
from app.core.crypto import decrypt_field
from app.core.db import RlsContext, session_scope
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.db import models
from app.modules.decision import paging
from app.modules.matching.compare import BAND_ORDER, Comparison, PersonRecord, blocking_keys, compare
from app.modules.matching.fixtures import build_fixtures, evaluate
from app.modules.matching.names import name_key

log = get_logger("rahat.matching")

IGNORED_STATUSES = ("pending", "deleted")
MAX_CANDIDATES = 500
DECIDED = ("linked", "rejected", "reversed")


def _decrypt(tenant: models.Tenant | None, token: str | None) -> str | None:
    if not token or tenant is None:
        return None
    try:
        return decrypt_field(tenant.wrapped_dek, token)
    except Exception:  # noqa: BLE001
        log.warning("could not decrypt an identifier for dedupe")
        return None


def person_record(person: models.Person, tenant: models.Tenant | None) -> PersonRecord:
    return PersonRecord(
        ref=str(person.id), names=tuple(n for n in (person.full_name, person.full_name_ur) if n), dob=person.dob.isoformat() if person.dob else None,
        gender=person.gender, district=person.district, national_id=_decrypt(tenant, person.national_id_enc),
        national_id_hash=person.national_id_hash, phone=None, phone_hash=person.phone_hash,
    )  # fmt: skip


def person_name_key(person: models.Person) -> str | None:
    return name_key(person.full_name) or name_key(person.full_name_ur)


def _candidates(tenant_id: uuid.UUID, me: models.Person, my_record: PersonRecord,
                tenant: models.Tenant | None) -> list[tuple[uuid.UUID, PersonRecord]]:  # fmt: skip
    """People sharing at least one blocking key with the applicant, read as the department's worker."""
    my_keys = blocking_keys(replace_hashes(my_record))
    conditions: list[Any] = []
    if me.national_id_hash:
        conditions.append(models.Person.national_id_hash == me.national_id_hash)
    if me.phone_hash:
        conditions.append(models.Person.phone_hash == me.phone_hash)
    if me.dob is not None:
        conditions.append(models.Person.dob == me.dob)
    key = person_name_key(me)
    if key:
        conditions.append(models.Person.name_key == key)
    conditions.append(models.Person.name_key.is_(None))  # not keyed yet: keyed here, then blocked like the rest
    out: list[tuple[uuid.UUID, PersonRecord]] = []
    with session_scope(RlsContext(role="worker", tenant_id=tenant_id)) as wdb:
        rows = wdb.scalars(
            select(models.Person).where(models.Person.tenant_id == tenant_id, models.Person.id != me.id,
                                        models.Person.status.not_in(IGNORED_STATUSES), or_(*conditions))
            .order_by(models.Person.created_at).limit(MAX_CANDIDATES)
        ).all()  # fmt: skip
        for person in rows:
            record = person_record(person, tenant)
            if blocking_keys(replace_hashes(record)) & my_keys:
                out.append((person.id, record))
    return out


def replace_hashes(record: PersonRecord) -> PersonRecord:
    """Blocking compares the national ID by its blind index, so a clear value and a hash give the same key."""
    return PersonRecord(ref=record.ref, names=record.names, dob=record.dob, national_id_hash=record.national_id_hash,
                        phone_hash=record.phone_hash)  # fmt: skip


def _pair(db: Session, tenant_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> models.DuplicateCandidate | None:
    return db.scalar(
        select(models.DuplicateCandidate).where(
            models.DuplicateCandidate.tenant_id == tenant_id,
            or_((models.DuplicateCandidate.person_a_id == a) & (models.DuplicateCandidate.person_b_id == b),
                (models.DuplicateCandidate.person_a_id == b) & (models.DuplicateCandidate.person_b_id == a)),
        ).order_by(models.DuplicateCandidate.created_at.desc()).limit(1)
    )  # fmt: skip


def _review_handoff(result: Comparison, candidate_id: uuid.UUID, other_id: uuid.UUID) -> HandoffPackage:
    agree = [k for k, v in result.fields.items() if v == "same"]
    differ = [k for k, v in result.fields.items() if v in ("different", "near")]
    return HandoffPackage(
        question="Are these two records the same person?",
        understanding=(f"Names match at {result.name.score:.2f}. Same: {', '.join(agree) or 'nothing else'}. "
                       f"Different or nearly the same: {', '.join(differ) or 'nothing'}. Match score {result.score:.2f}."),  # fmt: skip
        uncertain_fields=[UncertainField(field=k, value=None, confidence=0.0, why=f"identifier_{result.fields[k]}") for k in differ],
        rule_fired="possible_duplicate",
        hypotheses=[Hypothesis(label="same_person", probability=result.score),
                    Hypothesis(label="two_people", probability=round(1 - result.score, 4))],
        resolving_proof="rahat_id",
        suggested_question="Have you registered before, maybe with a different spelling of your name or another phone?",
        evidence={"duplicate_candidate_id": str(candidate_id), "other_person_id": str(other_id), "comparison": result.evidence()},
        guards=["possible_duplicate"],
    )  # fmt: skip


def _open_review(db: Session, tenant_id: uuid.UUID, person_id: uuid.UUID, application_id: uuid.UUID | None,
                 candidate: models.DuplicateCandidate, result: Comparison, other_id: uuid.UUID) -> None:  # fmt: skip
    from app.modules.cases.service import open_case

    if candidate.case_id is not None:
        existing = db.get(models.Case, candidate.case_id)
        if existing is not None and existing.status not in ("resolved", "closed"):
            return
    case = open_case(db, tenant_id=tenant_id, kind="duplicate_review", opened_reason="possible_duplicate", application_id=application_id,
                     person_id=person_id, handoff=_review_handoff(result, candidate.id, other_id), confidence=result.score, priority=30)  # fmt: skip
    candidate.case_id = case.id


def _record_pair(db: Session, tenant_id: uuid.UUID, me: uuid.UUID, other: uuid.UUID, result: Comparison,
                 application_id: uuid.UUID | None) -> str:  # fmt: skip
    """Store or refresh the pair; returns the band that counts for the decision."""
    existing = _pair(db, tenant_id, me, other)
    now = datetime.now(UTC)
    if existing is not None and existing.status in ("rejected", "reversed"):
        return "distinct"  # an officer decided these are two people
    if existing is not None and existing.status == "linked":
        return "same"
    evidence = result.evidence()
    if existing is not None:
        existing.score, existing.band, existing.evidence = result.score, result.band, evidence
        if result.band == "possible":
            _open_review(db, tenant_id, me, application_id, existing, result, other)
        elif result.band == "same":
            existing.status, existing.resolved_at = "linked", now
            audit.write(db, tenant_id=tenant_id, action="person.linked", actor_type="system", actor_id="dedupe", object_type="duplicate_candidate",
                        object_id=existing.id, reason="names_agree_and_identifier_agrees", acting_for_person_id=me,
                        details={"score": result.score, "other_person_id": str(other), "automatic": True})  # fmt: skip
        return result.band
    candidate = models.DuplicateCandidate(
        id=uuid.uuid4(), tenant_id=tenant_id, person_a_id=other, person_b_id=me, score=result.score, band=result.band, evidence=evidence,
        status="linked" if result.band == "same" else "open", resolved_at=now if result.band == "same" else None, created_at=now,
    )  # fmt: skip
    db.add(candidate)
    db.flush()
    if result.band == "same":
        audit.write(db, tenant_id=tenant_id, action="person.linked", actor_type="system", actor_id="dedupe", object_type="duplicate_candidate",
                    object_id=candidate.id, reason="names_agree_and_identifier_agrees", acting_for_person_id=me,
                    details={"score": result.score, "other_person_id": str(other), "automatic": True})  # fmt: skip
    else:
        audit.write(db, tenant_id=tenant_id, action="duplicate.flagged", actor_type="system", actor_id="dedupe", object_type="duplicate_candidate",
                    object_id=candidate.id, reason=",".join(result.reasons), acting_for_person_id=me,
                    details={"score": result.score, "other_person_id": str(other), "name_score": result.name.score})  # fmt: skip
        _open_review(db, tenant_id, me, application_id, candidate, result, other)
    return result.band


def check_duplicates(db: Session, *, tenant_id: uuid.UUID, person_id: uuid.UUID, application_id: uuid.UUID | None = None) -> DuplicateEvidence | None:
    """Compare a person with the department's register. None when the person cannot be read or is not active.

    Runs in the caller's transaction for its writes (pair rows, review case, audit); the caller commits.
    """
    me = db.get(models.Person, person_id)
    if me is None or me.tenant_id != tenant_id or me.status in IGNORED_STATUSES:
        return None
    tenant = db.get(models.Tenant, tenant_id)
    key = person_name_key(me)
    if me.name_key != key:
        me.name_key = key  # the blocking index for later applicants
    my_record = person_record(me, tenant)
    candidates = _candidates(tenant_id, me, my_record, tenant)
    scored = [(other_id, compare(my_record, record)) for other_id, record in candidates]
    flagged = [(other_id, result) for other_id, result in scored if result.band != "distinct"]
    effective: list[tuple[str, float, uuid.UUID]] = []
    for other_id, result in flagged:
        band = _record_pair(db, tenant_id, me.id, other_id, result, application_id)
        effective.append((band, result.score, other_id))
    for other_id, result in scored:
        if result.band == "distinct":
            effective.append(("distinct", result.score, other_id))
    audit.write(db, tenant_id=tenant_id, action="person.dedupe_checked", actor_type="system", actor_id="dedupe", object_type="person",
                object_id=me.id, acting_for_person_id=me.id,
                details={"candidates": len(candidates), "flagged": len(flagged), "application_id": str(application_id) if application_id else None,
                         "bands": {b: sum(1 for e in effective if e[0] == b) for b in ("same", "possible", "distinct")}})  # fmt: skip
    if not effective:
        return DuplicateEvidence(band="distinct", score=0.0, other_person_ref=None)
    band, score, other = max(effective, key=lambda e: (BAND_ORDER[e[0]], e[1]))
    return DuplicateEvidence(band=band, score=round(score, 4), other_person_ref=str(other) if band != "distinct" else None)


def backfill_name_keys(db: Session, tenant_ids: Iterable[uuid.UUID] | None = None) -> int:
    """Fill the blocking key of every active person that has none (seed and maintenance; system session)."""
    query = select(models.Person).where(models.Person.name_key.is_(None), models.Person.status.not_in(IGNORED_STATUSES))
    if tenant_ids is not None:
        query = query.where(models.Person.tenant_id.in_(list(tenant_ids)))
    count = 0
    for person in db.scalars(query).all():
        key = person_name_key(person)
        if key:
            person.name_key = key
            count += 1
    db.flush()
    return count


@lru_cache(maxsize=1)
def fixture_report() -> dict[str, Any]:
    """Precision and recall of each band on the labelled messy fixtures (pure; cached for the process)."""
    report = evaluate(build_fixtures())
    report["unexpected"] = report["unexpected"][:10]
    return report


# --- officers ------------------------------------------------------------------------------------------


def _candidate(db: Session, principal: Principal, candidate_id: uuid.UUID, *, lock: bool = False) -> models.DuplicateCandidate:
    query = select(models.DuplicateCandidate).where(models.DuplicateCandidate.id == candidate_id,
                                                    models.DuplicateCandidate.tenant_id == principal.tenant_id)  # fmt: skip
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise NotFound("Duplicate record not found.", code="duplicate_not_found")
    return row


def _readable(db: Session, principal: Principal, row: models.DuplicateCandidate) -> tuple[models.Person, models.Person]:
    """Both people, through Row Level Security: without both consents the officer cannot see or decide the pair."""
    a, b = db.get(models.Person, row.person_a_id), db.get(models.Person, row.person_b_id)
    if a is None or b is None:
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="duplicate_candidate", object_id=row.id, result="denied", reason="no_active_consent",
        )  # fmt: skip
        raise Forbidden("You cannot see one of these people without their active consent.", code="consent_required")
    return a, b


def _person_view(person: models.Person | None) -> dict[str, Any]:
    if person is None:
        return {"readable": False}
    return {"readable": True, "id": str(person.id), "full_name": person.full_name, "full_name_ur": person.full_name_ur,
            "dob": person.dob.isoformat() if person.dob else None, "gender": person.gender, "district": person.district,
            "status": person.status}  # fmt: skip


def candidate_view(db: Session, row: models.DuplicateCandidate, *, detail: bool = False) -> dict[str, Any]:
    a, b = db.get(models.Person, row.person_a_id), db.get(models.Person, row.person_b_id)
    out: dict[str, Any] = {
        "id": str(row.id), "status": row.status, "band": row.band, "score": row.score, "case_id": str(row.case_id) if row.case_id else None,
        "created_at": row.created_at.isoformat(), "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "person_a": _person_view(a), "person_b": _person_view(b), "reasons": list((row.evidence or {}).get("reasons", [])),
    }  # fmt: skip
    if detail:
        out["evidence"] = dict(row.evidence or {})
        if a is not None and b is not None:
            tenant = db.get(models.Tenant, row.tenant_id)
            out["comparison_now"] = compare(person_record(a, tenant), person_record(b, tenant)).evidence()
    return out


def list_candidates(db: Session, principal: Principal, *, status: str | None, limit: int, before: str | None) -> dict[str, Any]:
    query = select(models.DuplicateCandidate).where(models.DuplicateCandidate.tenant_id == principal.tenant_id)
    if status and status != "all":
        query = query.where(models.DuplicateCandidate.status == status)
    after = paging.before((models.DuplicateCandidate.created_at, models.DuplicateCandidate.id), before)
    if after is not None:
        query = query.where(after)
    rows = db.scalars(query.order_by(models.DuplicateCandidate.created_at.desc(), models.DuplicateCandidate.id.desc()).limit(limit + 1)).all()
    cursor = paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return {"items": [candidate_view(db, r) for r in rows[:limit]], "next_cursor": cursor}


def get_candidate(db: Session, principal: Principal, candidate_id: uuid.UUID) -> dict[str, Any]:
    row = _candidate(db, principal, candidate_id)
    _readable(db, principal, row)
    return candidate_view(db, row, detail=True)


def _resolve_case(db: Session, principal: Principal, row: models.DuplicateCandidate, action: str, reason: str) -> None:
    if row.case_id is None:
        return
    case = db.get(models.Case, row.case_id)
    if case is None or case.status in ("resolved", "closed"):
        return
    from app.contracts.api import CaseActionIn
    from app.modules.cases.service import act

    act(db, principal, case.id, CaseActionIn(action=action, reason=reason))


def decide_pair(db: Session, principal: Principal, candidate_id: uuid.UUID, *, decision: str, reason: str) -> dict[str, Any]:
    """An officer's answer: link (one person), distinct (two people) or unlink (reverse a link). Audited."""
    row = _candidate(db, principal, candidate_id, lock=True)
    _readable(db, principal, row)
    allowed = {"link": ("open", "rejected", "reversed"), "distinct": ("open",), "unlink": ("linked",)}[decision]
    if row.status not in allowed:
        raise Conflict(f"This pair is {row.status}; it cannot be {decision}ed.", code="illegal_transition", extra={"status": row.status})
    before = row.status
    row.status = {"link": "linked", "distinct": "rejected", "unlink": "reversed"}[decision]
    row.resolved_by = principal.user_id
    row.resolved_at = datetime.now(UTC)
    db.flush()
    action = {"link": "person.linked", "distinct": "duplicate.rejected", "unlink": "person.unlinked"}[decision]
    audit.write(db, tenant_id=principal.tenant_id, action=action, actor_id=principal.user_id, actor_role=principal.role,
                object_type="duplicate_candidate", object_id=row.id, reason=reason,
                details={"from": before, "to": row.status, "person_a_id": str(row.person_a_id), "person_b_id": str(row.person_b_id),
                         "score": row.score, "automatic": False})  # fmt: skip
    if decision in ("link", "distinct"):
        _resolve_case(db, principal, row, "approve" if decision == "link" else "reject", reason)
    return candidate_view(db, row, detail=True)
