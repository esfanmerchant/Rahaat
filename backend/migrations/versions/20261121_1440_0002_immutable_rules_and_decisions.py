"""Published rule versions and stored decisions cannot be rewritten, even by a buggy service

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21 14:40:00

The services already treat these rows as immutable. These triggers make the database refuse it too:

- A rule version that is published or retired keeps its content forever. The only change allowed is
  published -> retired when a newer version is published. It cannot be deleted. A rollback is a new version.
- A decision keeps everything that explains and replays it. Only the links to its case and to a decision
  that superseded it may be filled in later. (Deleting an application still removes its decisions, so a
  deletion request can be honoured.)
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = """
CREATE OR REPLACE FUNCTION rule_versions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status NOT IN ('published', 'retired') THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'rule version % is % and cannot be deleted; publish a new version instead', OLD.id, OLD.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'published' AND NEW.status = 'retired') THEN
    RAISE EXCEPTION 'rule version % cannot move from % to %', OLD.id, OLD.status, NEW.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  IF (NEW.dsl, NEW.content_hash, NEW.version_no, NEW.rule_set_id, NEW.tenant_id, NEW.description_en, NEW.description_ur,
      NEW.effective_from, NEW.created_by, NEW.approved_by, NEW.published_at, NEW.parent_version_id, NEW.high_impact)
     IS DISTINCT FROM
     (OLD.dsl, OLD.content_hash, OLD.version_no, OLD.rule_set_id, OLD.tenant_id, OLD.description_en, OLD.description_ur,
      OLD.effective_from, OLD.created_by, OLD.approved_by, OLD.published_at, OLD.parent_version_id, OLD.high_impact) THEN
    RAISE EXCEPTION 'rule version % is % and its content cannot change; create a new version', OLD.id, OLD.status
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER rule_versions_immutable BEFORE UPDATE OR DELETE ON rule_versions
  FOR EACH ROW EXECUTE FUNCTION rule_versions_guard();

CREATE OR REPLACE FUNCTION decisions_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW) - 'case_id' - 'superseded_by') IS DISTINCT FROM (to_jsonb(OLD) - 'case_id' - 'superseded_by') THEN
    RAISE EXCEPTION 'decision % is a stored record and cannot change; record a new decision instead', OLD.id
      USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER decisions_immutable BEFORE UPDATE ON decisions
  FOR EACH ROW EXECUTE FUNCTION decisions_guard();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS decisions_immutable ON decisions;
DROP FUNCTION IF EXISTS decisions_guard();
DROP TRIGGER IF EXISTS rule_versions_immutable ON rule_versions;
DROP FUNCTION IF EXISTS rule_versions_guard();
"""


def _run(sql: str) -> None:
    # Straight to the driver with no parameters, so the `%` in the RAISE messages is not read as a placeholder.
    op.get_bind().connection.driver_connection.execute(sql)  # type: ignore[union-attr]


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
