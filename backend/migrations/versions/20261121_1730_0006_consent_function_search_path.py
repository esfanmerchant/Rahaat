"""The consent check cannot be fooled by a temporary table

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-21 17:30:00

Found by the security suite (docs/SECURITY_REPORT.md): app_can_read_person runs with its owner's rights and
`search_path = public`, but Postgres searches the session's temporary schema first for tables unless it is
named last. The app role could create a temporary `consents` table and bring back a person whose consent was
withdrawn. Now pg_temp is searched last, and the app role cannot create temporary tables at all.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
ALTER FUNCTION app_can_read_person(uuid) SET search_path = public, pg_temp;
DO $$ BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM rahat_app', current_database());
EXCEPTION WHEN insufficient_privilege THEN
  RAISE NOTICE 'not the database owner: TEMPORARY stays granted; the search_path fix above still applies';
END $$;
"""

DOWNGRADE = """
ALTER FUNCTION app_can_read_person(uuid) SET search_path = public;
DO $$ BEGIN
  EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database());
END $$;
"""


def _run(sql: str) -> None:
    op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
