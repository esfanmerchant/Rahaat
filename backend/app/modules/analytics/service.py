"""The impact report for one department: counted from its own rows.

Decisions, cases, payments, scam reports and duplicate candidates are department data and are read as the caller.
Submission times live on applications, which are person data behind consent: they are read in the `worker`
context (as background jobs do), so a person whose consent has ended is left out, and only the length of time
between two timestamps leaves this module, never a row.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import RlsContext, session_scope
from app.core.deps import Principal
from app.db import models
from app.modules.analytics import impact
from app.modules.analytics.schemas import Assumption, ImpactOut, ReplayOut
from app.modules.cases.rules import ACTIVE
from app.modules.decision.replay import stored_silent_guesses
from app.modules.scam.corpus import SCAM_LABELS

MAX_ROWS = 50_000
APPLICATION_KINDS = ("application_review", "document_review", "duplicate_review")
STOPPED_PAYMENTS = ("cancelled", "reversed")


def _now() -> datetime:
    return datetime.now(UTC)


def _submitted_times(tenant_id: uuid.UUID, since: datetime) -> dict[uuid.UUID, datetime]:
    with session_scope(RlsContext(role="worker", tenant_id=tenant_id)) as db:
        rows = db.execute(
            select(models.Application.id, models.Application.submitted_at)
            .where(models.Application.tenant_id == tenant_id, models.Application.submitted_at.is_not(None), models.Application.submitted_at >= since)
            .limit(MAX_ROWS)
        ).all()
    return {app_id: at for app_id, at in rows if at is not None}


def _replay(db: Session, principal: Principal) -> ReplayOut:
    label = "Synthetic: held-out labelled cases made by this repository. It says nothing about real accuracy."
    try:
        from app.modules.evals import service as eval_service
        from app.modules.evals.summary import _labelled

        current = eval_service.latest(db, principal)
        stats = _labelled(current.model_dump(mode="json"), run=db.get(models.EvalRun, current.run_id) if current.run_id else None)
    except Exception:  # noqa: BLE001  (a department without published rules still gets its live numbers)
        return ReplayOut(label=label + " No replay is available for this department yet.")
    return ReplayOut(
        label=label,
        cases=stats.cases,
        accuracy_of_automatic=stats.accuracy_of_automatic,
        false_approvals=stats.false_approvals,
        false_rejections=stats.false_rejections,
        unnecessary_handoffs=stats.unnecessary_handoffs,
        abstention_rate=stats.abstention_rate,
        cost_per_case=stats.cost_per_case,
        all_human_cost_per_case=stats.all_human_cost_per_case,
        ece=stats.ece,
        stored_run=stats.stored,
    )


def compute(db: Session, principal: Principal, *, days: int, assumed_minutes: float, now: datetime | None = None) -> ImpactOut:
    now = now or _now()
    tenant_id = principal.tenant_id
    since = now - timedelta(days=days)
    tenant = db.get(models.Tenant, tenant_id)

    decisions = list(
        db.scalars(
            select(models.Decision)
            .where(models.Decision.tenant_id == tenant_id, models.Decision.superseded_by.is_(None), models.Decision.created_at >= since)
            .order_by(models.Decision.created_at, models.Decision.id)
            .limit(MAX_ROWS)
        ).all()
    )
    versions = {v.id: dict(v.dsl or {}) for v in db.scalars(select(models.RuleVersion).where(models.RuleVersion.tenant_id == tenant_id)).all()}
    mix = impact.route_mix(d.route for d in decisions)
    silent = sum(1 for d in decisions if stored_silent_guesses(d, versions.get(d.rule_version_id)))

    submitted = _submitted_times(tenant_id, since)
    auto_seconds = [
        (d.created_at - submitted[d.application_id]).total_seconds() for d in decisions if d.route == "auto" and d.application_id in submitted
    ]
    latencies = [float(d.latency_ms) for d in decisions if d.route == "auto" and d.latency_ms is not None]

    cases = db.execute(
        select(models.Case.kind, models.Case.status, models.Case.created_at, models.Case.resolved_at)
        .where(models.Case.tenant_id == tenant_id, models.Case.created_at >= since)
        .limit(MAX_ROWS)
    ).all()
    by_kind: dict[str, list[float]] = defaultdict(list)
    anomaly = {"total": 0, "active": 0, "confirmed": 0, "dismissed": 0}
    for kind, status, created, resolved in cases:
        if resolved is not None:
            by_kind[kind].append((resolved - created).total_seconds())
        if kind == "anomaly_review":
            anomaly["total"] += 1
            anomaly["active"] += status in ACTIVE
    for resolution in db.scalars(
        select(models.Case.resolution).where(
            models.Case.tenant_id == tenant_id,
            models.Case.kind == "anomaly_review",
            models.Case.resolution.is_not(None),
            models.Case.created_at >= since,
        )
    ).all():
        anomaly["confirmed" if resolution == "rejected" else "dismissed"] += (
            1  # a person's "reject" confirms the concern; "approve" finds it innocent
        )
    case_seconds = [s for kind in APPLICATION_KINDS for s in by_kind.get(kind, [])]
    review_seconds = list(
        db.scalars(
            select(models.HumanReview.review_seconds).where(
                models.HumanReview.tenant_id == tenant_id, models.HumanReview.created_at >= since, models.HumanReview.review_seconds.is_not(None)
            )
        ).all()
    )
    auto = impact.durations(auto_seconds)
    human_case = impact.durations(case_seconds)
    hands_on = impact.durations(review_seconds)

    payments = db.execute(
        select(models.Payment.status, models.Payment.amount_pkr).where(models.Payment.tenant_id == tenant_id, models.Payment.created_at >= since)
    ).all()
    by_status: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "amount_pkr": 0})
    for status, amount in payments:
        by_status[status]["count"] += 1
        by_status[status]["amount_pkr"] += int(amount)
    total_pkr = sum(int(a) for _, a in payments)

    scams = list(
        db.execute(
            select(models.ScamReport.label, models.ScamReport.confirmed_label).where(
                models.ScamReport.tenant_id == tenant_id, models.ScamReport.created_at >= since
            )
        ).all()
    )
    candidates = list(
        db.execute(
            select(models.DuplicateCandidate.band, models.DuplicateCandidate.status).where(
                models.DuplicateCandidate.tenant_id == tenant_id, models.DuplicateCandidate.created_at >= since
            )
        ).all()
    )
    guards = impact.guard_counts(d.guards or [] for d in decisions)
    stopped = [int(a) for s, a in payments if s in STOPPED_PAYMENTS]

    fraud = {
        "forged_cards_flagged": guards["forged_cards_flagged"],
        "identity_mismatches": guards["identity_mismatches"],
        "duplicates_caught": guards["duplicates_caught"],
        "duplicate_candidates": sum(1 for band, _ in candidates if band in ("same", "possible")),
        "duplicates_linked_by_a_person": sum(1 for _, status in candidates if status == "linked"),
        "scams_flagged": sum(1 for label, _ in scams if label in SCAM_LABELS),
        "scams_confirmed_by_a_person": sum(1 for _, confirmed in scams if confirmed in SCAM_LABELS),
        "anomaly_cases": anomaly,
        "payments_stopped": len(stopped),
        "payments_stopped_pkr": sum(stopped),
        "held_for_a_person_by_a_guard": guards["held_for_a_person_by_a_guard"],
    }
    cost = impact.expected_cost((d.outcome, dict(d.expected_costs or {}), dict(d.cost_matrix or {})) for d in decisions)
    saved = impact.time_saved(
        automatic_decisions=mix["by_route"]["auto"],
        median_review_seconds=hands_on["median_seconds"],
        median_case_seconds=human_case["median_seconds"],
        median_automatic_seconds=auto["median_seconds"],
        assumed_minutes_per_manual_review=assumed_minutes,
    )
    p50 = impact.percentile(latencies, 50)
    assumptions = [
        Assumption(
            name="assumed_minutes_per_manual_review",
            value=assumed_minutes,
            unit="minutes",
            used_for="Hands-on time saved, only until officer review times have been measured",
        ),
        Assumption(
            name="assumed_pkr_per_cost_unit",
            value=impact.ASSUMED_PKR_PER_COST_UNIT,
            unit="PKR per cost unit",
            used_for="Showing the cost matrix's units as rupees (the contract documents 1 unit as about Rs 120)",
        ),
    ]
    notes = [
        "Counts and durations come from this department's rows in the window. Nothing here is projected to a larger population.",
        "Cost per claim is an expectation under the cost matrix stored with each decision, not money spent.",
        "Time saved is a counterfactual: automatic decisions times measured human times, as if a person had handled each one like today's cases.",
        "Forged cards, duplicates and scams are 'flagged' counts. A flag is a reason for a person to look; it is not proof of fraud.",
    ]
    return ImpactOut.model_validate(
        {
            "generated_at": now.isoformat(),
            "window_days": days,
            "department": tenant.name if tenant else "",
            "handoff": {**mix, "silent_guesses": silent},
            "time_to_decision": {
                "automatic": auto,
                "automatic_engine_latency_ms_p50": p50,
                "human_case": human_case,
                "human_review_hands_on": hands_on,
                "human_case_by_kind": {k: impact.durations(v) for k, v in sorted(by_kind.items())},
            },
            "fraud_stopped": fraud,
            "cost_per_claim": cost,
            "payments": {
                "count": len(payments),
                "amount_pkr": total_pkr,
                "by_status": dict(by_status),
                "settled_pkr": by_status["settled"]["amount_pkr"] if "settled" in by_status else 0,
                "average_pkr": round(total_pkr / len(payments), 1) if payments else None,
            },
            "time_saved": saved,
            "replay": _replay(db, principal).model_dump(),
            "assumptions": [a.model_dump() for a in assumptions],
            "measured_from": {
                "decisions": len(decisions),
                "applications_with_a_submission_time": len(submitted),
                "cases": len(cases),
                "timed_officer_reviews": len(review_seconds),
                "payments": len(payments),
                "scam_reports": len(scams),
            },
            "notes": notes,
        }
    )
