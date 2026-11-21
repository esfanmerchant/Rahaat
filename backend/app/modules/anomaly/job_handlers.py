"""Job kinds of the anomaly module (discovered by app.modules.jobs)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.anomaly import service
from app.modules.jobs.service import JobContext


def scan_job(db: Session, job: JobContext) -> None:
    service.scan(db, job.tenant_id, trigger=str(job.payload.get("trigger", "job"))[:16])


HANDLERS = {service.JOB_KIND: scan_job}
