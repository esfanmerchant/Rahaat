"""Live security probes: fixed, read-only SQL run as the runtime role, so anyone can watch the database refuse.

Each probe opens its own connection of the low-privilege role `rahat_app`, sets (or deliberately does not set)
the Row Level Security context, tries one thing and rolls back. Nothing is ever committed. The statements are
constants; no input from the request reaches the SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine

_SET_CONTEXT = text(
    "SELECT set_config('app.role', :role, true), set_config('app.tenant_id', :tenant, true), set_config('app.user_id', :user, true)"
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    name: str
    claim: str
    passed: bool
    sql: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _first_line(exc: DBAPIError) -> str:
    original = getattr(exc, "orig", None) or exc
    return str(original).strip().splitlines()[0][:200]


def _run(probe: Callable[[Connection], ProbeResult]) -> ProbeResult:
    with get_engine().connect() as conn:
        transaction = conn.begin()
        try:
            return probe(conn)
        finally:
            transaction.rollback()


def _refused(conn: Connection, sql: str) -> tuple[bool, str]:
    nested = conn.begin_nested()
    try:
        conn.execute(text(sql))
    except DBAPIError as exc:
        nested.rollback()
        return True, _first_line(exc)
    nested.rollback()
    return False, "the statement was accepted"


def runtime_role(conn: Connection) -> ProbeResult:
    sql = "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    user, superuser, bypass = conn.execute(text(sql)).one()
    owns = conn.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user")).scalar_one()
    return ProbeResult("runtime_role", "The API connects as a role that is not superuser, has no BYPASSRLS and owns no table.",
                       not superuser and not bypass and owns == 0, sql,
                       {"role": user, "superuser": superuser, "bypassrls": bypass, "tables_owned": owns})  # fmt: skip


def no_context_sees_nothing(conn: Connection) -> ProbeResult:
    # The app only ever sets the context per transaction; clear it explicitly anyway, so the probe never depends
    # on what an earlier user of this pooled connection did.
    conn.execute(_SET_CONTEXT, {"role": "", "tenant": "", "user": ""})
    sql = ("SELECT (SELECT count(*) FROM persons), (SELECT count(*) FROM cases), (SELECT count(*) FROM audit_log), "
           "(SELECT count(*) FROM api_keys), (SELECT count(*) FROM users)")  # fmt: skip
    counts = dict(zip(("persons", "cases", "audit_log", "api_keys", "users"), conn.execute(text(sql)).one(), strict=True))
    return ProbeResult("no_context_sees_nothing", "A connection that has not said who it is sees no rows at all.",
                       not any(counts.values()), sql, {"rows_visible": counts})  # fmt: skip


def other_departments_invisible(tenant_id: UUID, user_id: UUID, role: str) -> Callable[[Connection], ProbeResult]:
    def probe(conn: Connection) -> ProbeResult:
        conn.execute(_SET_CONTEXT, {"role": role, "tenant": str(tenant_id), "user": str(user_id)})
        sql = ("SELECT (SELECT count(*) FROM cases WHERE tenant_id <> app_tenant_id()), "
               "(SELECT count(*) FROM audit_log WHERE tenant_id <> app_tenant_id()), "
               "(SELECT count(*) FROM api_keys WHERE tenant_id <> app_tenant_id())")  # fmt: skip
        cases, audit_rows, keys = conn.execute(text(sql)).one()
        return ProbeResult("other_departments_invisible",
                           "Raw SQL in your department's context cannot see another department's rows, even when it asks for them.",
                           cases == 0 and audit_rows == 0 and keys == 0, sql,
                           {"other_departments_cases": cases, "other_departments_audit_rows": audit_rows,
                            "other_departments_api_keys": keys})  # fmt: skip

    return probe


def rls_cannot_be_disabled(conn: Connection) -> ProbeResult:
    sql = "ALTER TABLE persons DISABLE ROW LEVEL SECURITY"
    refused, message = _refused(conn, sql)
    return ProbeResult("rls_cannot_be_disabled", "The API's role cannot switch Row Level Security off.", refused, sql, {"database_said": message})


def row_security_off_is_refused(conn: Connection) -> ProbeResult:
    conn.execute(text("SET LOCAL row_security = off"))
    sql = "SELECT count(*) FROM cases"
    refused, message = _refused(conn, sql)
    return ProbeResult("row_security_off_is_refused", "Asking Postgres to skip the policies makes the query fail instead of showing rows.",
                       refused, f"SET LOCAL row_security = off; {sql}", {"database_said": message})  # fmt: skip


def audit_is_append_only(conn: Connection) -> ProbeResult:
    sql = "UPDATE audit_log SET reason = reason WHERE false"
    refused, message = _refused(conn, sql)
    return ProbeResult("audit_is_append_only", "The API's role can only add audit rows, never change or delete them.", refused, sql,
                       {"database_said": message})  # fmt: skip


def consent_function_is_safe(conn: Connection) -> ProbeResult:
    sql = ("SELECT p.prosecdef, pg_get_userbyid(p.proowner), coalesce(array_to_string(p.proconfig, ','), '') "
           "FROM pg_proc p WHERE p.proname = 'app_can_read_person'")  # fmt: skip
    definer, owner, config = conn.execute(text(sql)).one()
    path = next((c.removeprefix("search_path=") for c in config.split(",") if c.startswith("search_path=")), "")
    pg_temp_last = path.replace(" ", "").endswith("pg_temp")
    return ProbeResult("consent_function_is_safe",
                       "The consent check runs as its owner, which the API's role is not, with a search path that a temporary table "
                       "cannot hijack (pg_temp named last).",
                       bool(definer) and owner != "rahat_app" and pg_temp_last, sql,
                       {"security_definer": definer, "owner": owner, "search_path": path, "pg_temp_last": pg_temp_last})  # fmt: skip


def run_all(*, tenant_id: UUID, user_id: UUID, role: str) -> list[ProbeResult]:
    probes: list[Callable[[Connection], ProbeResult]] = [
        runtime_role, no_context_sees_nothing, other_departments_invisible(tenant_id, user_id, role), rls_cannot_be_disabled,
        row_security_off_is_refused, audit_is_append_only, consent_function_is_safe,
    ]  # fmt: skip
    return [_run(probe) for probe in probes]
