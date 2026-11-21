"""Row Level Security, checked with raw SQL as the runtime role, bypassing the API entirely.

If the API forgot every filter, these are the guarantees the database would still give.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine, system_session
from app.db import models

_SET = text(
    "SELECT set_config('app.role', :role, true), set_config('app.tenant_id', :tenant, true), "
    "set_config('app.user_id', :user, true)"
)


def _as(conn: Connection, role: str, tenant: Any = None, user: Any = None) -> None:
    conn.execute(_SET, {"role": role, "tenant": str(tenant or ""), "user": str(user or "")})


def _count(conn: Connection, table: str, where: str = "true") -> int:
    return int(conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar_one())


def _case(tenant_id: uuid.UUID, person_id: uuid.UUID | None = None) -> uuid.UUID:
    with system_session() as db:
        case = models.Case(tenant_id=tenant_id, kind="application_review", subject_person_id=person_id)
        db.add(case)
        db.flush()
        return case.id


def _application(tenant_id: uuid.UUID, person_id: uuid.UUID) -> uuid.UUID:
    with system_session() as db:
        program = models.Program(tenant_id=tenant_id, slug=f"p-{uuid.uuid4().hex[:8]}", name="Test program")
        db.add(program)
        db.flush()
        application = models.Application(tenant_id=tenant_id, program_id=program.id, person_id=person_id)
        db.add(application)
        db.flush()
        return application.id


def test_runtime_role_is_not_privileged(database: None) -> None:
    with get_engine().connect() as conn:
        role = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert conn.execute(text("SELECT current_user")).scalar_one() == "rahat_app"
        assert role.rolsuper is False and role.rolbypassrls is False
        owners = conn.execute(text("SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
        assert "rahat_app" not in owners, "the runtime role must not own tables, or RLS would not apply to it"


def test_every_table_has_row_level_security(database: None) -> None:
    with get_engine().connect() as conn:
        unprotected = conn.execute(text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity AND c.relname <> 'alembic_version'"
        )).scalars().all()  # fmt: skip
        assert unprotected == []


def test_without_a_context_nothing_is_visible(factory: Any) -> None:
    tenant = factory.tenant()
    factory.account(tenant, "citizen")
    _case(tenant.id)
    with get_engine().connect() as conn:
        for table in ("tenants", "users", "memberships", "persons", "consents", "cases", "audit_log", "sessions"):
            assert _count(conn, table) == 0, f"{table} leaked rows to a connection with no context"


def test_one_tenant_cannot_read_or_write_another(factory: Any) -> None:
    mine, theirs = factory.tenant("Mine"), factory.tenant("Theirs")
    officer = factory.account(mine, "officer")
    _case(mine.id)
    their_case = _case(theirs.id)

    with get_engine().connect() as conn:
        _as(conn, "officer", mine.id, officer.user_id)
        assert _count(conn, "cases") == 1
        assert _count(conn, "cases", f"tenant_id = '{theirs.id}'") == 0
        assert _count(conn, "tenants") == 1, "only my own department is visible"
        updated = conn.execute(text("UPDATE cases SET priority = 1 WHERE id = :id"), {"id": their_case})
        assert updated.rowcount == 0, "another tenant's row cannot be changed"
        deleted = conn.execute(text("DELETE FROM cases WHERE id = :id"), {"id": their_case})
        assert deleted.rowcount == 0
        conn.rollback()

    with get_engine().connect() as conn:
        _as(conn, "officer", mine.id, officer.user_id)
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(
                text("INSERT INTO cases (id, tenant_id, kind, status, priority, opened_reason, handoff) "
                     "VALUES (:id, :tenant, 'complaint', 'open', 50, 'test', '{}')"),
                {"id": uuid.uuid4(), "tenant": theirs.id},
            )  # fmt: skip


def test_consent_gates_staff_access_and_withdrawal_stops_it_at_once(factory: Any) -> None:
    tenant = factory.tenant()
    officer, citizen = factory.account(tenant, "officer"), factory.account(tenant, "citizen")
    _application(tenant.id, citizen.person_id)

    with get_engine().connect() as conn:
        _as(conn, "officer", tenant.id, officer.user_id)
        assert _count(conn, "persons") == 1 and _count(conn, "applications") == 1

    with system_session() as db:
        db.execute(
            text("UPDATE consents SET status = 'withdrawn', withdrawn_at = now() WHERE person_id = :p"),
            {"p": citizen.person_id},
        )

    with get_engine().connect() as conn:
        _as(conn, "officer", tenant.id, officer.user_id)
        assert _count(conn, "persons") == 0, "withdrawal must stop access inside the database"
        assert _count(conn, "applications") == 0
        changed = conn.execute(text("UPDATE persons SET district = 'x' WHERE id = :p"), {"p": citizen.person_id})
        assert changed.rowcount == 0, "a row that cannot be read cannot be changed"
        for role in ("api_client", "worker"):
            _as(conn, role, tenant.id)
            assert _count(conn, "persons") == 0, f"{role} must lose access too"
        _as(conn, "citizen", tenant.id, citizen.user_id)
        assert _count(conn, "persons") == 1, "the citizen still sees their own record"


def test_an_expired_consent_counts_as_no_consent(factory: Any) -> None:
    tenant = factory.tenant()
    officer, citizen = factory.account(tenant, "officer"), factory.account(tenant, "citizen")
    with system_session() as db:
        db.execute(text("UPDATE consents SET expires_at = now() - interval '1 minute' WHERE person_id = :p"), {"p": citizen.person_id})
    with get_engine().connect() as conn:
        _as(conn, "officer", tenant.id, officer.user_id)
        assert _count(conn, "persons") == 0


def test_a_citizen_sees_only_their_own_record(factory: Any) -> None:
    tenant = factory.tenant()
    one, two = factory.account(tenant, "citizen"), factory.account(tenant, "citizen")
    with get_engine().connect() as conn:
        _as(conn, "citizen", tenant.id, one.user_id)
        rows = conn.execute(text("SELECT id FROM persons")).scalars().all()
        assert rows == [one.person_id] and two.person_id not in rows


def test_a_helper_needs_a_live_delegation_for_each_person(factory: Any) -> None:
    tenant = factory.tenant()
    helper = factory.account(tenant, "helper")
    family_a, family_b = factory.account(tenant, "citizen"), factory.account(tenant, "citizen")

    def visible() -> list[uuid.UUID]:
        with get_engine().connect() as conn:
            _as(conn, "helper", tenant.id, helper.user_id)
            return list(conn.execute(text("SELECT id FROM persons")).scalars().all())

    assert visible() == [], "no delegation, no access"
    with system_session() as db:
        delegation = models.HelperDelegation(
            tenant_id=tenant.id, helper_user_id=helper.user_id, person_id=family_a.person_id,
            scopes=["apply"], expires_at=datetime.now(UTC) + timedelta(days=1),
        )  # fmt: skip
        db.add(delegation)
        db.flush()
        delegation_id = delegation.id
    assert visible() == [family_a.person_id], "one family's consent does not open another family"
    assert family_b.person_id not in visible()

    with system_session() as db:
        db.execute(text("UPDATE helper_delegations SET revoked_at = now() WHERE id = :d"), {"d": delegation_id})
    assert visible() == [], "revoking stops access on the next query"

    with system_session() as db:
        db.execute(text("UPDATE helper_delegations SET revoked_at = NULL, expires_at = now() - interval '1 second' WHERE id = :d"),
                   {"d": delegation_id})  # fmt: skip
    assert visible() == [], "an expired delegation is not access"


def test_admins_and_auditors_do_not_read_personal_records(factory: Any) -> None:
    tenant = factory.tenant()
    admin, auditor = factory.account(tenant, "admin"), factory.account(tenant, "auditor")
    factory.account(tenant, "citizen")
    with get_engine().connect() as conn:
        for account in (admin, auditor):
            _as(conn, account.role, tenant.id, account.user_id)
            assert _count(conn, "persons") == 0
            assert _count(conn, "consents") == 1, "consent records themselves stay reviewable"


def test_the_audit_log_cannot_be_rewritten_by_the_app(factory: Any) -> None:
    tenant = factory.tenant()
    for statement in ("UPDATE audit_log SET reason = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log",
                      "UPDATE consent_events SET event = 'x'", "DELETE FROM audit_anchors"):  # fmt: skip
        with get_engine().connect() as conn:
            _as(conn, "system", tenant.id)
            with pytest.raises(DBAPIError, match="permission denied"):
                conn.execute(text(statement))


def test_a_malformed_context_fails_closed(factory: Any) -> None:
    factory.tenant()
    with get_engine().connect() as conn:
        _as(conn, "officer", "not-a-uuid")
        with pytest.raises(DBAPIError):
            _count(conn, "cases")
