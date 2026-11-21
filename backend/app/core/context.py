"""Per-request context shared by logging, errors and the audit log."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")


def current_request_id() -> str:
    return request_id_var.get()


def current_client_ip() -> str:
    return client_ip_var.get()
