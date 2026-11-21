"""DB-free checks of the token-bucket arithmetic, with a fake clock instead of sleeping."""

from __future__ import annotations

import uuid

from app.core import ratelimit
from app.core.ratelimit import Charge, Limiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_bucket_allows_a_burst_then_refills_steadily() -> None:
    clock = Clock()
    limiter = Limiter(clock=clock)
    charge = [Charge("user", "u1", per_minute=6)]
    assert all(limiter.take(charge) is None for _ in range(6)), "a full minute's worth may come at once"
    refused = limiter.take(charge)
    assert refused is not None and refused.scope == "user" and refused.retry_after == 10, "one token every 10 s"
    clock.now += 10
    assert limiter.take(charge) is None
    assert limiter.take(charge) is not None


def test_a_request_pays_every_bucket_or_none() -> None:
    limiter = Limiter(clock=Clock())
    tenant, other = uuid.uuid4(), uuid.uuid4()
    lane = Charge("tenant", "t", 3, tenant, label="people")
    user_a = [Charge("user", "a", 10, tenant, label="a"), lane]
    user_b = [Charge("user", "b", 10, tenant, label="b"), lane]
    assert limiter.take(user_a) is None and limiter.take(user_a) is None and limiter.take(user_b) is None
    refused = limiter.take(user_b)
    assert refused is not None and refused.scope == "tenant", "the department's lane is shared"
    remaining = {v.label: v.remaining for v in limiter.snapshot(tenant)}
    assert remaining == {"a": 8, "b": 9, "people": 0}, "the refused call did not use up user b's own tokens"
    assert limiter.snapshot(other) == [], "an admin sees only their own department's buckets"


def test_cost_counts_as_several_requests_and_never_exceeds_the_bucket() -> None:
    clock = Clock()
    limiter = Limiter(clock=clock)
    assert limiter.take([Charge("api_key", "k", 12)], cost=10) is None
    refused = limiter.take([Charge("api_key", "k", 12)], cost=10)
    assert refused is not None and refused.retry_after == 40, "8 tokens short at one token every 5 s"
    small = [Charge("api_key", "tiny", 3)]
    assert limiter.take(small, cost=10) is None, "a cost above the limit takes the whole bucket instead of never passing"
    assert limiter.take(small) is not None


def test_changing_a_limit_applies_without_resetting_the_bucket() -> None:
    limiter = Limiter(clock=Clock())
    for _ in range(5):
        assert limiter.take([Charge("user", "u", 5)]) is None
    assert limiter.take([Charge("user", "u", 50)]) is not None, "raising the limit does not hand out free tokens"
    assert limiter.take([Charge("user", "v", 10)]) is None  # 9 left
    lowered = [Charge("user", "v", 2)]
    assert limiter.take(lowered) is None and limiter.take(lowered) is None, "lowering the limit clamps what is left to 2"
    assert limiter.take(lowered) is not None


def test_the_number_of_buckets_is_bounded() -> None:
    limiter = Limiter(clock=Clock(), max_buckets=100)
    for n in range(1000):
        limiter.take([Charge("ip", f"10.0.{n // 250}.{n % 250}", 5)])
    assert len(limiter) == 100


def test_clients_are_grouped_by_network() -> None:
    assert ratelimit.network_key("203.0.113.7") == "203.0.113.7"
    assert ratelimit.network_key("2001:db8:1:2:3:4:5:6") == ratelimit.network_key("2001:db8:1:2:ffff::1") == "2001:db8:1:2::/64"
    assert ratelimit.network_key("::ffff:203.0.113.7") == "203.0.113.7"
    assert ratelimit.network_key("testclient") == "testclient"
    assert ratelimit.network_key("") == "unknown"


def test_retry_after_is_whole_seconds_and_never_zero_when_refused() -> None:
    assert ratelimit.wait_seconds(5, 1, 1.0) == 0
    assert ratelimit.wait_seconds(0.9, 1, 1.0) == 1
    assert ratelimit.wait_seconds(0, 1, 0.01) == 100
    assert ratelimit.refill(0, 10, 1.0, 100) == 10 and ratelimit.refill(3, 10, 1.0, -5) == 3


def test_only_api_paths_are_limited() -> None:
    assert ratelimit.is_limited_path("/v1/cases")
    for exempt in ("/healthz", "/readyz", "/metrics", "/", "/assets/index.js", "/docs", "/openapi.json"):
        assert not ratelimit.is_limited_path(exempt)
