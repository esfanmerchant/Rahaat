"""DB-free checks of the shared contracts and of the endpoint-to-role registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import ApplicationFormV1, CostMatrix, FieldValue, TypedDecision, apply_patch
from app.core.policy import Policy, describe_routes, undeclared_routes


def test_default_cost_matrix_gives_the_documented_thresholds() -> None:
    costs = CostMatrix()
    # Approve alone only when the expected loss is below the cost of a human look: (1 - p) * 100 <= 3.2
    assert costs.human_cost(queue_days=1) == pytest.approx(3.2)
    assert costs.approve_threshold() == pytest.approx(0.968)
    assert costs.reject_threshold() == pytest.approx(1 - 3.2 / 30)


def test_thresholds_move_when_an_admin_changes_the_costs() -> None:
    cautious = CostMatrix(wrong_approve=400)
    assert cautious.approve_threshold() > CostMatrix().approve_threshold()
    busy_queue = CostMatrix().approve_threshold(queue_days=5)
    assert busy_queue < CostMatrix().approve_threshold(), "a long human queue makes waiting dearer"


def test_a_component_that_abstains_cannot_act_alone() -> None:
    with pytest.raises(ValidationError):
        TypedDecision[str](choice=None, confidence=0.4, route="auto", model_version="m", abstained=True)
    with pytest.raises(ValidationError):
        TypedDecision[str](choice=None, confidence=0.4, route="human", model_version="m", abstained=False)
    unsure = TypedDecision[str](choice=None, confidence=0.4, route="human", model_version="m", abstained=True)
    assert unsure.choice is None


def test_only_trusted_sources_can_mark_a_field_verified() -> None:
    with pytest.raises(ValidationError):
        FieldValue[str](value="x", confidence=0.9, provenance="spoken", verified=True)
    assert FieldValue[str](value="x", confidence=0.9, provenance="qr_signed", verified=True).verified
    assert FieldValue[str](value=None, confidence=0.9, provenance="typed").confidence == 0.0, "unknown has no confidence"


def test_form_reports_only_what_is_still_missing() -> None:
    form = ApplicationFormV1()
    assert form.missing(["full_name", "household_size"]) == ["full_name", "household_size"]
    form = apply_patch(form, {"household_size": {"value": 5, "confidence": 0.8, "provenance": "spoken"}})
    assert form.missing(["full_name", "household_size"]) == ["full_name"]
    with pytest.raises(ValueError, match="unknown form fields"):
        apply_patch(form, {"is_admin": {"value": True}})


def test_every_route_declares_who_may_call_it() -> None:
    from app.main import create_app

    app = create_app()
    registry = describe_routes(app)
    assert len(registry) >= 15, "routes from included routers must be visible to the registry"
    assert undeclared_routes(app) == [], "every endpoint needs a Policy(...) or Public(...) marker"
    by_route = {(e["method"], e["path"]): e for e in registry}
    assert by_route[("POST", "/v1/auth/login")]["public"] is True
    assert by_route[("GET", "/v1/audit")]["roles"] == ["auditor", "admin"]
    assert "citizen" not in by_route[("GET", "/v1/system/policies")]["roles"]


def test_a_route_without_a_policy_is_caught() -> None:
    from fastapi import APIRouter, FastAPI

    router = APIRouter()

    @router.get("/v1/forgot-the-policy")
    def forgot() -> dict[str, str]:
        return {}

    app = FastAPI()
    app.include_router(router)
    assert undeclared_routes(app) == ["GET /v1/forgot-the-policy"]


def test_policies_reject_unknown_roles() -> None:
    with pytest.raises(ValueError, match="unknown roles"):
        Policy("x", ["superuser"])
