"""Sign-in, sessions, refresh rotation with reuse detection, lockout and tenant switching."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

APP_HEADER = {"X-Requested-With": "rahat"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_staff_and_citizens_can_sign_in(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    officer, citizen = factory.account(tenant, "officer"), factory.account(tenant, "citizen")

    staff = factory.login(client, officer)
    assert staff["active"]["role"] == "officer" and staff["active"]["tenant_slug"] == tenant.slug
    assert staff["token_type"] == "bearer" and staff["expires_in"] > 0

    person = factory.login(client, citizen)
    assert person["active"]["role"] == "citizen" and person["active"]["person_id"] == str(citizen.person_id)

    me = client.get("/v1/auth/me", headers=_bearer(staff["access_token"]))
    assert me.status_code == 200 and me.json()["user"]["id"] == str(officer.user_id)


def test_refresh_cookie_is_http_only_and_scoped(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    response = client.post("/v1/auth/login", json={"identifier": account.identifier, "secret": account.secret})
    cookie = response.headers["set-cookie"].lower()
    assert "rt=" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/v1/auth" in cookie
    assert "rt" not in response.json() and "refresh" not in response.text.lower()


def test_wrong_password_and_unknown_account_look_identical(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    wrong = client.post("/v1/auth/login", json={"identifier": account.identifier, "secret": "nope"})
    unknown = client.post("/v1/auth/login", json={"identifier": "nobody@test.rahat.example", "secret": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    strip = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert strip(wrong) == strip(unknown), "the response must not reveal whether the account exists"
    assert wrong.json()["code"] == "invalid_credentials"
    assert wrong.headers["content-type"].startswith("application/problem+json")


def test_real_looking_phone_numbers_are_never_accepted(client: TestClient) -> None:
    response = client.post("/v1/auth/login", json={"identifier": "0300-1234567", "secret": "4826"})  # mock-lint: allow
    assert response.status_code == 401


def test_account_locks_after_repeated_failures(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    for _ in range(5):
        assert client.post("/v1/auth/login", json={"identifier": account.identifier, "secret": "wrong"}).status_code == 401
    locked = client.post("/v1/auth/login", json={"identifier": account.identifier, "secret": account.secret})
    assert locked.status_code == 429 and locked.json()["code"] == "account_locked", "even the right password waits"
    assert int(locked.headers["retry-after"]) > 0


def test_unknown_identifiers_lock_too_so_lockout_reveals_nothing(client: TestClient) -> None:
    ghost = {"identifier": "ghost-lockout@test.rahat.example", "secret": "wrong"}
    for _ in range(5):
        assert client.post("/v1/auth/login", json=ghost).status_code == 401
    assert client.post("/v1/auth/login", json=ghost).status_code == 429


def test_refresh_rotates_and_needs_the_app_header(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    first = factory.login(client, account)
    assert client.post("/v1/auth/refresh").status_code == 403, "cookie-authenticated calls need the custom header"

    refreshed = client.post("/v1/auth/refresh", headers=APP_HEADER)
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != first["access_token"]
    assert client.get("/v1/auth/me", headers=_bearer(refreshed.json()["access_token"])).status_code == 200


def test_reusing_an_old_refresh_token_ends_every_session_in_the_family(client: TestClient, app: Any, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    factory.login(client, account)
    stolen = client.cookies.get("rt")
    latest = client.post("/v1/auth/refresh", headers=APP_HEADER).json()["access_token"]  # the real user rotates

    thief = TestClient(app)
    thief.cookies.set("rt", stolen)
    assert thief.post("/v1/auth/refresh", headers=APP_HEADER).status_code == 401, "the rotated token is dead"

    # Someone holds a copy, so the whole family is revoked, including the real user's current session.
    assert client.get("/v1/auth/me", headers=_bearer(latest)).status_code == 401
    assert client.post("/v1/auth/refresh", headers=APP_HEADER).status_code == 401


def test_sign_out_takes_effect_immediately(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "auditor")
    token = factory.login(client, account)["access_token"]
    assert client.get("/v1/auth/me", headers=_bearer(token)).status_code == 200
    assert client.post("/v1/auth/logout", headers=APP_HEADER).status_code == 204
    ended = client.get("/v1/auth/me", headers=_bearer(token))
    assert ended.status_code == 401 and ended.json()["code"] == "session_ended", "a still-valid token is not enough"


def test_sessions_can_be_listed_and_revoked_all(client: TestClient, app: Any, factory: Any) -> None:
    account = factory.account(factory.tenant(), "admin")
    token_a = factory.login(client, account)["access_token"]
    token_b = factory.login(TestClient(app), account)["access_token"]
    sessions = client.get("/v1/auth/sessions", headers=_bearer(token_a)).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1

    assert client.post("/v1/auth/logout-all", headers=_bearer(token_a)).json() == {"revoked": 2}
    assert client.get("/v1/auth/me", headers=_bearer(token_b)).status_code == 401


def test_switching_department_invalidates_the_old_token(client: TestClient, factory: Any) -> None:
    first, second, other = factory.tenant("First"), factory.tenant("Second"), factory.tenant("Not mine")
    auditor = factory.account(first, "auditor", extra_tenants=(second,))
    session = factory.login(client, auditor, tenant_slug=first.slug)
    assert {m["tenant_id"] for m in session["memberships"]} == {str(first.id), str(second.id)}
    assert session["active"]["tenant_id"] == str(first.id)
    old = _bearer(session["access_token"])

    refused = client.post("/v1/auth/switch", headers=old, json={"tenant_id": str(other.id)})
    assert refused.status_code == 403 and refused.json()["code"] == "not_a_member"

    switched = client.post("/v1/auth/switch", headers=old, json={"tenant_id": str(second.id)})
    assert switched.status_code == 200 and switched.json()["active"]["tenant_id"] == str(second.id)
    assert client.get("/v1/auth/me", headers=old).status_code == 401, "tokens for the previous department stop working"
    assert client.get("/v1/auth/me", headers=_bearer(switched.json()["access_token"])).status_code == 200


def test_tenant_slug_picks_the_department_and_refuses_foreign_ones(client: TestClient, factory: Any) -> None:
    first, second, other = factory.tenant(), factory.tenant(), factory.tenant()
    auditor = factory.account(first, "auditor", extra_tenants=(second,))
    assert factory.login(client, auditor, tenant_slug=second.slug)["active"]["tenant_id"] == str(second.id)
    refused = client.post("/v1/auth/login", json={"identifier": auditor.identifier, "secret": auditor.secret, "tenant_slug": other.slug})
    assert refused.status_code == 401 and refused.json()["code"] == "invalid_credentials"


def test_requests_without_or_with_forged_tokens_are_refused(client: TestClient, factory: Any) -> None:
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=_bearer("eyJhbGciOiJub25lIn0.e30.")).status_code == 401
    token = factory.login(client, factory.account(factory.tenant(), "citizen"))["access_token"]
    header, payload, signature = token.split(".")
    assert client.get("/v1/auth/me", headers=_bearer(f"{header}.{payload}x.{signature}")).status_code == 401


def test_sign_in_is_audited(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    auditor = factory.account(tenant, "auditor")
    headers = factory.headers(client, auditor)
    actions = [e["action"] for e in client.get("/v1/audit", headers=headers).json()["items"]]
    assert "auth.login" in actions
