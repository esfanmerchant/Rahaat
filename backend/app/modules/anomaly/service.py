"""Run the detectors over a department's applications and turn findings into `anomaly_review` cases.

    scan(db, tenant_id, now=..., trigger="job")       detect, open or refresh cases, store the run, audit
    overview(db, tenant_id)                           the last run and the flags (their cases), for the staff page
    enqueue_scan(db, tenant_id, trigger="event")      queue one scan job unless one is already waiting
    anomaly_evidence_for(db, tenant_id, application)  an `AnomalyEvidence` for the decision engine's guard

Reading applications goes through Row Level Security: a scan runs as the `worker` role, so a person whose
consent has ended is left out of every pattern. A ring partly hidden that way is under-reported, which is
the safe direction. Identifiers are fingerprinted with a keyed hash before any detector sees them.
The last run is stored in `eval_runs` (kind `anomaly_scan`), so no migration is needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.decision import HandoffPackage, Hypothesis
from app.contracts.engine import AnomalyEvidence
from app.core import audit
from app.core.crypto import blind_index
from app.db import models
from app.modules.anomaly import detectors as D
from app.modules.anomaly.dedupe import Action, ExistingCase, plan_cases
from app.modules.anomaly.schemas import AnomaliesOut, DetectorStatus, FlagOut, ScanSummary
from app.modules.cases import paging
from app.modules.cases.rules import ACTIVE
from app.modules.cases.service import open_case

SCAN_RUN_KIND = "anomaly_scan"
JOB_KIND = "anomaly.scan"
CASE_KIND = "anomaly_review"
LOOKBACK_DAYS = 60
MAX_APPLICATIONS = 20_000
MAX_EVIDENCE_IDS = 60  # stored in the handoff package; the count is always exact
RECENT_FLAGS = 100


def _now() -> datetime:
    return datetime.now(UTC)


def _value(form: dict[str, Any], name: str) -> str | None:
    field = form.get(name)
    value = field.get("value") if isinstance(field, dict) else None
    return str(value) if value not in (None, "") else None


def load_records(db: Session, tenant_id: uuid.UUID, *, now: datetime) -> list[D.AppRecord]:
    """Submitted applications of the last 60 days as detector records (through RLS), identifiers fingerprinted."""
    scope = f"anomaly:{tenant_id}"
    since = now - timedelta(days=LOOKBACK_DAYS)
    rows = db.execute(
        select(
            models.Application.id,
            models.Application.person_id,
            models.Application.status,
            models.Application.form,
            models.Application.submitted_at,
            models.Application.created_at,
            models.Application.submitted_via,
            models.Application.created_by,
        )
        .where(models.Application.tenant_id == tenant_id, models.Application.status != "draft", models.Application.created_at >= since)
        .order_by(models.Application.created_at, models.Application.id)
        .limit(MAX_APPLICATIONS)
    ).all()
    households = dict(
        db.execute(
            select(models.HouseholdLink.person_id, models.HouseholdLink.household_key).where(models.HouseholdLink.tenant_id == tenant_id)
        ).all()
    )
    records = []
    for app_id, person_id, status, form, submitted_at, created_at, via, created_by in rows:
        form = form or {}
        payout, national_id = _value(form, "payout_account"), _value(form, "national_id")
        records.append(
            D.AppRecord(
                app_id=str(app_id),
                person_id=str(person_id),
                at=submitted_at or created_at,
                district=_value(form, "district"),
                payout=blind_index(payout, scope=scope) if payout else None,
                national_id=blind_index(national_id, scope=scope) if national_id else None,
                helper_id=str(created_by) if via == "helper" and created_by else None,
                household=f"hh:{households[person_id]}" if person_id in households else None,
                status=status,
            )
        )
    return records


# --- findings to cases -------------------------------------------------------------------------------------


def describe(finding: D.Finding) -> str:
    e = finding.evidence
    if finding.detector == "shared_payout":
        return (
            f"One payout account ({e.get('account')}) appears on {e.get('people')} people from {e.get('households')} households"
            f" in {e.get('districts') or 'unknown districts'}."
        )
    if finding.detector == "application_spike":
        return (
            f"{e.get('district')} had {e.get('applications')} applications on {e.get('day')}; its usual is about {e.get('usual_per_day')} a day"
            f" (robust z {e.get('robust_z')} over {e.get('baseline_days')} days)."
        )
    if finding.detector == "helper_burst":
        return f"One helper ({e.get('helper')}) submitted for {e.get('families')} families within {e.get('minutes')} minutes from {e.get('from')}."
    return (
        f"One ID number ({e.get('id')}) appears on {e.get('attempts')} applications by {e.get('people')} people; "
        f"{e.get('refused')} were refused or withdrawn."
    )


def _handoff(finding: D.Finding) -> HandoffPackage:
    conf = finding.confidence
    return HandoffPackage(
        question="Is this pattern a real problem or does it have an innocent explanation?",
        understanding=describe(finding),
        rule_fired=None,
        hypotheses=[Hypothesis(label="anomaly", probability=conf), Hypothesis(label="innocent_explanation", probability=round(1 - conf, 3))],
        suggested_question=finding.cheapest_check,
        guards=["anomaly_flag"],
        evidence={
            "detector": finding.detector,
            "pattern_key": finding.pattern_key,
            "title": finding.title,
            "summary_code": finding.summary_code,
            "chips": finding.evidence,
            "confidence": conf,
            "priority": finding.priority,
            "model_version": D.MODEL_VERSION,
            "evidence_count": len(finding.evidence_ids),
            "application_ids": finding.evidence_ids[:MAX_EVIDENCE_IDS],
        },
    )


def _existing(db: Session, tenant_id: uuid.UUID) -> tuple[list[ExistingCase], dict[str, models.Case]]:
    rows = db.scalars(
        select(models.Case)
        .where(models.Case.tenant_id == tenant_id, models.Case.kind == CASE_KIND)
        .order_by(models.Case.created_at.desc(), models.Case.id.desc())
        .limit(500)
    ).all()
    existing, cases = [], {}
    for case in rows:
        evidence = (case.handoff or {}).get("evidence") or {}
        key = evidence.get("pattern_key")
        if not key:
            continue
        existing.append(ExistingCase(str(case.id), key, case.status in ACTIVE, frozenset(evidence.get("application_ids") or [])))
        cases[str(case.id)] = case
    return existing, cases


def _refresh(db: Session, tenant_id: uuid.UUID, case: models.Case, action: Action, now: datetime) -> None:
    finding = action.finding
    package = _handoff(finding).model_dump(mode="json")
    package["evidence"]["application_ids"] = sorted(
        set((case.handoff or {}).get("evidence", {}).get("application_ids", [])) | set(finding.evidence_ids)
    )[:MAX_EVIDENCE_IDS]
    case.handoff = package
    case.confidence = finding.confidence
    case.priority = min(case.priority, finding.priority)
    db.add(
        models.CaseNote(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            case_id=case.id,
            author_user_id=None,
            author_kind="system",
            body=f"The pattern grew: {len(action.new_ids)} more application(s). {describe(finding)}",
            created_at=now,
        )
    )
    audit.write(
        db,
        tenant_id=tenant_id,
        action="anomaly.case_refreshed",
        actor_type="system",
        object_type="case",
        object_id=case.id,
        model_version=D.MODEL_VERSION,
        details={"detector": finding.detector, "pattern_key": finding.pattern_key, "added": len(action.new_ids)},
    )


def _status(result: D.DetectorResult) -> DetectorStatus:
    return DetectorStatus(
        detector=result.detector,
        title=D.TITLES[result.detector],
        status=result.status,
        flags=len(result.findings),
        abstained_reason=result.abstention.reasons[0] if result.abstention else None,
        data_points=result.data_points,
        params=result.params,
    )


def scan(db: Session, tenant_id: uuid.UUID, *, now: datetime | None = None, trigger: str = "job", actor_id: uuid.UUID | None = None) -> ScanSummary:
    """Detect, open or refresh cases, store the run and audit it. Idempotent: a second scan of the same data opens nothing new."""
    now = now or _now()
    records = load_records(db, tenant_id, now=now)
    results = D.run_all(records, today=now.date())
    findings = [f for r in results for f in r.findings]
    existing, cases = _existing(db, tenant_id)
    opened = refreshed = suppressed = 0
    for action in plan_cases(findings, existing):
        f = action.finding
        if action.kind == "open":
            open_case(
                db,
                tenant_id=tenant_id,
                kind=CASE_KIND,
                opened_reason=f"anomaly_{f.detector}",
                handoff=_handoff(f),
                confidence=f.confidence,
                priority=f.priority,
            )
            opened += 1
        elif action.kind == "refresh" and action.case_id in cases:
            _refresh(db, tenant_id, cases[action.case_id], action, now)
            refreshed += 1
        elif action.kind == "suppress":
            suppressed += 1
    statuses = [_status(r) for r in results]
    run = models.EvalRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        kind=SCAN_RUN_KIND,
        model_version=D.MODEL_VERSION,
        status="done",
        created_at=now,
        metrics={
            "ran_at": now.isoformat(),
            "trigger": trigger,
            "applications_scanned": len(records),
            "cases_opened": opened,
            "cases_refreshed": refreshed,
            "suppressed": suppressed,
            "detectors": [s.model_dump(mode="json") for s in statuses],
        },
        artifacts={},
    )
    db.add(run)
    db.flush()
    audit.write(
        db,
        tenant_id=tenant_id,
        action="anomaly.scan",
        actor_id=actor_id,
        actor_type="user" if actor_id else "system",
        object_type="eval_run",
        object_id=run.id,
        model_version=D.MODEL_VERSION,
        details={
            "trigger": trigger,
            "applications": len(records),
            "opened": opened,
            "refreshed": refreshed,
            "suppressed": suppressed,
            "flags": {s.detector: s.flags for s in statuses},
            "abstained": [s.detector for s in statuses if s.status == "abstained"],
        },
    )
    return _summary(run)


def _summary(run: models.EvalRun) -> ScanSummary:
    m = run.metrics or {}
    return ScanSummary(
        run_id=run.id,
        ran_at=m.get("ran_at") or paging.iso(run.created_at) or "",
        trigger=m.get("trigger", "job"),
        applications_scanned=int(m.get("applications_scanned", 0)),
        cases_opened=int(m.get("cases_opened", 0)),
        cases_refreshed=int(m.get("cases_refreshed", 0)),
        suppressed=int(m.get("suppressed", 0)),
        detectors=[DetectorStatus.model_validate(d) for d in m.get("detectors", [])],
    )


def _flag(case: models.Case) -> FlagOut | None:
    handoff = case.handoff or {}
    e = handoff.get("evidence") or {}
    if e.get("detector") not in D.DETECTORS:
        return None
    return FlagOut(
        case_id=case.id,
        case_status=case.status,
        detector=e["detector"],
        title=e.get("title") or D.TITLES[e["detector"]],
        pattern_key=e.get("pattern_key", ""),
        confidence=case.confidence,
        priority=case.priority,
        evidence=dict(e.get("chips") or {}),
        evidence_count=int(e.get("evidence_count") or len(e.get("application_ids") or [])),
        evidence_ids=list(e.get("application_ids") or [])[:MAX_EVIDENCE_IDS],
        cheapest_check=handoff.get("suggested_question"),
        resolution=case.resolution,
        created_at=paging.iso(case.created_at) or "",
    )


def overview(db: Session, tenant_id: uuid.UUID) -> AnomaliesOut:
    run = db.scalar(
        select(models.EvalRun)
        .where(models.EvalRun.tenant_id == tenant_id, models.EvalRun.kind == SCAN_RUN_KIND)
        .order_by(models.EvalRun.created_at.desc(), models.EvalRun.id.desc())
        .limit(1)
    )
    cases = db.scalars(
        select(models.Case)
        .where(models.Case.tenant_id == tenant_id, models.Case.kind == CASE_KIND)
        .order_by(models.Case.priority, models.Case.created_at.desc(), models.Case.id)
        .limit(RECENT_FLAGS)
    ).all()
    flags = [f for f in (_flag(c) for c in cases) if f is not None]
    counts = {name: 0 for name in D.DETECTORS}
    for f in flags:
        if f.case_status in ACTIVE:
            counts[f.detector] += 1
    note = (
        "Detection details are for staff only. A flag is a reason for a person to look, never a decision about anyone. "
        "Confidence is a heuristic score of the pattern, not a calibrated probability. Synthetic accuracy: docs/EVAL_REPORT.md."
    )
    return AnomaliesOut(last_scan=_summary(run) if run else None, flags=flags, counts=counts, note=note)


def enqueue_scan(db: Session, tenant_id: uuid.UUID, *, trigger: str = "manual") -> tuple[models.Job, bool]:
    """Queue one scan. An identical job still waiting is reused, so a burst of events or clicks makes one run."""
    from app.modules.jobs.service import enqueue

    waiting = db.scalar(
        select(models.Job)
        .where(models.Job.tenant_id == tenant_id, models.Job.kind == JOB_KIND, models.Job.status.in_(("queued", "running")))
        .limit(1)
    )
    if waiting is not None:
        return waiting, True
    return enqueue(db, tenant_id=tenant_id, kind=JOB_KIND, payload={"trigger": trigger}, priority=60, max_attempts=3), False


def anomaly_evidence_for(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID) -> AnomalyEvidence | None:
    """For the decision engine's `anomaly_flag` guard: set when an open anomaly case names this application. None when nothing is flagged."""
    target = str(application_id)
    rows = db.scalars(
        select(models.Case).where(models.Case.tenant_id == tenant_id, models.Case.kind == CASE_KIND, models.Case.status.in_(ACTIVE)).limit(500)
    ).all()
    hits = [c for c in rows if target in ((c.handoff or {}).get("evidence") or {}).get("application_ids", [])]
    if not hits:
        return None
    score = max((c.confidence or 0.0) for c in hits)
    return AnomalyEvidence(
        score=round(score, 3),
        flagged=True,
        reasons=sorted({f"anomaly_{(c.handoff or {}).get('evidence', {}).get('detector', 'pattern')}" for c in hits}),
    )
