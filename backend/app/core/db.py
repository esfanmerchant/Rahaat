"""Database sessions that carry the Row Level Security context.

The app connects as `rahat_app`, which neither owns the tables nor has BYPASSRLS. Postgres policies read
four transaction-local settings (`app.role`, `app.tenant_id`, `app.user_id`, `app.person_id`). They are set
at the start of every transaction, so they survive commits inside one request and never leak between
pooled connections. A session without a context sees no rows at all.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class RlsContext:
    role: str
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    person_id: UUID | None = None


# System context: pre-authentication lookups (login, refresh, API keys), the job dispatcher and the seed.
# Every use is explicit. Search for `system_session(` to review them all.
SYSTEM = RlsContext(role="system")

_RLS_KEY = "rls"
_SET_CONTEXT = text(
    "SELECT set_config('app.role', :role, true), set_config('app.tenant_id', :tenant_id, true), "
    "set_config('app.user_id', :user_id, true), set_config('app.person_id', :person_id, true)"
)

_engines: dict[str, Engine] = {}
_session_factory: sessionmaker[Session] = sessionmaker(expire_on_commit=False)


def get_engine() -> Engine:
    """Runtime engine: the low-privilege role that RLS applies to."""
    if "app" not in _engines:
        settings = get_settings()
        _engines["app"] = create_engine(
            settings.app_url(), pool_pre_ping=True, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow
        )
    return _engines["app"]


def get_owner_engine() -> Engine:
    """Table-owner engine. Migrations and the audit-tamper demo only; never used to serve requests."""
    if "owner" not in _engines:
        _engines["owner"] = create_engine(get_settings().owner_url(), pool_pre_ping=True, pool_size=1, max_overflow=2)
    return _engines["owner"]


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()


def open_session(ctx: RlsContext) -> Session:
    session = _session_factory(bind=get_engine())
    session.info[_RLS_KEY] = ctx
    return session


@event.listens_for(Session, "after_begin")
def _apply_rls_context(session: Session, transaction: Any, connection: Connection) -> None:
    ctx: RlsContext | None = session.info.get(_RLS_KEY)
    if ctx is None:
        return
    connection.execute(
        _SET_CONTEXT,
        {
            "role": ctx.role,
            "tenant_id": str(ctx.tenant_id) if ctx.tenant_id else "",
            "user_id": str(ctx.user_id) if ctx.user_id else "",
            "person_id": str(ctx.person_id) if ctx.person_id else "",
        },
    )


@contextlib.contextmanager
def session_scope(ctx: RlsContext) -> Iterator[Session]:
    """A session that commits on success and rolls back on any error."""
    session = open_session(ctx)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def system_session() -> contextlib.AbstractContextManager[Session]:
    return session_scope(SYSTEM)
