"""Evaluation API: the cost of being wrong (B7), stored eval runs, the evaluation summary (B13), the cost matrix.

    GET  /v1/evals/decisions/latest       the department's threshold analysis (newest stored run, or fresh)
    POST /v1/evals/decisions/what-if      curves and thresholds for other costs; nothing is saved (a slider)
    POST /v1/evals/decisions/runs         run the analysis and store it in eval_runs
    GET  /v1/evals/runs                   stored runs, newest first
    GET  /v1/evals/summary                accuracy, mistakes, abstention, silent guesses, latency, cost (B13)
    GET  /v1/evals/names                  dedupe bands on the labelled messy fixtures (B8)
    GET  /v1/cost-matrix                  the department's costs and the thresholds they give
    PUT  /v1/cost-matrix                  change the costs (admin, audited); the next decision uses them
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.evals import service
from app.modules.evals.schemas import CostMatrixIn, CostMatrixOut, CostMatrixSave, DecisionAnalysisOut, EvalRunList, RunIn

router = APIRouter(tags=["evals"])
_read = Policy("evals:read", ["admin", "auditor"], description="Threshold analysis, eval runs and the evaluation summary")
_run = Policy("evals:run", ["admin"], description="Run and store an evaluation")
_costs_read = Policy("costs:read", ["admin", "auditor", "officer"], description="The department's cost matrix and thresholds")
_costs_write = Policy("costs:write", ["admin"], description="Change the department's cost matrix (audited)")


@router.get("/v1/evals/decisions/latest", response_model=DecisionAnalysisOut, summary="Threshold analysis on 1,000+ held-out labelled cases")
def latest(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> DecisionAnalysisOut:
    return service.latest(db, principal)


@router.post("/v1/evals/decisions/what-if", response_model=DecisionAnalysisOut, summary="What these costs would do; nothing is saved")
def what_if(body: CostMatrixIn, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> DecisionAnalysisOut:
    return service.what_if(db, principal, body.matrix())


@router.post("/v1/evals/decisions/runs", response_model=DecisionAnalysisOut, status_code=201, summary="Run the analysis and store it")
def run(body: RunIn | None = None, principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> DecisionAnalysisOut:
    out = service.run_and_store(db, principal, note=body.note if body else None)
    db.commit()
    return out


@router.get("/v1/evals/runs", response_model=EvalRunList, summary="Stored evaluation runs, newest first")
def list_runs(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    kind: str | None = Query(None, max_length=32, description="decision | names | ..."),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=120),
) -> EvalRunList:
    return service.list_runs(db, principal, kind=kind, limit=limit, before=cursor)


@router.get("/v1/evals/names", summary="Dedupe bands measured on 200+ labelled messy record pairs")
def names(principal: Principal = Depends(_read)) -> dict[str, Any]:
    from app.modules.matching.service import fixture_report

    return fixture_report()


@router.get("/v1/cost-matrix", response_model=CostMatrixOut, summary="The department's costs and the thresholds they give")
def get_cost_matrix(principal: Principal = Depends(_costs_read), db: Session = Depends(get_db)) -> CostMatrixOut:
    return service.get_cost_matrix(db, principal)


@router.put("/v1/cost-matrix", response_model=CostMatrixOut, summary="Change the costs (audited); the next decision uses them")
def put_cost_matrix(body: CostMatrixSave, principal: Principal = Depends(_costs_write), db: Session = Depends(get_db)) -> CostMatrixOut:
    out = service.save_cost_matrix(db, principal, CostMatrixIn.model_validate(body.model_dump(exclude={"reason"})).matrix(), body.reason)
    db.commit()
    return out
