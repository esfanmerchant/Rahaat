"""The database itself refuses to rewrite a published rule version or a stored decision."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.db import get_engine, system_session
from app.db import models

_SET_SYSTEM = text("SELECT set_config('app.role', 'system', true)")


def _rule_version(tenant_id: uuid.UUID, status: str) -> uuid.UUID:
    with system_session() as db:
        program = models.Program(tenant_id=tenant_id, slug=f"p-{uuid.uuid4().hex[:8]}", name="Test program")
        db.add(program)
        db.flush()
        rule_set = models.RuleSet(tenant_id=tenant_id, program_id=program.id, name="rules")
        db.add(rule_set)
        db.flush()
        version = models.RuleVersion(
            tenant_id=tenant_id, rule_set_id=rule_set.id, version_no=1, status=status, dsl={"all": []},
            content_hash="a" * 64, published_at=datetime.now(UTC) if status == "published" else None,
        )  # fmt: skip
        db.add(version)
        db.flush()
        return version.id


def _run(statement: str, params: dict[str, Any]) -> None:
    with get_engine().begin() as conn:
        conn.execute(_SET_SYSTEM)
        conn.execute(text(statement), params)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE rule_versions SET dsl = '{\"all\": [{\"id\": \"x\"}]}'::jsonb WHERE id = :id",
        "UPDATE rule_versions SET content_hash = repeat('b', 64) WHERE id = :id",
        "UPDATE rule_versions SET status = 'draft' WHERE id = :id",
        "DELETE FROM rule_versions WHERE id = :id",
    ],
)
def test_a_published_rule_version_cannot_be_rewritten(factory: Any, statement: str) -> None:
    version_id = _rule_version(factory.tenant().id, "published")
    with pytest.raises(IntegrityError, match="rule version"):
        _run(statement, {"id": version_id})


def test_a_published_version_can_only_be_retired(factory: Any) -> None:
    version_id = _rule_version(factory.tenant().id, "published")
    _run("UPDATE rule_versions SET status = 'retired' WHERE id = :id", {"id": version_id})
    with pytest.raises(IntegrityError):
        _run("UPDATE rule_versions SET status = 'published' WHERE id = :id", {"id": version_id})


def test_drafts_stay_editable(factory: Any) -> None:
    version_id = _rule_version(factory.tenant().id, "draft")
    _run("UPDATE rule_versions SET dsl = '{\"all\": []}'::jsonb, content_hash = NULL WHERE id = :id", {"id": version_id})
    _run("DELETE FROM rule_versions WHERE id = :id", {"id": version_id})


def test_a_stored_decision_cannot_be_rewritten_but_can_be_linked_to_its_case(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    version_id = _rule_version(tenant.id, "published")
    with system_session() as db:
        program_id = db.get(models.RuleSet, db.get(models.RuleVersion, version_id).rule_set_id).program_id
        application = models.Application(tenant_id=tenant.id, program_id=program_id, person_id=citizen.person_id)
        db.add(application)
        db.flush()
        decision = models.Decision(
            tenant_id=tenant.id, application_id=application.id, person_id=citizen.person_id, rule_version_id=version_id,
            model_version="m", input_hash="0" * 64, route="human", outcome="needs_human",
        )  # fmt: skip
        db.add(decision)
        db.flush()
        decision_id = decision.id

    _run("UPDATE decisions SET case_id = :case WHERE id = :id", {"id": decision_id, "case": uuid.uuid4()})
    for statement in (
        "UPDATE decisions SET outcome = 'approved', route = 'auto' WHERE id = :id",
        "UPDATE decisions SET input_hash = repeat('1', 64) WHERE id = :id",
        "UPDATE decisions SET explanation = '{\"rewritten\": true}'::jsonb WHERE id = :id",
    ):
        with pytest.raises(IntegrityError, match="decision"):
            _run(statement, {"id": decision_id})
