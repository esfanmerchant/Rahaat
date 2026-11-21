"""Circuit breaker and retry backoff. Pure: the clock and the sleep are injected, so tests run instantly."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

BreakerState = Literal["closed", "open", "half_open"]


@dataclass
class _Counters:
    state: BreakerState = "closed"
    consecutive_failures: int = 0
    opened_at: float | None = None
    trial_in_flight: bool = False
    total_failures: int = 0
    total_successes: int = 0
    rejected_while_open: int = 0


class CircuitBreaker:
    """closed -> (threshold failures) -> open -> (reset_after) -> half_open -> one trial -> closed or open.

    While open, calls are refused at once instead of waiting for a timeout, so a dead dependency costs
    the citizen nothing and is not hammered while it recovers.
    """

    def __init__(self, name: str, *, threshold: int = 3, reset_after: float = 15.0, clock: Callable[[], float] = time.monotonic) -> None:
        if threshold < 1 or reset_after <= 0:
            raise ValueError("threshold must be at least 1 and reset_after positive")
        self.name = name
        self.threshold = threshold
        self.reset_after = reset_after
        self._clock = clock
        self._c = _Counters()
        self._lock = threading.Lock()

    @property
    def state(self) -> BreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._c.state

    def _maybe_half_open(self) -> None:
        if self._c.state == "open" and self._c.opened_at is not None and self._clock() - self._c.opened_at >= self.reset_after:
            self._c.state = "half_open"
            self._c.trial_in_flight = False

    def allow(self) -> bool:
        """May a call go out now? In half-open state exactly one trial call is let through."""
        with self._lock:
            self._maybe_half_open()
            if self._c.state == "closed":
                return True
            if self._c.state == "half_open" and not self._c.trial_in_flight:
                self._c.trial_in_flight = True
                return True
            self._c.rejected_while_open += 1
            return False

    def record_success(self) -> None:
        with self._lock:
            self._c.state = "closed"
            self._c.consecutive_failures = 0
            self._c.opened_at = None
            self._c.trial_in_flight = False
            self._c.total_successes += 1

    def record_failure(self) -> None:
        with self._lock:
            self._c.total_failures += 1
            self._c.consecutive_failures += 1
            if self._c.state == "half_open" or self._c.consecutive_failures >= self.threshold:
                self._c.state = "open"
                self._c.opened_at = self._clock()
            self._c.trial_in_flight = False

    def reset(self) -> None:
        with self._lock:
            self._c = _Counters()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._maybe_half_open()
            reopen_in = None
            if self._c.state == "open" and self._c.opened_at is not None:
                reopen_in = round(max(0.0, self.reset_after - (self._clock() - self._c.opened_at)), 2)
            return {
                "state": self._c.state,
                "consecutive_failures": self._c.consecutive_failures,
                "threshold": self.threshold,
                "trial_in_seconds": reopen_in,
                "total_failures": self._c.total_failures,
                "total_successes": self._c.total_successes,
                "rejected_while_open": self._c.rejected_while_open,
            }


def backoff_delay(attempt: int, *, base: float, cap: float) -> float:
    """Delay before retry number `attempt` (1-based): base, 2 x base, 4 x base ... never above cap."""
    if attempt < 1:
        return 0.0
    return float(min(cap, base * (2 ** (attempt - 1))))
