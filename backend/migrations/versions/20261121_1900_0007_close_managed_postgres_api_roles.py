"""Managed Postgres (Supabase) API roles get no access to our tables

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-21 19:00:00

Supabase grants its REST API roles (`anon`, `authenticated`) access to every table in `public`. RLS already
hides every row from them, but the app never uses that API, so take the grants away too. A no-op where
those roles do not exist (the embedded database, plain Postgres).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
      EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM %I', r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM %I', r);
    END IF;
  END LOOP;
END $$;
"""


def upgrade() -> None:
    op.get_bind().connection.driver_connection.execute(UPGRADE)  # type: ignore[union-attr]


def downgrade() -> None:
    pass  # the grants were never ours to restore
