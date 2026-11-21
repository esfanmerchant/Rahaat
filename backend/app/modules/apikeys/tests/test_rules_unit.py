"""DB-free checks of the API key rules and the key format."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core import apikeys
from app.core.errors import Unprocessable
from app.core.logging import redact
from app.modules.apikeys import rules

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def test_generated_keys_have_the_documented_shape_and_only_a_hash_is_derived() -> None:
    raw, prefix, digest = apikeys.generate()
    assert raw.startswith(f"rk_{prefix}_") and len(prefix) == 10
    assert apikeys.parse_prefix(raw) == prefix
    assert digest == apikeys.hash_key(raw) and len(digest) == 64
    secret = raw.split("_", 2)[2]
    assert secret not in digest and prefix not in digest
    assert apikeys.generate()[0] != raw, "every key is random"


@pytest.mark.parametrize("bad", ["", "rk_", "rk_abc_def", "rk_0123456789_short", "xx_0123456789_" + "a" * 43,
                                 "rk_0123456789_" + "a" * 42 + "!", "rk_ABCDEF0123_" + "a" * 43, "Bearer rk_0123456789_" + "a" * 43])
def test_malformed_keys_are_refused_before_any_lookup(bad: str) -> None:
    assert apikeys.parse_prefix(bad) is None


def test_keys_never_reach_the_logs_in_clear() -> None:
    raw, prefix, _ = apikeys.generate()
    line = redact(f"X-API-Key: {raw} and Authorization: Bearer {raw}")
    assert raw.split("_", 2)[2] not in line
    assert f"rk_{prefix}_[key]" in line, "the public prefix stays, so a log line can still be tied to a key"


def test_status_follows_revocation_expiry_and_approval() -> None:
    assert rules.key_status(revoked_at=None, expires_at=NOW + timedelta(days=1), pending=False, now=NOW) == "active"
    assert rules.key_status(revoked_at=None, expires_at=NOW + timedelta(days=1), pending=True, now=NOW) == "pending_approval"
    assert rules.key_status(revoked_at=None, expires_at=NOW, pending=False, now=NOW) == "expired", "the expiry instant itself is expired"
    assert rules.key_status(revoked_at=NOW, expires_at=NOW + timedelta(days=1), pending=True, now=NOW) == "revoked", "revoked wins"


def test_scopes_must_exist_and_be_used_by_an_endpoint() -> None:
    routes = {"cases:read": ["GET /v1/cases"], "payments:read": ["GET /v1/payments"], "scam:check": []}
    assert rules.check_scopes(["payments:read", "cases:read", "payments:read"], routes) == ["cases:read", "payments:read"]
    with pytest.raises(Unprocessable) as unknown:
        rules.check_scopes(["cases:write"], routes)
    assert unknown.value.code == "unknown_scope" and unknown.value.extra["unknown_scopes"] == ["cases:write"]
    with pytest.raises(Unprocessable) as unused:
        rules.check_scopes(["scam:check"], routes)
    assert unused.value.code == "scope_not_available"


def test_only_personal_data_scopes_need_a_second_admin() -> None:
    assert rules.needs_second_admin(["cases:read"])
    assert rules.needs_second_admin(["payments:read", "cases:read"])
    assert not rules.needs_second_admin(["payments:read"])


def test_rotation_never_extends_a_key() -> None:
    ends = NOW + timedelta(days=20)
    assert rules.rotated_expiry(expires_at=ends, now=NOW, days=None) == ends, "the replacement ends when the old key would have"
    assert rules.rotated_expiry(expires_at=ends, now=NOW, days=7) == NOW + timedelta(days=7), "it may end sooner"
    assert rules.rotated_expiry(expires_at=ends, now=NOW, days=365) == ends, "but never later"
    assert rules.rotated_expiry(expires_at=None, now=NOW, days=None) == NOW + timedelta(days=365), "a key without an end gets the maximum"
