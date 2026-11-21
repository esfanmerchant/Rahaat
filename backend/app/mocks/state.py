"""In-memory state of the mock services: failure controls, the payment ledger, the SMS outbox."""

from __future__ import annotations

import random
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from app.mocks.config import SERVICES, get_mock_service_settings
from app.mocks.registry import MockPerson


@dataclass
class ServiceControl:
    latency_ms: int = 0
    failure_rate: float = 0.0  # share of requests answered with 503
    down: bool = False  # every request answered with 503
    calls: int = 0
    failures_injected: int = 0

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MockState:
    controls: dict[str, ServiceControl] = field(default_factory=lambda: {name: ServiceControl() for name in SERVICES})
    payments: dict[str, dict[str, Any]] = field(default_factory=dict)  # idempotency key -> rail record
    sms_outbox: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=500))
    registry_overrides: dict[str, MockPerson] = field(default_factory=dict)
    rng: random.Random = field(default_factory=lambda: random.Random(get_mock_service_settings().seed))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def set_control(self, service: str, *, latency_ms: int | None, failure_rate: float | None, down: bool | None) -> None:
        with self.lock:
            control = self.controls[service]
            if latency_ms is not None:
                control.latency_ms = latency_ms
            if failure_rate is not None:
                control.failure_rate = failure_rate
            if down is not None:
                control.down = down

    def reset_controls(self) -> None:
        with self.lock:
            self.controls = {name: ServiceControl() for name in SERVICES}
            self.rng = random.Random(get_mock_service_settings().seed)

    def reset_all(self) -> None:
        self.reset_controls()
        with self.lock:
            self.payments.clear()
            self.sms_outbox.clear()
            self.registry_overrides.clear()

    def draw_failure(self, service: str) -> tuple[bool, int]:
        """Count the call and decide whether to inject a failure. Returns (fail, latency_ms)."""
        with self.lock:
            control = self.controls[service]
            control.calls += 1
            fail = control.down or (control.failure_rate > 0 and self.rng.random() < control.failure_rate)
            if fail:
                control.failures_injected += 1
            return fail, control.latency_ms


STATE = MockState()
