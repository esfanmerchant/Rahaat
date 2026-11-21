"""Row Level Security building blocks used by migrations.

The app connects as `rahat_app`: not the table owner, no BYPASSRLS. Policies read transaction-local
settings that the API sets at the start of every transaction (app/core/db.py). With no settings, the
helper functions return NULL / 'none' and every policy is false, so the default is "see nothing".

Layers:
1. `tenant_isolation` on every tenant table: a row is visible only inside its own tenant.
2. `person_access` (RESTRICTIVE, SELECT) on tables that hold a person's data: on top of the tenant
   check, the caller must be that citizen, a helper with a live delegation, or staff whose department
   holds an active consent. Withdrawing consent therefore stops access inside the database itself.
3. Grants: the app role cannot UPDATE or DELETE append-only tables (audit log, consent events).
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

APP_ROLE = "rahat_app"

FUNCTIONS = """
CREATE OR REPLACE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.role', true), ''), 'none') $$;

CREATE OR REPLACE FUNCTION app_is_system() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT COALESCE(current_setting('app.role', true), '') = 'system' $$;

CREATE OR REPLACE FUNCTION app_tenant_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_user_id() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

-- Runs with the owner's rights so it can read consent tables without recursing into their policies.
CREATE OR REPLACE FUNCTION app_can_read_person(pid uuid) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE
  r   text := COALESCE(NULLIF(current_setting('app.role', true), ''), 'none');
  uid uuid := NULLIF(current_setting('app.user_id', true), '')::uuid;
  tid uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
BEGIN
  IF r = 'system' THEN
    RETURN true;
  END IF;
  IF pid IS NULL OR tid IS NULL THEN
    RETURN false;
  END IF;
  IF r = 'citizen' THEN
    RETURN EXISTS (SELECT 1 FROM persons p WHERE p.id = pid AND p.tenant_id = tid AND p.user_id = uid);
  ELSIF r = 'helper' THEN
    RETURN EXISTS (
      SELECT 1 FROM helper_delegations d
      WHERE d.person_id = pid AND d.tenant_id = tid AND d.helper_user_id = uid
        AND d.revoked_at IS NULL AND d.expires_at > now());
  ELSIF r IN ('officer', 'api_client', 'worker') THEN
    RETURN EXISTS (
      SELECT 1 FROM consents c
      WHERE c.person_id = pid AND c.tenant_id = tid AND c.status = 'active'
        AND c.grantee_type = 'tenant' AND c.grantee_id = tid
        AND (c.expires_at IS NULL OR c.expires_at > now()));
  END IF;
  -- Admins manage configuration and auditors read redacted records: neither reads a person's raw data.
  RETURN false;
END $$;
"""

DROP_FUNCTIONS = """
DROP FUNCTION IF EXISTS app_can_read_person(uuid);
DROP FUNCTION IF EXISTS app_user_id();
DROP FUNCTION IF EXISTS app_tenant_id();
DROP FUNCTION IF EXISTS app_is_system();
DROP FUNCTION IF EXISTS app_role();
"""

_TENANT_CHECK = "(tenant_id = app_tenant_id() OR app_is_system())"

GLOBAL_POLICIES = """
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
CREATE POLICY plans_read ON plans FOR SELECT USING (true);
CREATE POLICY plans_write ON plans FOR ALL USING (app_is_system()) WITH CHECK (app_is_system());

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenants_read ON tenants FOR SELECT USING (
  id = app_tenant_id() OR app_is_system()
  OR EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = tenants.id AND m.user_id = app_user_id()));
CREATE POLICY tenants_insert ON tenants FOR INSERT WITH CHECK (app_is_system());
CREATE POLICY tenants_update ON tenants FOR UPDATE
  USING ((id = app_tenant_id() AND app_role() = 'admin') OR app_is_system())
  WITH CHECK ((id = app_tenant_id() AND app_role() = 'admin') OR app_is_system());
CREATE POLICY tenants_delete ON tenants FOR DELETE USING (app_is_system());

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_self ON users FOR ALL
  USING (id = app_user_id() OR app_is_system()) WITH CHECK (id = app_user_id() OR app_is_system());
CREATE POLICY users_staff_read ON users FOR SELECT USING (
  app_role() IN ('officer', 'admin', 'auditor')
  AND EXISTS (SELECT 1 FROM memberships m WHERE m.user_id = users.id AND m.tenant_id = app_tenant_id()));

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY sessions_self ON sessions FOR ALL
  USING (user_id = app_user_id() OR app_is_system()) WITH CHECK (user_id = app_user_id() OR app_is_system());

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
CREATE POLICY memberships_read ON memberships FOR SELECT
  USING (tenant_id = app_tenant_id() OR user_id = app_user_id() OR app_is_system());
CREATE POLICY memberships_insert ON memberships FOR INSERT
  WITH CHECK ((tenant_id = app_tenant_id() AND app_role() = 'admin') OR app_is_system());
CREATE POLICY memberships_update ON memberships FOR UPDATE
  USING ((tenant_id = app_tenant_id() AND app_role() = 'admin') OR app_is_system())
  WITH CHECK ((tenant_id = app_tenant_id() AND app_role() = 'admin') OR app_is_system());
CREATE POLICY memberships_delete ON memberships FOR DELETE
  USING ((tenant_id = app_tenant_id() AND app_role() = 'admin') OR app_is_system());
"""

# Tables with their own policies above; the generic tenant policy is not applied to them.
SPECIAL_TABLES = ("plans", "tenants", "users", "sessions", "memberships")


def _run(op: Any, statements: str) -> None:
    """Send raw SQL exactly as written (several statements, no bind-parameter parsing)."""
    op.get_bind().exec_driver_sql(statements)


def install_functions(op: Any) -> None:
    _run(op, FUNCTIONS)


def drop_functions(op: Any) -> None:
    _run(op, DROP_FUNCTIONS)


def install_global_policies(op: Any) -> None:
    _run(op, GLOBAL_POLICIES)


def drop_cross_table_policies(op: Any) -> None:
    """Policies that read another table must go before that table can be dropped (downgrade only)."""
    _run(op, "DROP POLICY IF EXISTS tenants_read ON tenants; DROP POLICY IF EXISTS users_staff_read ON users;")


def enable_tenant_rls(op: Any, table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" FOR ALL USING {_TENANT_CHECK} WITH CHECK {_TENANT_CHECK}'
    )


def enable_person_rls(op: Any, table: str, person_column: str) -> None:
    op.execute(
        f'CREATE POLICY person_access ON "{table}" AS RESTRICTIVE FOR SELECT '
        f'USING (app_is_system() OR app_can_read_person("{person_column}"))'
    )


def create_app_role(op: Any, password: str) -> None:
    """Create the runtime role once. Its password is re-synced on every migration run (env.py)."""
    connection = op.get_bind()
    exists = connection.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,)).first()
    if not exists:
        statement = sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}").format(
            sql.Identifier(APP_ROLE), sql.Literal(password)
        )
        connection.connection.driver_connection.execute(statement)


def grant_app_role(op: Any, append_only: tuple[str, ...]) -> None:
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}")
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE}")
    for table in append_only:
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{table}" FROM {APP_ROLE}')
    # Tables created by later migrations get the same default grants.
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}")
