"""Read-only probes of the HTTP surface: security headers, CORS, and error bodies that never leak internals."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

EVIL = "https://evil.example"


def _responses(client: TestClient) -> dict[str, Any]:
    return {
        "ok": client.get("/v1/system/info"),
        "health": client.get("/healthz"),
        "not found": client.get("/v1/nothing-here"),
        "unauthenticated": client.get("/v1/cases"),
        "forged token": client.get("/v1/cases", headers={"Authorization": "Bearer eyJhbGciOiJub25lIn0.e30."}),
        "method not allowed": client.get("/v1/auth/login"),
        "invalid body": client.post("/v1/auth/login", json={"identifier": 1}),
        "malformed json": client.post("/v1/auth/login", content=b"{nope", headers={"content-type": "application/json"}),
        "too large": client.post("/v1/auth/login", content=b"x" * 7_000_000, headers={"content-type": "application/json"}),
    }


def test_every_kind_of_response_carries_the_security_headers(client: TestClient) -> None:
    for label, response in _responses(client).items():
        headers = response.headers
        assert headers["x-content-type-options"] == "nosniff", label
        assert headers["x-frame-options"] == "DENY", label
        assert headers["referrer-policy"] == "no-referrer", label
        assert headers["cross-origin-opener-policy"] == "same-origin", label
        assert "geolocation=()" in headers["permissions-policy"], label
        csp = headers["content-security-policy"]
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp and "unsafe-inline" not in csp, label
        assert headers["x-request-id"], label
        if label != "health":
            assert headers["cache-control"] == "no-store", f"{label}: API answers must not be cached"


def test_hsts_is_sent_behind_an_https_proxy(client: TestClient) -> None:
    response = client.get("/healthz", headers={"X-Forwarded-Proto": "https"})
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


def test_only_the_api_docs_get_the_relaxed_content_policy(client: TestClient) -> None:
    docs = client.get("/docs")
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    assert "cdn.jsdelivr.net" not in client.get("/v1/system/info").headers["content-security-policy"]


@pytest.mark.parametrize("origin", [EVIL, "null", "http://localhost:5173", "https://rahat.example.evil.example"])
def test_no_origin_is_allowed_to_read_responses_cross_origin(client: TestClient, factory: Any, origin: str) -> None:
    preflight = client.options("/v1/cases", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                     "Access-Control-Request-Headers": "authorization"})  # fmt: skip
    assert preflight.status_code >= 400, "no CORS preflight is ever approved"
    officer = factory.headers(client, factory.account(factory.tenant(), "officer"))
    for response in (preflight, client.get("/v1/system/info", headers={"Origin": origin}),
                     client.get("/v1/cases", headers={**officer, "Origin": origin}),
                     client.post("/v1/auth/login", json={"identifier": "x@y.example", "secret": "z"}, headers={"Origin": origin})):  # fmt: skip
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-allow-credentials" not in response.headers


def test_the_refresh_cookie_cannot_be_read_by_scripts_or_sent_cross_site(client: TestClient, factory: Any) -> None:
    account = factory.account(factory.tenant(), "officer")
    cookie = client.post("/v1/auth/login", json={"identifier": account.identifier, "secret": account.secret}).headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/v1/auth" in cookie
    refused = client.post("/v1/auth/refresh")
    assert refused.status_code == 403 and refused.json()["code"] == "csrf_header_missing", "a cross-site form cannot refresh"


def test_errors_are_problem_documents_without_internals(client: TestClient) -> None:
    for label, response in _responses(client).items():
        if response.status_code < 400:
            continue
        assert response.headers["content-type"].startswith("application/problem+json"), label
        body = response.json()
        assert {"type", "title", "status", "detail", "code", "request_id"} <= set(body), label
        assert body["request_id"] == response.headers["x-request-id"], label
        for leak in ("Traceback", 'File "', ".py", "sqlalchemy", "psycopg", "pydantic_core"):
            assert leak not in response.text, f"{label} leaks {leak!r}"


def test_validation_errors_do_not_echo_what_was_sent(client: TestClient) -> None:
    probe = "<script>do-not-echo-0999-1234567</script>"
    response = client.post("/v1/auth/login", json={"identifier": probe, "secret": probe, "extra": probe})
    assert response.status_code == 422 and probe not in response.text and "do-not-echo" not in response.text


def test_an_unexpected_failure_is_a_plain_500_with_headers_and_a_request_id(app: Any, factory: Any, monkeypatch: pytest.MonkeyPatch,
                                                                            caplog: pytest.LogCaptureFixture) -> None:  # fmt: skip
    """Regression: 500s used to be rendered outside the middleware, with no security headers and request id '-'."""
    from app.modules.system import router as system_router

    def explode(_: Any) -> Any:
        raise RuntimeError("internal detail /srv/app/secret_module.py line 42 password=hunter2")

    monkeypatch.setattr(system_router, "describe_routes", explode)
    with TestClient(app, raise_server_exceptions=False) as quiet:
        admin = factory.headers(quiet, factory.account(factory.tenant(), "admin"))
        response = quiet.get("/v1/system/policies", headers={**admin, "X-Request-ID": "probe-500-request"})
    assert response.status_code == 500 and response.json()["code"] == "internal_error"
    assert response.headers["content-type"].startswith("application/problem+json")
    for leak in ("RuntimeError", "secret_module", "hunter2", "Traceback", ".py"):
        assert leak not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"] == "probe-500-request", "the id to quote is real"
    assert response.headers["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    logged = [r for r in caplog.records if r.getMessage().startswith("unhandled error")]
    assert len(logged) == 1, "logged once, by the middleware, while the request id is still known"


def test_unexpected_errors_still_reach_the_test_client(app: Any, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.system import router as system_router

    monkeypatch.setattr(system_router, "describe_routes", lambda _: 1 / 0)
    with TestClient(app) as strict:
        admin = factory.headers(strict, factory.account(factory.tenant(), "admin"))
        with pytest.raises(ZeroDivisionError):
            strict.get("/v1/system/policies", headers=admin)
