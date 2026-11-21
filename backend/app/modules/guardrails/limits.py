"""Small in-process sliding-window limiters for the AI endpoints (anonymous questions, speech uploads).

The prototype runs one API process (deploy/start.sh), so per-process counters are exact. With several
processes the limits would multiply; the platform-wide limiter would then replace this.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindow:
    """At most `limit` hits per key in any `window_s` seconds. Memory is bounded by `max_keys`."""

    def __init__(self, limit: int, window_s: float, *, max_keys: int = 20_000) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, *, now: float | None = None) -> float | None:
        """Record a hit. Returns None when allowed, else the seconds to wait before the next one is."""
        t = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(t)
                hits = self._hits.setdefault(key, deque())
            while hits and t - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window_s - (t - hits[0]))
            hits.append(t)
            return None

    def _evict(self, now: float) -> None:
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window_s]
        for k in stale:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:  # still full: drop the oldest half
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: self.max_keys // 2]:
                del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
