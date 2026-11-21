"""Admin view and control of the mock services' failure injection. Demo and dev only; absent in prod."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.contracts.common import Strict
from app.core import audit
from app.core.config import get_settings
from app.core.deps import Principal, get_db
from app.core.errors import NotFound
from app.core.policy import Policy
from app.modules.integrations import service
from app.modules.integrations.settings import get_integration_settings

router = APIRouter(prefix="/v1/admin/mocks", tags=["admin: mock services"])
_read = Policy("mocks:read", ["admin"], description="See the simulated services' failure controls and breakers")
_control = Policy("mocks:control", ["admin"], description="Make a simulated service slow, flaky or down (audited)")

ServiceName = Literal["identity", "registry", "payment", "sms"]


class ServiceOut(BaseModel):
    latency_ms: int
    failure_rate: float
    down: bool
    calls: int
    failures_injected: int
    breaker: dict[str, Any]


class MocksOut(BaseModel):
    transport: str
    services: dict[str, ServiceOut]
    label: str = Field(description="Every one of these services is simulated")


class MockControlIn(Strict):
    service: ServiceName | None = Field(default=None, description="Which service to change; omit with reset")
    latency_ms: int | None = Field(default=None, ge=0, le=15_000)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    down: bool | None = None
    reset: bool = Field(default=False, description="Clear every control and close every breaker")
    reason: str = Field(min_length=5, max_length=500, description="Stored in the audit log")

    @model_validator(mode="after")
    def _something_to_do(self) -> MockControlIn:
        if self.reset:
            return self
        if self.service is None or (self.latency_ms is None and self.failure_rate is None and self.down is None):
            raise ValueError("name a service and at least one of latency_ms, failure_rate or down, or set reset")
        return self


class SmsOutboxItem(BaseModel):
    message_id: str
    to: str = Field(description="Masked")
    sender: str
    body: str
    status: str
    at: str


def _demo_only() -> None:
    if not get_settings().demo_mode:
        raise NotFound()


def _view(body: dict[str, Any]) -> MocksOut:
    breakers = service.breaker_snapshots()
    services = {name: ServiceOut(**values, breaker=breakers.get(name, {})) for name, values in body.get("services", {}).items()}
    return MocksOut(transport=get_integration_settings().transport_effective(), services=services, label=str(body.get("label", "")))


@router.get("", response_model=MocksOut, summary="Failure controls and circuit breakers of the simulated services")
def get_mocks(_: Principal = Depends(_read)) -> MocksOut:
    _demo_only()
    return _view(service.mock_controls())


@router.post("", response_model=MocksOut, summary="Make a simulated service slow, flaky or down, or reset all")
def control_mocks(body: MockControlIn, principal: Principal = Depends(_control), db: Session = Depends(get_db)) -> MocksOut:
    _demo_only()
    if body.reset:
        result = service.reset_mock_controls()
    else:
        assert body.service is not None
        result = service.set_mock_control(body.service, latency_ms=body.latency_ms, failure_rate=body.failure_rate, down=body.down)
    audit.write(
        db, tenant_id=principal.tenant_id, action="mocks.control_changed", actor_id=principal.user_id, actor_role=principal.role,
        object_type="mock_service", object_id=body.service or "all", reason=body.reason,
        details=body.model_dump(exclude={"reason"}),
    )  # fmt: skip
    db.commit()
    return _view(result)


@router.get("/sms", response_model=list[SmsOutboxItem], summary="What the mock SMS gateway delivered (numbers masked)")
def mock_sms(_: Principal = Depends(_read), limit: int = Query(50, ge=1, le=200)) -> list[SmsOutboxItem]:
    _demo_only()
    return [SmsOutboxItem(**{k: str(v) for k, v in item.items() if k in SmsOutboxItem.model_fields}) for item in service.mock_sms_outbox(limit)]
