"""Seed: ingest the policy corpus for every department. Safe to run twice (unchanged documents are skipped)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.modules.rag.ingest import department_ids, ingest

ORDER = 70
log = get_logger("rahat.rag")


def seed(db: Session) -> None:
    for tenant_id in department_ids(db):
        report = ingest(db, tenant_id)
        if report.refused:
            log.warning("policy corpus: %s", "; ".join(report.refused))
