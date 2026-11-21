"""One active consent per person, grantee and purpose; tracking codes unique within a department

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-21 14:50:00

The services already prevent both with locks. The indexes make the database refuse a duplicate even when
two requests race.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_consents_active", "consents", ["tenant_id", "person_id", "grantee_type", "grantee_id", "purpose"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )  # fmt: skip
    op.create_index(
        "uq_applications_tracking_code", "applications", ["tenant_id", "tracking_code"],
        unique=True, postgresql_where=sa.text("tracking_code IS NOT NULL"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("uq_applications_tracking_code", table_name="applications")
    op.drop_index("uq_consents_active", table_name="consents")
