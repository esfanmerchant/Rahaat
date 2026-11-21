"""Prometheus metrics. Labels carry route templates and status classes only, never identifiers."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter("rahat_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "rahat_http_request_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
DECISIONS = Counter("rahat_decisions_total", "Decisions by route", ["route"])
ACCESS_DENIED = Counter("rahat_access_denied_total", "Requests blocked by policy or consent", ["reason"])
AUTH_EVENTS = Counter("rahat_auth_events_total", "Authentication events", ["event"])

METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, f"{status // 100}xx").inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


def render() -> bytes:
    return generate_latest()
