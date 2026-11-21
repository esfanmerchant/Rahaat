"""One row per policy document version, even if the startup hook and the seed ingest at the same time

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-21 17:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_kb_document_version", "kb_documents", ["tenant_id", "source", "version_no"])


def downgrade() -> None:
    op.drop_constraint("uq_kb_document_version", "kb_documents", type_="unique")
