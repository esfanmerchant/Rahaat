"""Adapters for the (mock) external services: identity, registry, payment rail, SMS.

Every call has a timeout, a bounded retry with exponential backoff (timeouts and 5xx only) and a per-service
circuit breaker. An expected outage comes back as a status such as `("unavailable", None)`, never as an
exception, so a caller cannot forget to handle it. Callers decide what an outage means: identity or
registry unavailable sends the case to a person; a payment rail failure leaves the payment retryable.

Signatures used by other tracks (app/contracts/engine.py):
    verify_identity(national_id, full_name, dob) -> IdentityCheck
    lookup_registry(national_id) -> tuple[RegistryStatus, RegistryRecord | None]
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from prometheus_client import Counter
from pydantic import ValidationError

from app.contracts.engine import IdentityCheck, RegistryRecord, RegistryStatus
from app.core.config import get_settings
from app.core.errors import ServiceUnavailable
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier, mock_id_valid, normalise_mock_phone
from app.mocks.config import SERVICES
from app.modules.integrations.resilience import CircuitBreaker, backoff_delay
from app.modules.integrations.settings import get_integration_settings
from app.modules.integrations.transport import HttpTransport, InProcessTransport, MockResponse, Transport, TransportError

log = get_logger("rahat.integrations")

CALLS = Counter("rahat_integration_calls_total", "Calls to external (mock) services", ["service", "outcome"])

PaymentRailStatus = Literal["settled", "rejected", "unavailable"]
SmsStatus = Literal["sent", "rejected", "unavailable"]


@dataclass(frozen=True)
class RailResult:
    status: PaymentRailStatus
    rail_ref: str | None = None
    settled_pkr: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SmsResult:
    status: SmsStatus
    message_id: str | None = None
    detail: str | None = None


# Plain words for a citizen when a service is down. Keyed by service; the pipeline picks the language.
DEGRADED_MESSAGES: dict[str, dict[str, str]] = {
    "identity": {
        "en": "We could not check your ID card right now. A person will check it. You do not need to do anything.",
        "ur": "ہم ابھی آپ کا شناختی کارڈ چیک نہیں کر سکے۔ ایک افسر اسے دیکھے گا۔ آپ کو کچھ نہیں کرنا۔",
    },
    "registry": {
        "en": "We could not reach the records office right now. A person will check your application. You do not need to do anything.",
        "ur": "ہم ابھی ریکارڈ دفتر سے رابطہ نہیں کر سکے۔ ایک افسر آپ کی درخواست دیکھے گا۔ آپ کو کچھ نہیں کرنا۔",
    },
    "payment": {
        "en": "Your payment is approved. Sending it is taking longer than usual. We will try again and send you a message.",
        "ur": "آپ کی رقم منظور ہو گئی ہے۔ بھیجنے میں دیر ہو رہی ہے۔ ہم دوبارہ کوشش کریں گے اور آپ کو پیغام بھیجیں گے۔",
    },
    "sms": {
        "en": "We could not send a text message right now. You can see all messages in the Rahat app.",
        "ur": "ہم ابھی پیغام نہیں بھیج سکے۔ آپ سب پیغام راحت ایپ میں دیکھ سکتے ہیں۔",
    },
}


def degradation_message(service: str, lang: str = "ur") -> str:
    messages = DEGRADED_MESSAGES[service]
    return messages.get(lang, messages["ur"])


# --- wiring (replaceable in tests) ----------------------------------------------------------------------

_lock = threading.Lock()
_breakers: dict[str, CircuitBreaker] = {}
_transport: Transport | None = None
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def configure(
    *, transport: Transport | None = None, clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None
) -> None:
    """Replace the transport, clock or sleep (tests). Breakers are rebuilt with the new clock."""
    global _transport, _clock, _sleep
    with _lock:
        if transport is not None:
            _transport = transport
        if clock is not None:
            _clock = clock
            _breakers.clear()
        if sleep is not None:
            _sleep = sleep


def reset() -> None:
    """Back to defaults: fresh breakers, transport chosen from settings, real clock."""
    global _transport, _clock, _sleep
    get_integration_settings.cache_clear()
    with _lock:
        _breakers.clear()
        _transport = None
        _clock = time.monotonic
        _sleep = time.sleep


def breaker(service: str) -> CircuitBreaker:
    with _lock:
        if service not in _breakers:
            settings = get_integration_settings()
            _breakers[service] = CircuitBreaker(
                service, threshold=settings.breaker_threshold, reset_after=settings.breaker_reset_seconds, clock=_clock
            )
        return _breakers[service]


def transport() -> Transport:
    global _transport
    with _lock:
        if _transport is None:
            if get_integration_settings().transport_effective() == "inprocess":
                _transport = InProcessTransport()
            else:
                _transport = HttpTransport(get_settings().mock_base_url)
        return _transport


def breaker_snapshots() -> dict[str, dict[str, Any]]:
    return {name: breaker(name).snapshot() for name in SERVICES}


def _transient(response: MockResponse) -> bool:
    return response.status >= 500 or response.status == 429


def _call(service: str, method: str, path: str, *, json: dict[str, Any] | None = None) -> MockResponse | None:
    """One logical call with retries. None means unavailable (breaker open, or every attempt failed)."""
    settings = get_integration_settings()
    gate = breaker(service)
    if not gate.allow():
        CALLS.labels(service, "breaker_open").inc()
        return None
    attempts = 1 + max(0, settings.retries)
    last_problem = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            response = transport().request(method, path, key=settings.key_for(service), timeout=settings.timeout_for(service), json=json)
        except TransportError as exc:
            last_problem = str(exc) or "transport_error"
        else:
            if not _transient(response):
                gate.record_success()
                CALLS.labels(service, "ok" if response.status < 400 else "client_error").inc()
                return response
            last_problem = f"http_{response.status}"
        if attempt < attempts:
            CALLS.labels(service, "retried").inc()
            _sleep(backoff_delay(attempt, base=settings.backoff_base_seconds, cap=settings.backoff_max_seconds))
    gate.record_failure()
    CALLS.labels(service, "unavailable").inc()
    log.warning("%s service unavailable after %d attempts (%s); breaker is %s", service, attempts, last_problem, gate.state)
    return None


# --- adapters -------------------------------------------------------------------------------------------


def verify_identity(national_id: str, full_name: str | None, dob: str | None) -> IdentityCheck:
    """Does this mock ID, name and date of birth belong to one record? `unavailable` on an outage."""
    if not national_id or not mock_id_valid(national_id):
        return IdentityCheck(status="not_found", checked_at=_now())  # never send anything but a valid mock ID out
    response = _call("identity", "POST", "/identity/verify", json={"national_id": national_id.strip(), "full_name": full_name, "dob": dob})
    if response is None:
        return IdentityCheck(status="unavailable")
    if response.status == 404:
        return IdentityCheck(status="not_found", checked_at=_now())
    if response.status != 200 or response.body.get("status") not in ("match", "partial", "mismatch"):
        log.error("identity service gave an unexpected answer (HTTP %s)", response.status)
        return IdentityCheck(status="unavailable")
    score = response.body.get("name_score")
    return IdentityCheck(
        status=response.body["status"],
        name_score=float(score) if isinstance(score, int | float) else None,
        checked_at=str(response.body.get("checked_at") or _now()),
    )


def lookup_registry(national_id: str) -> tuple[RegistryStatus, RegistryRecord | None]:
    """The registry's record for a mock ID: ("found", record), ("not_found", None) or ("unavailable", None)."""
    if not national_id or not mock_id_valid(national_id):
        return "not_found", None
    response = _call("registry", "GET", f"/registry/persons/{national_id.strip()}")
    if response is None:
        return "unavailable", None
    if response.status == 404:
        return "not_found", None
    if response.status != 200:
        log.error("registry gave an unexpected answer (HTTP %s)", response.status)
        return "unavailable", None
    try:
        return "found", RegistryRecord.model_validate(response.body)
    except ValidationError:
        log.error("registry record did not match the contract")
        return "unavailable", None


def submit_payment(*, idempotency_key: str, amount_pkr: int, account_ref: str, reference: str = "") -> RailResult:
    """Send money on the (mock) rail. Safe to repeat: the same key never pays twice."""
    response = _call(
        "payment", "POST", "/payments",
        json={"idempotency_key": idempotency_key, "amount_pkr": amount_pkr, "account_ref": account_ref[:64] or "cash-pickup",
              "reference": reference[:80]},
    )  # fmt: skip
    if response is None:
        return RailResult("unavailable", detail=degradation_message("payment", "en"))
    if response.status == 200 and response.body.get("status") == "settled":
        settled = response.body.get("settled_pkr")
        return RailResult("settled", rail_ref=str(response.body.get("rail_ref")), settled_pkr=int(settled) if settled is not None else None)
    return RailResult("rejected", detail=str(response.body.get("code") or f"http_{response.status}"))


def send_sms(to: str, body: str, *, sender: str = "RAHAT") -> SmsResult:
    """Send one text message through the (mock) gateway. Only mock numbers are ever sent."""
    phone = normalise_mock_phone(to or "")
    if phone is None:
        return SmsResult("rejected", detail="not_a_mock_number")
    response = _call("sms", "POST", "/sms/messages", json={"to": phone, "body": body[:480], "sender": sender[:16]})
    if response is None:
        return SmsResult("unavailable")
    if response.status == 200:
        return SmsResult("sent", message_id=str(response.body.get("message_id")))
    return SmsResult("rejected", detail=str(response.body.get("code") or f"http_{response.status}"))


# --- failure controls (admin, demo only) ----------------------------------------------------------------


def _control(method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Control calls skip the breaker and the retries: an admin wants the plain answer."""
    settings = get_integration_settings()
    try:
        response = transport().request(method, path, key=settings.control_key, timeout=settings.timeout_seconds, json=json)
    except TransportError as exc:
        raise ServiceUnavailable("The mock services are not reachable.", code="mocks_unreachable") from exc
    if response.status != 200:
        raise ServiceUnavailable(f"The mock services refused the control call (HTTP {response.status}).", code="mocks_refused")
    return response.body


def mock_controls() -> dict[str, Any]:
    return _control("GET", "/control")


def set_mock_control(service: str, *, latency_ms: int | None, failure_rate: float | None, down: bool | None) -> dict[str, Any]:
    return _control("POST", f"/control/{service}", json={"latency_ms": latency_ms, "failure_rate": failure_rate, "down": down})


def reset_mock_controls() -> dict[str, Any]:
    body = _control("POST", "/control/reset")
    for name in SERVICES:
        breaker(name).reset()
    return body


def mock_sms_outbox(limit: int = 50) -> list[dict[str, Any]]:
    """The gateway's own outbox (what the phones 'received'), with numbers masked."""
    settings = get_integration_settings()
    try:
        response = transport().request("GET", f"/sms/outbox?limit={int(limit)}", key=settings.sms_key, timeout=settings.timeout_seconds)
    except TransportError as exc:
        raise ServiceUnavailable("The mock SMS gateway is not reachable.", code="mocks_unreachable") from exc
    if response.status != 200:
        raise ServiceUnavailable(f"The mock SMS gateway refused (HTTP {response.status}).", code="mocks_refused")
    return [{**m, "to": mask_identifier(str(m.get("to", "")))} for m in response.body.get("items", [])]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
