"""In-process token buckets: per client network for anonymous calls, per user, per API key and per department.

One API process serves the prototype (DECISIONS 3), so the buckets live in memory. A bucket holds one minute's
worth of requests and refills continuously, so a short burst passes and a steady flood is held to the limit.
A request takes its cost from every bucket that applies, or from none: a call refused by the department's
bucket does not use up the caller's own.

A department has two lanes, one for people and one for API keys, so a busy integration cannot lock its own
officers out (and the other way round).

Only `/v1/` paths are limited. Health, metrics, the API docs and the static frontend are exempt. Sign-in and
registration keep their own, stricter throttles on top of this.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core import metrics
from app.core.config import get_settings
from app.core.context import current_client_ip
from app.core.errors import TooManyRequests

Scope = Literal["ip", "user", "api_key", "tenant"]

LIMITED_PREFIX = "/v1/"
MAX_COST = 100


def refill(tokens: float, capacity: float, per_second: float, elapsed: float) -> float:
    """Tokens after `elapsed` seconds of refilling, never above the capacity."""
    return min(capacity, tokens + max(0.0, elapsed) * per_second)


def wait_seconds(tokens: float, cost: float, per_second: float) -> int:
    """Whole seconds until `cost` tokens are available: 0 when they already are, otherwise at least 1."""
    if tokens >= cost:
        return 0
    return max(1, math.ceil((cost - tokens) / per_second))


def is_limited_path(path: str) -> bool:
    return path.startswith(LIMITED_PREFIX)


def network_key(ip: str) -> str:
    """The bucket for an anonymous caller.

    IPv6 clients are grouped by their /64, the block one customer is usually given, so stepping through
    addresses does not reset the limit. IPv4-mapped IPv6 addresses count as the IPv4 address.
    """
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return ip.strip()[:64] or "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


@dataclass(frozen=True, slots=True)
class Charge:
    """One bucket a request must pay into."""

    scope: Scope
    key: str
    per_minute: int
    tenant_id: UUID | None = None
    label: str = ""  # what an admin sees: a user id, a key prefix, a lane name


@dataclass(frozen=True, slots=True)
class Refusal:
    scope: Scope
    per_minute: int
    retry_after: int


@dataclass(frozen=True, slots=True)
class BucketView:
    scope: Scope
    label: str
    per_minute: int
    remaining: int
    seconds_to_full: int


@dataclass(slots=True)
class _Bucket:
    scope: Scope
    tenant_id: UUID | None
    label: str
    capacity: float
    per_second: float
    tokens: float
    updated: float


class Limiter:
    """Thread-safe token buckets. `clock` is injectable so the arithmetic is tested without sleeping."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, max_buckets: int = 20_000) -> None:
        self._clock = clock
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()
        self._lock = threading.Lock()

    def take(self, charges: Sequence[Charge], cost: int = 1) -> Refusal | None:
        """Take `cost` tokens from every bucket, or from none. Returns the refusal with the longest wait, if any."""
        cost = max(1, min(int(cost), MAX_COST))
        now = self._clock()
        with self._lock:
            buckets = [self._bucket(charge, now) for charge in charges]
            refusals = []
            for charge, bucket in zip(charges, buckets, strict=True):
                need = min(float(cost), bucket.capacity)  # a cost above the limit takes the whole bucket, never more
                if bucket.tokens < need:
                    refusals.append(Refusal(charge.scope, charge.per_minute, wait_seconds(bucket.tokens, need, bucket.per_second)))
            if refusals:
                return max(refusals, key=lambda refusal: refusal.retry_after)
            for bucket in buckets:
                bucket.tokens -= min(float(cost), bucket.capacity)
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)  # the least recently used bucket; it would come back full
            return None

    def _bucket(self, charge: Charge, now: float) -> _Bucket:
        ident = (charge.scope, charge.key)
        capacity = float(max(1, charge.per_minute))
        per_second = capacity / 60.0
        bucket = self._buckets.get(ident)
        if bucket is None:
            bucket = _Bucket(charge.scope, charge.tenant_id, charge.label, capacity, per_second, capacity, now)
            self._buckets[ident] = bucket
            return bucket
        bucket.tokens = refill(bucket.tokens, bucket.capacity, bucket.per_second, now - bucket.updated)
        bucket.updated = now
        if bucket.capacity != capacity:  # the limit changed: settings, or an admin chose another one
            bucket.capacity, bucket.per_second = capacity, per_second
            bucket.tokens = min(bucket.tokens, capacity)
        self._buckets.move_to_end(ident)
        return bucket

    def snapshot(self, tenant_id: UUID) -> list[BucketView]:
        """The department's buckets as they stand now (people, keys and the two department lanes)."""
        now = self._clock()
        with self._lock:
            views = []
            for bucket in self._buckets.values():
                if bucket.tenant_id != tenant_id:
                    continue
                tokens = refill(bucket.tokens, bucket.capacity, bucket.per_second, now - bucket.updated)
                views.append(BucketView(bucket.scope, bucket.label, int(bucket.capacity), int(tokens),
                                        wait_seconds(tokens, bucket.capacity, bucket.per_second)))  # fmt: skip
            return views

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def __len__(self) -> int:
        return len(self._buckets)


LIMITER = Limiter()

_MESSAGES: dict[Scope, str] = {
    "ip": "Too many requests from your network. Wait {s} seconds and try again.",
    "user": "You are sending requests faster than we allow. Wait {s} seconds and try again.",
    "api_key": "This API key has used its {n} requests a minute. Wait {s} seconds and try again.",
    "tenant": "Your department is sending too many requests right now. Wait {s} seconds and try again.",
}


def refusal_error(refusal: Refusal) -> TooManyRequests:
    """429 with `Retry-After` and a plain message. The problem document also says which limit was hit."""
    metrics.RATE_LIMITED.labels(refusal.scope).inc()
    return TooManyRequests(
        _MESSAGES[refusal.scope].format(s=refusal.retry_after, n=refusal.per_minute),
        code="rate_limited",
        headers={"Retry-After": str(refusal.retry_after)},
        extra={"limit_scope": refusal.scope, "limit_per_minute": refusal.per_minute, "retry_after_seconds": refusal.retry_after},
    )


def anonymous_charges(ip: str) -> list[Charge]:
    network = network_key(ip)
    return [Charge("ip", network, get_settings().rate_limits().anonymous_per_minute, label=network)]


def user_charges(tenant_id: UUID, user_id: UUID) -> list[Charge]:
    limits = get_settings().rate_limits()
    return [
        Charge("user", f"{tenant_id}:{user_id}", limits.user_per_minute, tenant_id, label=str(user_id)),
        Charge("tenant", f"{tenant_id}:people", limits.tenant_per_minute, tenant_id, label="people"),
    ]


def api_key_charges(tenant_id: UUID, key_id: UUID, prefix: str, per_minute: int) -> list[Charge]:
    limits = get_settings().rate_limits()
    return [
        Charge("api_key", str(key_id), per_minute, tenant_id, label=prefix),
        Charge("tenant", f"{tenant_id}:api", limits.tenant_per_minute, tenant_id, label="api_keys"),
    ]


def charge(path: str, charges: Sequence[Charge], cost: int = 1) -> None:
    """Pay for one request on `path`, or raise 429. Paths outside `/v1/` are never limited."""
    if not get_settings().rate_limits().enabled or not is_limited_path(path):
        return
    refusal = LIMITER.take(charges, cost)
    if refusal is not None:
        raise refusal_error(refusal)


def charge_anonymous(path: str, cost: int = 1) -> None:
    """Calls without a valid credential pay per client network: public routes and failed sign-ins alike."""
    if not get_settings().rate_limits().enabled or not is_limited_path(path):
        return
    charge(path, anonymous_charges(current_client_ip()), cost)
