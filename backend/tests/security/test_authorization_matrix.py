"""Authorisation matrix, driven by the policy registry: a new route is covered without editing this file.

For every protected route, each caller its policy does not admit (anonymous, every role outside the policy,
an API key without the route's scope) is refused with 401 or 403 and changes nothing: every row of both
departments hashes the same afterwards, and the only new audit rows are the records of the refusals.
The paths carry real ids of the caller's own department, so "nothing changed" is a real claim.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.security import support
from tests.security.support import ROLES, World

PROTECTED = support.protected_routes()
EXPECTED_PUBLIC = {
    "GET /healthz", "GET /readyz", "GET /metrics", "GET /v1/system/info", "GET /v1/demo/accounts",
    "POST /v1/auth/login", "POST /v1/auth/refresh", "POST /v1/auth/logout", "POST /v1/notifications/verify",
    "POST /v1/people/register/start", "POST /v1/people/register/complete", "GET /{full_path:path}",
    "GET /v1/admin/jobs/drain",  # Vercel Cron: bearer CRON_SECRET compared in constant time; 404 while the secret is unset
    "GET /v1/public/pulse",  # aggregate counts and a synthetic replay for /live; no personal data; rate limited per network
    "POST /v1/ask",  # rules assistant: answers only from approved policy text, no personal data, per-address rate limits
}  # fmt: skip


def _callers(world: World, route: dict[str, Any]) -> list[tuple[str, int, str]]:
    """(caller, expected status, expected problem code) for everyone this route's policy must refuse."""
    callers = [("anonymous", 401, "not_authenticated")]
    callers += [(role, 403, "role_not_allowed") for role in ROLES if role not in route["roles"]]
    key = support.key_without_scope(world.a, route)
    if key is not None:
        callers.append((key, 403, "api_scope_missing"))
    return callers


def test_every_route_declares_a_policy_and_public_routes_are_an_explicit_list() -> None:
    undeclared = [support.route_id(r) for r in support.registry() if r["policy"] is None]
    assert undeclared == []
    public = {support.route_id(r) for r in support.registry() if r["public"]}
    assert public <= EXPECTED_PUBLIC, f"new public routes need a security review: {sorted(public - EXPECTED_PUBLIC)}"
    assert len(PROTECTED) >= 50, "the matrix found suspiciously few routes"


def test_api_keys_are_admitted_only_by_scope_on_a_small_read_surface() -> None:
    keyed = {support.route_id(r): r["api_scopes"] for r in support.registry() if r["api_scopes"]}
    assert keyed, "no route admits API keys"
    assert all(route.startswith("GET ") or "scam" in route for route in keyed), f"keys reach a write route: {keyed}"


@pytest.mark.parametrize("route", PROTECTED, ids=support.route_id)
def test_callers_the_policy_does_not_admit_are_refused_and_change_nothing(world: World, route: dict[str, Any]) -> None:
    path = support.fill(route["path"], world.a.ids)
    callers = _callers(world, route)
    world.warm()
    before, heads = support.fingerprint(world.a, world.b), support.audit_heads(world.a, world.b)

    for who, status, code in callers:
        response = world.call(route["method"], path, side=world.a, who=who, template=route["path"])
        assert response.status_code == status, f"{who}: expected {status}, got {response.status_code}: {response.text[:300]}"
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == code, f"{who}: {response.json()}"

    assert support.fingerprint(world.a, world.b) == before, "a refused request changed data"
    recorded = support.audit_since(heads)
    assert {row.action for row in recorded} <= {"access.denied"}, f"unexpected audit rows: {recorded}"
    refused_after_sign_in = [c for c in callers if c[0] != "anonymous"]
    assert len(recorded) == len(refused_after_sign_in), "every refusal of a known caller is on the record, once"
