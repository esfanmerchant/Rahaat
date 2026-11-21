"""How adapters reach the mock services: in process (dev and test) or over HTTP (deployed).

Both transports enforce the timeout, so a slow mock looks the same either way. The HTTP transport never
follows redirects and ignores proxy environment variables: it talks to one internal address only.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.mocks.config import KEY_HEADER


class TransportError(Exception):
    """The service could not be reached in time (connection refused, timeout). Always worth a retry."""


@dataclass(frozen=True)
class MockResponse:
    status: int
    body: dict[str, Any]


class Transport(Protocol):
    name: str

    def request(
        self, method: str, path: str, *, key: str, timeout: float, json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MockResponse: ...  # fmt: skip


def _decode(response: httpx.Response) -> MockResponse:
    try:
        body = response.json()
    except ValueError:
        body = {}
    return MockResponse(response.status_code, body if isinstance(body, dict) else {"items": body})


class HttpTransport:
    name = "http"

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), follow_redirects=False, trust_env=False)

    def request(
        self, method: str, path: str, *, key: str, timeout: float, json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MockResponse:  # fmt: skip
        try:
            response = self._client.request(method, path, json=json, params=params, headers={KEY_HEADER: key}, timeout=timeout)
        except httpx.TransportError as exc:  # timeouts, refused connections, protocol errors
            raise TransportError(type(exc).__name__) from exc
        return _decode(response)


_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="mock-inprocess")


class InProcessTransport:
    """Calls the mock ASGI app inside this process. A deadline stands in for the socket timeout."""

    name = "inprocess"

    def _call(self, method: str, path: str, key: str, json: dict[str, Any] | None, params: dict[str, Any] | None) -> MockResponse:
        from app.mocks.main import app as mock_app

        async def send() -> MockResponse:
            asgi = httpx.ASGITransport(app=mock_app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=asgi, base_url="http://mock.internal") as client:
                return _decode(await client.request(method, path, json=json, params=params, headers={KEY_HEADER: key}))

        return asyncio.run(send())  # a fresh event loop in this worker thread

    def request(
        self, method: str, path: str, *, key: str, timeout: float, json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> MockResponse:  # fmt: skip
        future = _POOL.submit(self._call, method, path, key, json, params)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TransportError("timeout") from exc
