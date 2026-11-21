"""The evaluation summary (B13): one answer for the eval dashboard, per rule version.

Live decisions have no ground truth, so for them the summary reports what can be measured honestly: the
route mix, abstention, guards, engine fallbacks, the silent-guess invariant rechecked on every stored
automatic decision, engine latency (p50, p95), expected cost per decision, and how often officers went
against the engine's lean. Accuracy, false approvals and false rejections come from the latest stored
evaluation runs on held-out labelled cases.
"""

from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import Principal
from app.db import models
from app.modules.decision.replay import OUTCOME_ACTION, stored_silent_guesses
from app.modules.evals import service as eval_service

LIVE_LIMIT = 20_000


class LiveStats(BaseModel):
    rule_version_id: uuid.UUID | None = None
    rule_version_no: int | None = None
    decisions: int
    routes: dict[str, int]
    outcomes: dict[str, int]
    auto_rate: float
    abstention_rate: float = Field(description="Share not decided automatically (asked for proof or sent to a person)")
    silent_guesses: int = Field(description="Automatic decisions that break the invariant, rechecked from the stored rows; must be 0")
    engine_fallbacks: int = Field(description="Decisions where the engine refused to guess (invariant fallback or invalid rules)")
    guards: dict[str, int]
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    expected_cost_per_decision: float | None = None
    officer_reviews: int
    officer_overrides: int
    override_rate: float | None = None


class LabelledStats(BaseModel):
    run_id: uuid.UUID | None = None
    stored: bool
    created_at: str | None = None
    rule_version_id: uuid.UUID | None = None
    rule_version_no: int | None = None
    model_version: str | None = None
    cases: int
    accuracy_of_automatic: float | None = Field(default=None, description="Right automatic answers / automatic answers")
    false_approvals: int
    false_approve_rate: float
    false_rejections: int
    false_reject_rate: float
    abstention_rate: float
    unnecessary_handoffs: int
    not_automatic_although_ok: int
    cost_per_case: float
    all_human_cost_per_case: float
    ece: float | None = None
    roc_auc: float | None = None
    silent_guesses: int = 0


class NamesStats(BaseModel):
    fixtures: int
    kinds: int
    wrong_links: int
    duplicates_caught_recall: float | None
    bands: dict[str, dict[str, Any]]


class EvalSummaryOut(BaseModel):
    generated_at: str
    live_overall: LiveStats
    live_by_rule_version: list[LiveStats]
    labelled: LabelledStats | None = Field(description="The analysis for the active rules and costs (stored run, or fresh)")
    labelled_by_rule_version: list[LabelledStats] = Field(description="The latest stored run of each rule version")
    names: NamesStats
    silent_guesses_total: int
    notes: list[str]


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _live(rows: Sequence[models.Decision], dsl_by_version: dict[uuid.UUID, dict[str, Any]], reviews: dict[uuid.UUID, tuple[int, int]],
          version_id: uuid.UUID | None, version_no: int | None) -> LiveStats:  # fmt: skip
    n = len(rows)
    routes = Counter(r.route for r in rows)
    outcomes = Counter(r.outcome for r in rows)
    guards = Counter(g for r in rows for g in (r.guards or []))
    silent = sum(1 for r in rows if stored_silent_guesses(r, dsl_by_version.get(r.rule_version_id)))
    fallbacks = sum(1 for r in rows if "invariant_fallback" in (r.reasons or []) or "rules_invalid" in (r.guards or []))
    latencies = [float(r.latency_ms) for r in rows if r.latency_ms is not None]
    costs = [float((r.expected_costs or {}).get(OUTCOME_ACTION.get(r.outcome, ""), math.nan)) for r in rows]
    costs = [c for c in costs if not math.isnan(c)]
    reviewed = sum(reviews.get(r.id, (0, 0))[0] for r in rows)
    overridden = sum(reviews.get(r.id, (0, 0))[1] for r in rows)
    return LiveStats(
        rule_version_id=version_id, rule_version_no=version_no, decisions=n, routes={k: routes[k] for k in ("auto", "ask_more", "human")},
        outcomes={k: outcomes[k] for k in ("approved", "rejected", "needs_proof", "needs_human")},
        auto_rate=round(routes["auto"] / n, 4) if n else 0.0, abstention_rate=round((n - routes["auto"]) / n, 4) if n else 0.0,
        silent_guesses=silent, engine_fallbacks=fallbacks, guards=dict(guards.most_common()),
        latency_ms_p50=percentile(latencies, 50), latency_ms_p95=percentile(latencies, 95),
        expected_cost_per_decision=round(sum(costs) / len(costs), 4) if costs else None, officer_reviews=reviewed,
        officer_overrides=overridden, override_rate=round(overridden / reviewed, 4) if reviewed else None,
    )  # fmt: skip


def _labelled(report: dict[str, Any], *, run: models.EvalRun | None) -> LabelledStats:
    point = report.get("operating_point") or {}
    automatic = int(point.get("approved", 0)) + int(point.get("rejected", 0))
    wrong = int(point.get("false_approvals", 0)) + int(point.get("false_rejections", 0))
    reliability = report.get("reliability") or {}
    n = int(point.get("n", 0))
    return LabelledStats(
        run_id=run.id if run else None, stored=run is not None, created_at=run.created_at.astimezone(UTC).isoformat() if run else None,
        rule_version_id=report.get("rule_version_id"), rule_version_no=report.get("rule_version_no"), model_version=report.get("model_version"),
        cases=n, accuracy_of_automatic=round((automatic - wrong) / automatic, 4) if automatic else None,
        false_approvals=int(point.get("false_approvals", 0)), false_approve_rate=float(point.get("false_approve_rate", 0.0)),
        false_rejections=int(point.get("false_rejections", 0)), false_reject_rate=float(point.get("false_reject_rate", 0.0)),
        abstention_rate=round(1 - float(point.get("auto_rate", 0.0)), 4), unnecessary_handoffs=int(point.get("unnecessary_handoffs", 0)),
        not_automatic_although_ok=int(point.get("not_automatic_although_ok", 0)), cost_per_case=float(point.get("cost_per_case", 0.0)),
        all_human_cost_per_case=float(point.get("all_human_cost_per_case", 0.0)), ece=reliability.get("ece"), roc_auc=report.get("roc_auc"),
        silent_guesses=int(point.get("silent_guesses", 0)),
    )  # fmt: skip


def summary(db: Session, principal: Principal) -> EvalSummaryOut:
    tenant_id = principal.tenant_id
    rows = list(db.scalars(
        select(models.Decision).where(models.Decision.tenant_id == tenant_id)
        .order_by(models.Decision.created_at.desc(), models.Decision.id.desc()).limit(LIVE_LIMIT)
    ).all())  # fmt: skip
    version_ids = {r.rule_version_id for r in rows}
    versions = {v.id: v for v in db.scalars(select(models.RuleVersion).where(models.RuleVersion.tenant_id == tenant_id)).all()}
    dsl_by_version = {vid: dict(versions[vid].dsl or {}) for vid in version_ids if vid in versions}
    reviews: dict[uuid.UUID, tuple[int, int]] = {}
    review_rows = db.execute(
        select(models.HumanReview.decision_id, models.HumanReview.overrode_ai).where(models.HumanReview.tenant_id == tenant_id,
                                                                                      models.HumanReview.decision_id.is_not(None))  # fmt: skip
    ).all()
    for decision_id, overrode in review_rows:
        if decision_id is None:
            continue
        count, over = reviews.get(decision_id, (0, 0))
        reviews[decision_id] = (count + 1, over + int(bool(overrode)))
    grouped: dict[uuid.UUID, list[models.Decision]] = defaultdict(list)
    for row in rows:
        grouped[row.rule_version_id].append(row)
    by_version = [_live(items, dsl_by_version, reviews, vid, versions[vid].version_no if vid in versions else None)
                  for vid, items in sorted(grouped.items(), key=lambda kv: versions[kv[0]].version_no if kv[0] in versions else 0)]  # fmt: skip
    overall = _live(rows, dsl_by_version, reviews, None, None)

    labelled: LabelledStats | None = None
    notes: list[str] = []
    try:
        current = eval_service.latest(db, principal)
        labelled = _labelled(current.model_dump(mode="json"), run=db.get(models.EvalRun, current.run_id) if current.run_id else None)
    except Exception as exc:  # noqa: BLE001  (no published rules yet: the dashboard still shows live numbers)
        notes.append(f"No labelled analysis: {type(exc).__name__}")
    latest_per_version: dict[uuid.UUID | None, models.EvalRun] = {}
    for run in db.scalars(select(models.EvalRun).where(models.EvalRun.tenant_id == tenant_id, models.EvalRun.kind == eval_service.KIND)
                          .order_by(models.EvalRun.created_at.desc(), models.EvalRun.id.desc()).limit(200)).all():  # fmt: skip
        latest_per_version.setdefault(run.rule_version_id, run)
    labelled_by_version = [_labelled(eval_service._report_of(run), run=run) for run in latest_per_version.values()]

    from app.modules.matching.service import fixture_report

    names = fixture_report()
    names_stats = NamesStats(fixtures=names["fixtures"], kinds=names["kinds"], wrong_links=names["wrong_links"],
                             duplicates_caught_recall=names["duplicates_caught"]["recall"], bands=names["bands"])  # fmt: skip
    silent_total = overall.silent_guesses + (labelled.silent_guesses if labelled else 0) + sum(s.silent_guesses for s in labelled_by_version)
    notes.append("Live decisions have no ground truth; accuracy and mistakes come from held-out labelled cases.")
    return EvalSummaryOut(generated_at=datetime.now(UTC).isoformat(), live_overall=overall, live_by_rule_version=by_version,
                          labelled=labelled, labelled_by_rule_version=labelled_by_version, names=names_stats,
                          silent_guesses_total=silent_total, notes=notes)  # fmt: skip
