"""Uploaded documents can be stored in the database

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-21 21:30:00

A serverless host (Vercel) has no disk shared between instances: a file written while one instance handled the
upload is missing when another one serves the officer. With DOCUMENT_STORE=db the bytes go into this table, in
the same transaction as the document row. Tenant isolation and the person-level read check apply as for
`documents`, and deleting a document deletes its bytes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from migrations import rls

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_blobs",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(op.f("ix_document_blobs_person_id"), "document_blobs", ["person_id"], unique=False)
    op.create_index(op.f("ix_document_blobs_tenant_id"), "document_blobs", ["tenant_id"], unique=False)
    rls.enable_tenant_rls(op, "document_blobs")
    rls.enable_person_rls(op, "document_blobs", "person_id")
    # Default privileges cover new tables only when the same role created them; grant explicitly to be sure.
    op.execute(f"GRANT SELECT, INSERT, DELETE ON document_blobs TO {rls.APP_ROLE}")


def downgrade() -> None:
    op.drop_table("document_blobs")
