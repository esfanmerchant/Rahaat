"""Test helpers: a clean mock world with a fake clock and no real sleeping. Used by several modules' tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.mocks.state import STATE
from app.modules.integrations import service

_FAST = {
    "MOCK_TRANSPORT": "inprocess",
    "MOCK_RETRIES": "1",
    "MOCK_BACKOFF_BASE_SECONDS": "0",
    "MOCK_BREAKER_THRESHOLD": "2",
    "MOCK_BREAKER_RESET_SECONDS": "30",
    "MOCK_TIMEOUT_SECONDS": "1.0",
}


@dataclass
class FakeClock:
    now: float = 1_000.0
    slept: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


@contextmanager
def fresh_mocks(**env: str) -> Iterator[FakeClock]:
    """Fresh mock state, fresh breakers, fast retries. Extra `MOCK_*` settings can be passed as keyword args."""
    values = {**_FAST, **{f"MOCK_{k.upper()}": str(v) for k, v in env.items()}}
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    clock = FakeClock()
    STATE.reset_all()
    service.reset()
    service.configure(clock=clock, sleep=clock.sleep)
    try:
        yield clock
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        STATE.reset_all()
        service.reset()
