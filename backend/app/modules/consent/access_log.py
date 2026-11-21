"""Who looked at my data: reads and refused attempts, read back from the audit trail.

Every read of a person's data by staff, a helper or an API client writes one `person.data_viewed` row
(`object_type="person"`, `object_id=<person id>`) in the reader's own transaction, with what was read
(`details.what`) and why (`reason`, a purpose code). Refused attempts are already `access.denied` and
`helper.switch_denied` rows that name the person. The citizen's access log is a filtered, plain view of
those rows: who (role and department; a helper by name; never a staff member's name or email), what, why,
when, and whether it was allowed.

`entry_for` is pure and has DB-free tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.core import audit
from app.core.db import system_session
from app.core.deps import Principal
from app.db import models

VIEW_ACTION: Final = "person.data_viewed"

# Why a role reads a person's data, when the caller does not say.
DEFAULT_PURPOSE: Final[dict[str, str]] = {
    "officer": "case_review",
    "auditor": "audit",
    "helper": "helper_assist",
    "api_client": "partner_api",
    "admin": "administration",
    "worker": "processing",
}

# Rows about a person that the access log shows.
ACCESS_ACTIONS: Final = (VIEW_ACTION, "access.denied", "helper.switch_denied", "helper.switched", "person.data_exported")
# Things a helper did for the person, shown so the person can see what was done in their name.
HELPER_ACTIONS: Final = (
    "application.created", "application.updated", "application.submitted", "document.uploaded",
    "consent.granted", "consent.narrowed", "consent.withdrawn", "correction.requested",
)  # fmt: skip

EventKind = Literal["viewed", "denied", "helper_opened", "helper_acted", "exported"]
ActorKind = Literal["staff", "helper", "partner", "system"]
STAFF_ROLES: Final = frozenset({"officer", "admin", "auditor"})


def record_view(db: Session, principal: Principal, person_id: UUID, *, what: str, ref_id: UUID | str | None = None,
                purpose: str | None = None, details: dict[str, Any] | None = None) -> None:  # fmt: skip
    """Write the `person.data_viewed` row for one read, in the caller's transaction. The caller commits."""
    audit.write(
        db, tenant_id=principal.tenant_id, action=VIEW_ACTION, actor_type="api_key" if principal.auth_kind == "api_key" else "user",
        actor_id=principal.user_id, actor_role=principal.role, acting_for_person_id=person_id, object_type="person",
        object_id=person_id, reason=purpose or DEFAULT_PURPOSE.get(principal.role, "service"),
        details={"what": what, "ref_id": str(ref_id) if ref_id else None, **(details or {})},
    )  # fmt: skip


class AccessEntry(BaseModel):
    seq: int
    at: str
    event: EventKind
    action: str = Field(description="The raw audit action, for the auditor's cross-reference")
    what: str | None = Field(default=None, description="What was read: case_detail, document_content, decision_trace, ...")
    reason: str | None = Field(default=None, description="Why: a purpose code for reads, the refusal code for denied attempts")
    allowed: bool
    actor_kind: ActorKind
    actor_role: str | None = None
    actor_name: str | None = Field(default=None, description="Helpers only. Staff are shown by role and department")
    department: str


class AccessLogPage(Page):
    items: list[AccessEntry]


@dataclass(frozen=True, slots=True)
class AuditFacts:
    """The fields of an audit row that the access log reads."""

    seq: int
    ts: datetime
    action: str
    actor_type: str
    actor_id: str | None
    actor_role: str | None
    result: str
    reason: str | None
    details: dict[str, Any]


def facts(row: models.AuditLog) -> AuditFacts:
    try:
        details = json.loads(row.details or "{}")
    except ValueError:
        details = {}
    return AuditFacts(seq=row.seq, ts=row.ts, action=row.action, actor_type=row.actor_type, actor_id=row.actor_id,
                      actor_role=row.actor_role, result=row.result, reason=row.reason,
                      details=details if isinstance(details, dict) else {})  # fmt: skip


def _actor_kind(row: AuditFacts) -> ActorKind:
    if row.actor_type == "api_key" or row.actor_role == "api_client":
        return "partner"
    if row.actor_role == "helper":
        return "helper"
    if row.actor_role in STAFF_ROLES:
        return "staff"
    return "system"


def _event(row: AuditFacts) -> EventKind:
    if row.result == "denied" or row.action in ("access.denied", "helper.switch_denied"):
        return "denied"
    if row.action == VIEW_ACTION:
        return "viewed"
    if row.action == "helper.switched":
        return "helper_opened"
    if row.action == "person.data_exported":
        return "exported"
    return "helper_acted"


def _what(row: AuditFacts) -> str | None:
    if row.action == VIEW_ACTION:
        what = row.details.get("what")
        return str(what) if what else None
    if row.action in ("access.denied", "helper.switch_denied"):
        attempted = row.details.get("attempted") or row.details.get("scope")
        return str(attempted) if attempted else None
    return row.action


def entry_for(row: AuditFacts, *, department: str, helper_names: dict[str, str]) -> AccessEntry:
    """Pure: one audit row as the person sees it. No staff names, emails or ids ever leave this function."""
    kind = _actor_kind(row)
    return AccessEntry(
        seq=row.seq, at=row.ts.astimezone(UTC).isoformat(timespec="seconds"), event=_event(row), action=row.action,
        what=_what(row), reason=row.reason, allowed=row.result != "denied" and row.action not in ("access.denied", "helper.switch_denied"),
        actor_kind=kind, actor_role=row.actor_role if kind != "system" else None,
        actor_name=helper_names.get(row.actor_id or "") if kind == "helper" else None, department=department,
    )  # fmt: skip


def _helper_names(actor_ids: set[str]) -> dict[str, str]:
    """Display names of the helpers in this person's log. Narrow system lookup by id; nothing else is read."""
    ids: set[UUID] = set()
    for value in actor_ids:
        try:
            ids.add(UUID(value))
        except ValueError:
            continue
    if not ids:
        return {}
    with system_session() as sdb:
        rows = sdb.execute(select(models.User.id, models.User.display_name).where(models.User.id.in_(ids))).all()
    return {str(r.id): r.display_name for r in rows}


def access_log(db: Session, *, tenant_id: UUID, person_id: UUID, own_user_id: UUID | None, cursor: int | None = None,
               limit: int = DEFAULT_PAGE_SIZE) -> AccessLogPage:  # fmt: skip
    """Newest first. `own_user_id` is the person's own account: their own actions are not "someone looked"."""
    limit = max(1, min(limit or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE))
    log = models.AuditLog
    about = or_(and_(log.object_type == "person", log.object_id == str(person_id)), log.acting_for_person_id == person_id)
    kinds = or_(log.action.in_(ACCESS_ACTIONS), and_(log.actor_role == "helper", log.action.in_(HELPER_ACTIONS)))
    query = select(log).where(log.tenant_id == tenant_id, about, kinds)
    if own_user_id is not None:
        query = query.where(or_(log.actor_id.is_(None), log.actor_id != str(own_user_id)))
    if cursor:
        query = query.where(log.seq < cursor)
    rows = [facts(r) for r in db.scalars(query.order_by(log.seq.desc()).limit(limit + 1)).all()]
    page = rows[:limit]
    tenant = db.get(models.Tenant, tenant_id)
    names = _helper_names({r.actor_id for r in page if r.actor_role == "helper" and r.actor_id})
    department = tenant.name if tenant else "Department"
    return AccessLogPage(items=[entry_for(r, department=department, helper_names=names) for r in page],
                         next_cursor=str(page[-1].seq) if len(rows) > limit and page else None)  # fmt: skip
