"""The mock services as one ASGI app: `uvicorn app.mocks.main:app --port 9001`.

Simulated identity verification, registry lookup, payment rail and SMS gateway. Each service checks its own
API key (`X-Mock-Key`). The control endpoints (their own key) set latency, failure rate and "down" per
service, so the platform's timeouts, retries and circuit breakers can be shown working. In dev and test
the platform calls this app in process; deployed, it listens on an internal port only.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.mockdata import normalise_mock_phone
from app.mocks import identity as identity_rules
from app.mocks import registry
from app.mocks.config import SERVICES, get_mock_service_settings
from app.mocks.receiver import RECEIVER
from app.mocks.receiver import router as receiver_router
from app.mocks.state import STATE

LABEL = "Simulated service for the Rahat prototype. Not a real identity, registry, payment or SMS system."

app = FastAPI(title="Rahat mock services (simulated)", description=LABEL, version="1", docs_url="/docs", redoc_url=None)

app.include_router(receiver_router)

ServiceName = Literal["identity", "registry", "payment", "sms"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Rejected(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@app.exception_handler(_Rejected)
async def _rejected(_: Any, exc: _Rejected) -> JSONResponse:
    return JSONResponse({"code": exc.code, "detail": exc.detail}, status_code=exc.status)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_key(service: str, presented: str | None) -> None:
    expected = get_mock_service_settings().key_for(service)
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise _Rejected(401, "bad_key", f"missing or wrong API key for the {service} service")


def _guard(service: str) -> Any:
    async def dependency(x_mock_key: str | None = Header(default=None)) -> None:
        fail, latency_ms = STATE.draw_failure(service)
        if latency_ms:
            await asyncio.sleep(min(latency_ms, get_mock_service_settings().max_latency_ms) / 1000)
        if fail:
            raise _Rejected(503, "service_unavailable", f"the mock {service} service is not available (failure injection)")
        _check_key(service, x_mock_key)

    return Depends(dependency)


def _control_key(x_mock_key: str | None = Header(default=None)) -> None:
    _check_key("control", x_mock_key)


# --- identity -------------------------------------------------------------------------------------------


class IdentityIn(_In):
    national_id: str = Field(max_length=20)
    full_name: str | None = Field(default=None, max_length=200)
    dob: str | None = Field(default=None, max_length=10)


@app.post("/identity/verify", dependencies=[_guard("identity")])
def verify_identity(body: IdentityIn) -> dict[str, Any]:
    record = registry.find(body.national_id, STATE.registry_overrides)
    if record is None:
        raise _Rejected(404, "not_found", "no identity record for this ID")
    status, score = identity_rules.match(record, body.full_name, body.dob)
    return {"status": status, "name_score": score, "checked_at": _now(), "record_version": record.record_version}


# --- registry -------------------------------------------------------------------------------------------


@app.get("/registry/persons/{national_id}", dependencies=[_guard("registry")])
def lookup_registry(national_id: str) -> dict[str, Any]:
    record = registry.find(national_id[:20], STATE.registry_overrides)
    if record is None:
        raise _Rejected(404, "not_found", "no registry record for this ID")
    return record.registry_view()


# --- payment rail ---------------------------------------------------------------------------------------


class PaymentIn(_In):
    idempotency_key: str = Field(min_length=8, max_length=80)
    amount_pkr: int = Field(gt=0, le=1_000_000)
    account_ref: str = Field(min_length=1, max_length=64)
    reference: str = Field(default="", max_length=80)


@app.post("/payments", dependencies=[_guard("payment")])
def create_payment(body: PaymentIn) -> dict[str, Any]:
    with STATE.lock:
        existing = STATE.payments.get(body.idempotency_key)
        if existing is not None:
            if existing["amount_pkr"] != body.amount_pkr:
                raise _Rejected(409, "idempotency_conflict", "this idempotency key was already used for a different amount")
            return {**existing, "replayed": True}
        record = {
            "rail_ref": f"MR-{secrets.token_hex(5).upper()}", "idempotency_key": body.idempotency_key,
            "amount_pkr": body.amount_pkr, "settled_pkr": body.amount_pkr, "status": "settled",
            "account_ref": body.account_ref[-4:], "reference": body.reference, "settled_at": _now(),
        }  # fmt: skip
        STATE.payments[body.idempotency_key] = record
        return {**record, "replayed": False}


@app.get("/payments/{rail_ref}", dependencies=[_guard("payment")])
def get_payment(rail_ref: str) -> dict[str, Any]:
    for record in list(STATE.payments.values()):
        if record["rail_ref"] == rail_ref:
            return record
    raise _Rejected(404, "not_found", "no payment with this reference")


# --- SMS gateway ----------------------------------------------------------------------------------------


class SmsIn(_In):
    to: str = Field(max_length=20)
    body: str = Field(min_length=1, max_length=480)
    sender: str = Field(default="RAHAT", max_length=16)


@app.post("/sms/messages", dependencies=[_guard("sms")])
def send_sms(body: SmsIn) -> dict[str, Any]:
    to = normalise_mock_phone(body.to)
    if to is None:
        raise _Rejected(422, "not_a_mock_number", "this gateway delivers to mock numbers (0999-NNNNNNN) only")
    message = {"message_id": f"SMS-{secrets.token_hex(5).upper()}", "to": to, "sender": body.sender, "body": body.body,
               "status": "delivered", "at": _now()}  # fmt: skip
    STATE.sms_outbox.appendleft(message)
    return message


@app.get("/sms/outbox", dependencies=[_guard("sms")])
def sms_outbox(limit: int = Query(50, ge=1, le=500), to: str | None = Query(None, max_length=20)) -> dict[str, Any]:
    wanted = normalise_mock_phone(to) if to else None
    items = [m for m in list(STATE.sms_outbox) if wanted is None or m["to"] == wanted]
    return {"items": items[:limit]}


# --- control --------------------------------------------------------------------------------------------


class ControlIn(_In):
    latency_ms: int | None = Field(default=None, ge=0, le=15_000)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    down: bool | None = None


def _controls() -> dict[str, Any]:
    return {"services": {name: STATE.controls[name].public() for name in SERVICES}, "label": LABEL}


@app.get("/control", dependencies=[Depends(_control_key)])
def get_controls() -> dict[str, Any]:
    return _controls()


@app.post("/control/reset", dependencies=[Depends(_control_key)])
def reset_controls(everything: bool = Query(False, description="Also clear the ledger, the outbox and registry overrides")) -> dict[str, Any]:
    if everything:
        STATE.reset_all()
        RECEIVER.reset()
    else:
        STATE.reset_controls()
    return _controls()


@app.post("/control/{service}", dependencies=[Depends(_control_key)])
def set_control(service: ServiceName, body: ControlIn) -> dict[str, Any]:
    STATE.set_control(service, latency_ms=body.latency_ms, failure_rate=body.failure_rate, down=body.down)
    return _controls()


class RegistryOverrideIn(_In):
    full_name: str | None = Field(default=None, max_length=200)
    dob: str | None = Field(default=None, max_length=10)
    household_size: int | None = Field(default=None, ge=1, le=30)
    verified_income_pkr: int | None = Field(default=None, ge=0, le=10_000_000)
    clear_income: bool = False
    income_as_of: str | None = Field(default=None, max_length=10)
    receives_other_aid: bool | None = None
    is_widow: bool | None = None
    has_disability: bool | None = None


@app.put("/control/registry/{national_id}", dependencies=[Depends(_control_key)])
def override_registry(national_id: str, body: RegistryOverrideIn) -> dict[str, Any]:
    """Change one registry record for a scenario (for example a stale income). Lives until reset."""
    base = registry.find(national_id[:20])
    if base is None:
        raise _Rejected(404, "not_found", "not a valid mock ID")
    changes = body.model_dump(exclude_none=True, exclude={"clear_income"})
    if body.clear_income:
        changes.update(verified_income_pkr=None, income_as_of=None)
    record = registry.with_changes(base, changes)
    STATE.registry_overrides[record.national_id] = record
    return record.registry_view()


@app.delete("/control/registry/{national_id}", dependencies=[Depends(_control_key)])
def clear_registry_override(national_id: str) -> dict[str, Any]:
    STATE.registry_overrides.pop(national_id.strip(), None)
    return {"ok": True}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True, "label": LABEL}
