"""Insecure direct object references, for every route with an id in its path (found from the registry).

A caller the policy admits, in department A, sends a random id and then a real id that belongs to department
B. Both must answer 404 (or 403), show nothing of B, and change nothing in B. Lists read by B's staff and B's
API keys must not contain anything of A.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.security import support
from tests.security.support import PARAM, World

ID_ROUTES = [r for r in support.protected_routes() if PARAM.search(r["path"])]
LIST_ROUTES = [r for r in support.protected_routes() if r["method"] == "GET" and not PARAM.search(r["path"])]


def test_the_write_detector_notices_a_change(world: World) -> None:
    from app.core.db import system_session
    from app.db import models

    before = support.fingerprint(world.b)
    with system_session() as db:
        case = db.get(models.Case, world.b.ids["case_id"])
        assert case is not None
        case.priority = case.priority + 1
    after = support.fingerprint(world.b)
    assert after != before and after["cases"] != before["cases"]


@pytest.mark.parametrize("route", ID_ROUTES, ids=support.route_id)
def test_a_random_id_and_another_departments_real_id_reveal_nothing(world: World, route: dict[str, Any]) -> None:
    params = PARAM.findall(route["path"])
    missing = [p for p in params if p not in world.b.ids]
    assert not missing, f"tests/security/support.py has no real object for {missing}: add one so this route is covered"
    caller = support.admitted_caller(route)
    world.warm()
    before = support.fingerprint(world.b)

    attempts = {
        "a random id": support.fill(route["path"], {p: uuid.uuid4() for p in params}),
        "department B's real id": support.fill(route["path"], world.b.ids),
    }
    for label, path in attempts.items():
        response = world.call(route["method"], path, side=world.a, who=caller, template=route["path"])
        assert response.status_code in (403, 404), f"{caller} with {label}: {response.status_code} {response.text[:300]}"
        assert response.headers["content-type"].startswith("application/problem+json")
        assert not support.leaked(response.text, world.b.markers), f"{label}: the answer mentions department B"

    assert support.fingerprint(world.b) == before, "department B changed after a request from department A"


@pytest.mark.parametrize("route", LIST_ROUTES, ids=support.route_id)
def test_lists_never_show_another_departments_records(world: World, route: dict[str, Any]) -> None:
    callers = [support.admitted_caller(route)]
    callers += [f"key:{name}" for name, scopes in world.b.key_scopes.items() if set(scopes) & set(route["api_scopes"])]
    for who in callers:
        response = world.call(route["method"], route["path"], side=world.b, who=who)
        assert response.status_code < 500, f"{who}: {response.status_code} {response.text[:300]}"
        assert not support.leaked(response.text, world.a.markers), f"{who} of department B sees department A's records"


def test_an_api_key_reads_only_its_own_department(world: World) -> None:
    mine = world.client.get("/v1/cases", headers=world.headers(world.a, "key:cases"))
    assert mine.status_code == 200
    assert [c["id"] for c in mine.json()["items"]] == [str(world.a.ids["case_id"])]
    other = world.client.get(f"/v1/cases/{world.b.ids['case_id']}", headers=world.headers(world.a, "key:cases"))
    assert other.status_code == 404
