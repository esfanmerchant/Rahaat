"""Per-request context shared by logging, errors and the audit log."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")


def current_request_id() -> str:
    return request_id_var.get()


def current_client_ip() -> str:
    return client_ip_var.get()


# Set per request by the middleware when jobs run inline (serverless). The holder is a mutable dict because a sync
# endpoint runs in a worker thread whose context changes never reach the middleware, but a shared object does.
jobs_holder_var: ContextVar[dict[str, bool] | None] = ContextVar("jobs_holder", default=None)


def note_job_enqueued() -> None:
    holder = jobs_holder_var.get()
    if holder is not None:
        holder["enqueued"] = True
