"""Test helpers that create a program with published rules and an application inside a test tenant."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core import audit
from app.core.db import RlsContext, session_scope, system_session
from app.db import models
from app.seed import RULES_V1


@dataclass
class ProgramSetup:
    program_id: uuid.UUID
    rule_set_id: uuid.UUID
    v1_id: uuid.UUID


def make_program(tenant_id: uuid.UUID, *, dsl: dict[str, Any] | None = None) -> ProgramSetup:
    with system_session() as db:
        program = models.Program(id=uuid.uuid4(), tenant_id=tenant_id, slug="rahat", name="Rahat (Prototype Relief Program)")
        db.add(program)
        db.flush()
        rule_set = models.RuleSet(id=uuid.uuid4(), tenant_id=tenant_id, program_id=program.id, name="Rahat eligibility")
        db.add(rule_set)
        db.flush()
        body = copy.deepcopy(dsl or RULES_V1)
        now = datetime.now(UTC)
        version = models.RuleVersion(id=uuid.uuid4(), tenant_id=tenant_id, rule_set_id=rule_set.id, version_no=1, status="published",
                                     dsl=body, content_hash=audit.hash_payload(body), published_at=now, effective_from=now)  # fmt: skip
        db.add(version)
        db.flush()
        rule_set.active_version_id = version.id
        return ProgramSetup(program_id=program.id, rule_set_id=rule_set.id, v1_id=version.id)


def make_application(tenant_id: uuid.UUID, person_id: uuid.UUID, program_id: uuid.UUID) -> uuid.UUID:
    with system_session() as db:
        app_row = models.Application(id=uuid.uuid4(), tenant_id=tenant_id, program_id=program_id, person_id=person_id, status="submitted",
                                     client_op_id=f"test-{uuid.uuid4().hex[:16]}")  # fmt: skip
        db.add(app_row)
        db.flush()
        return app_row.id


def citizen_session(account: Any) -> Any:
    """A session as the citizen who submits (what Track A's submit pipeline runs in)."""
    return session_scope(RlsContext(role="citizen", tenant_id=account.tenant_id, user_id=account.user_id, person_id=account.person_id))


def withdraw_consent(tenant_id: uuid.UUID, person_id: uuid.UUID) -> None:
    from sqlalchemy import update

    with system_session() as db:
        db.execute(update(models.Consent).where(models.Consent.tenant_id == tenant_id, models.Consent.person_id == person_id)
                   .values(status="withdrawn", withdrawn_at=datetime.now(UTC)))  # fmt: skip
