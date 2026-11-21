"""A small per-process limiter for scam checks: per user and per IP, sliding one-minute windows.

It assumes one API process, which is how the prototype is deployed; the platform-wide limiter replaces it
later. Limits are module attributes so tests can lower them.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from app.core import metrics
from app.core.errors import TooManyRequests

PER_USER_PER_MINUTE = 20
PER_IP_PER_MINUTE = 120
WINDOW_SECONDS = 60.0


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Record a hit. Returns the seconds to wait when the key is over its limit (the hit is then not recorded)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= WINDOW_SECONDS:
                hits.popleft()
            if len(hits) >= limit:
                return max(WINDOW_SECONDS - (now - hits[0]), 1.0)
            hits.append(now)
            if len(self._hits) > 50_000:  # forget idle keys so memory stays bounded
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] >= WINDOW_SECONDS][:10_000]:
                    self._hits.pop(stale, None)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_users = SlidingWindow()
_ips = SlidingWindow()


def check(user_key: str, ip: str) -> None:
    for window, key, limit in ((_users, f"user:{user_key}", PER_USER_PER_MINUTE), (_ips, f"ip:{ip}", PER_IP_PER_MINUTE)):
        if key.endswith(":"):
            continue
        wait = window.hit(key, limit)
        if wait is not None:
            metrics.ACCESS_DENIED.labels("rate_limit").inc()
            raise TooManyRequests("Too many checks in a minute. Please wait and try again.", code="rate_limited",
                                  headers={"Retry-After": str(math.ceil(wait))})  # fmt: skip


def reset() -> None:
    _users.reset()
    _ips.reset()
