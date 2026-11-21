"""Serverless settings: the client address header and the inline-jobs holder. No database."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import reset_settings_cache
from app.core.context import current_client_ip
from app.core.middleware import RequestContextMiddleware


@contextmanager
def env(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    reset_settings_cache()
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        reset_settings_cache()


def _app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, max_body_bytes=10_000)

    @app.get("/ip")
    def ip() -> dict[str, str]:
        return {"ip": current_client_ip()}

    return TestClient(app, client=("10.1.2.3", 5000))


def test_the_forwarded_header_is_ignored_when_the_setting_is_unset() -> None:
    with env(CLIENT_IP_HEADER=""):
        reply = _app().get("/ip", headers={"x-vercel-forwarded-for": "203.0.113.9", "x-forwarded-for": "198.51.100.7", "x-real-ip": "192.0.2.1"})
    assert reply.json() == {"ip": "10.1.2.3"}


def test_the_named_header_is_used_when_set() -> None:
    with env(CLIENT_IP_HEADER="x-vercel-forwarded-for"):
        client = _app()
        assert client.get("/ip", headers={"x-vercel-forwarded-for": "203.0.113.9"}).json() == {"ip": "203.0.113.9"}
        # only the named header counts, and the first address of a list
        assert client.get("/ip", headers={"x-forwarded-for": "198.51.100.7"}).json() == {"ip": "10.1.2.3"}
        assert client.get("/ip", headers={"x-vercel-forwarded-for": "203.0.113.9, 10.0.0.1"}).json() == {"ip": "203.0.113.9"}
        assert client.get("/ip").json() == {"ip": "10.1.2.3"}, "a missing header falls back to the peer address"
