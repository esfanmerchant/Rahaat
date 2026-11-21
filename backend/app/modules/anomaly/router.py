"""Anomaly flags for staff.

GET  /v1/anomalies        the last detection run and every flag (each flag is an `anomaly_review` case)
POST /v1/anomalies/run    queue a detection run now; it runs as a background job and the page reads the result with GET
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.anomaly import service
from app.modules.anomaly.schemas import AnomaliesOut, ScanQueuedOut

router = APIRouter(prefix="/v1/anomalies", tags=["anomalies"])
_read = Policy("anomalies:read", ["admin", "officer", "auditor"], description="Anomaly flags and the last detection run (staff only)")
_run = Policy("anomalies:run", ["admin", "officer"], description="Queue an anomaly detection run now", cost=5)


@router.get("", response_model=AnomaliesOut, summary="Anomaly flags by detector and the last run")
def list_anomalies(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> AnomaliesOut:
    return service.overview(db, principal.tenant_id)


@router.post("/run", response_model=ScanQueuedOut, status_code=202, summary="Run detection now (queued as a job)")
def run_now(principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> ScanQueuedOut:
    job, already = service.enqueue_scan(db, principal.tenant_id, trigger="manual")
    audit.write(db, tenant_id=principal.tenant_id, action="anomaly.run_requested", actor_id=principal.user_id, actor_role=principal.role,
                object_type="job", object_id=job.id, details={"already_queued": already})  # fmt: skip
    db.commit()
    return ScanQueuedOut(job_id=job.id, status=job.status, already_queued=already)
