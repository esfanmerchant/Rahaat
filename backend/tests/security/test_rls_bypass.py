"""Raw SQL as the runtime role, skipping the API: what an SQL injection or a buggy query could try.

`tests/integration/test_rls.py` covers tenant isolation, consent and the append-only audit log. These probes
try to switch Row Level Security off, take over the schema, or fool the consent function.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine, get_owner_engine
from app.db.base import Base

# Transaction-local, like the app: a session-level setting would survive on the pooled connection.
_SET = text("SELECT set_config('app.role', :role, true), set_config('app.tenant_id', :tenant, true), "
            "set_config('app.user_id', :user, true)")  # fmt: skip


def _as(conn: Connection, role: str, tenant: Any, user: Any) -> None:
    conn.execute(_SET, {"role": role, "tenant": str(tenant), "user": str(user)})


def _refused(statement: str, params: dict[str, Any] | None = None) -> str:
    with get_engine().connect() as conn:
        with pytest.raises(DBAPIError) as caught:
            conn.execute(text(statement), params or {})
        conn.rollback()
    return str(caught.value).lower()


def test_without_a_context_every_table_is_empty(factory: Any) -> None:
    tenant = factory.tenant()
    factory.account(tenant, "citizen")
    factory.account(tenant, "officer")
    tables = [t.name for t in Base.metadata.sorted_tables if t.name != "plans"]  # plans are public by design
    with get_engine().connect() as conn:
        leaking = [name for name in tables if conn.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()]  # noqa: S608
    assert leaking == [], f"rows visible with no context: {leaking}"


@pytest.mark.parametrize("statement", [
    "ALTER TABLE persons DISABLE ROW LEVEL SECURITY",
    "ALTER TABLE cases NO FORCE ROW LEVEL SECURITY",
    "DROP POLICY tenant_isolation ON cases",
    "CREATE POLICY open_door ON cases FOR SELECT USING (true)",
    "ALTER POLICY person_access ON persons USING (true)",
    "CREATE OR REPLACE FUNCTION app_can_read_person(pid uuid) RETURNS boolean LANGUAGE sql AS 'SELECT true'",
    "ALTER FUNCTION app_can_read_person(uuid) OWNER TO rahat_app",
    "CREATE TABLE public.side_door (id int)",
    "SET ROLE postgres",
    "SELECT pg_read_file('postgresql.conf')",
    "COPY (SELECT 1) TO PROGRAM 'echo owned'",
    "ALTER ROLE rahat_app BYPASSRLS",
])  # fmt: skip
def test_the_runtime_role_cannot_switch_off_or_rewrite_row_level_security(database: None, statement: str) -> None:
    message = _refused(statement)
    assert any(word in message for word in ("permission denied", "must be owner", "must be superuser", "does not exist", "insufficient")), message


def test_the_runtime_role_cannot_hand_out_privileges(database: None) -> None:
    public_grants = text("SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a WHERE c.relname = 'persons' AND a.grantee = 0")
    with get_engine().connect() as conn:
        conn.execute(text("GRANT ALL ON persons TO PUBLIC"))  # Postgres only warns "no privileges were granted"
        assert conn.execute(public_grants).scalar_one() == 0
        conn.rollback()


def test_row_security_cannot_be_turned_off_for_a_session(factory: Any) -> None:
    tenant = factory.tenant()
    officer = factory.account(tenant, "officer")
    with get_engine().connect() as conn:
        _as(conn, "officer", tenant.id, officer.user_id)
        conn.execute(text("SET row_security = off"))
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(text("SELECT count(*) FROM cases"))  # Postgres refuses instead of returning unfiltered rows
        conn.rollback()


def _set_temp_privilege(grant: bool) -> None:
    """Owner-side switch for the second layer of the test below (raw driver call: the SQL contains %I)."""
    verb = "GRANT TEMPORARY ON DATABASE %I TO rahat_app" if grant else "REVOKE TEMPORARY ON DATABASE %I FROM rahat_app"
    with get_owner_engine().begin() as owner:
        owner.connection.driver_connection.execute(f"DO $$ BEGIN EXECUTE format('{verb}', current_database()); END $$;")


def test_a_temporary_table_cannot_stand_in_for_the_consent_table(factory: Any) -> None:
    """Two layers (migration 0006): the app role cannot create temporary tables at all, and even if it could, the
    consent function searches pg_temp last, so a forged temporary 'consents' table is never read."""
    tenant = factory.tenant()
    officer, citizen = factory.account(tenant, "officer"), factory.account(tenant, "citizen")
    create = text("CREATE TEMP TABLE consents (person_id uuid, tenant_id uuid, status text, grantee_type text, "
                  "grantee_id uuid, expires_at timestamptz)")  # fmt: skip
    with get_engine().connect() as conn:
        with pytest.raises(DBAPIError, match="permission denied to create temporary tables"):
            conn.execute(create)

    _set_temp_privilege(True)
    try:
        with get_engine().connect() as conn:
            _as(conn, "officer", tenant.id, officer.user_id)
            conn.execute(text("UPDATE consents SET status = 'withdrawn' WHERE person_id = :p"), {"p": citizen.person_id})
            assert conn.execute(text("SELECT count(*) FROM persons")).scalar_one() == 0, "withdrawn: the officer sees nobody"
            conn.execute(create)
            conn.execute(text("INSERT INTO consents VALUES (:p, :t, 'active', 'tenant', :t, NULL)"), {"p": citizen.person_id, "t": tenant.id})
            visible = conn.execute(text("SELECT count(*) FROM persons")).scalar_one()
            conn.rollback()
    finally:
        _set_temp_privilege(False)
    assert visible == 0, "a forged temporary 'consents' table brought the person back"
