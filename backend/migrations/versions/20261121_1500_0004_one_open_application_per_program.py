"""One open application per person and program

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-21 15:00:00

Found by running the anchor flow on the live site: the same person could open two applications for one
program and be paid for both. The service now refuses a second open application (409 application_exists);
this index makes the database refuse it too. A person may apply again after a rejection or a withdrawal.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_applications_one_open", "applications", ["tenant_id", "person_id", "program_id"],
        unique=True, postgresql_where=sa.text("status NOT IN ('rejected', 'withdrawn')"),
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("uq_applications_one_open", table_name="applications")
