"""Alembic environment. Migrations run as the table owner (DATABASE_URL_OWNER), never as the app role."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from psycopg import sql
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import Connection

from app.core.config import APP_DB_ROLE, get_settings
from app.db import models  # noqa: F401  (registers every table on the metadata)
from app.db.base import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _sync_app_role_password(connection: Connection) -> None:
    """Keep the runtime role's password equal to APP_DB_PASSWORD on every run.

    Without this, a role created with one password and an environment configured with another would
    lock the app out of its own database.
    """
    exists = connection.exec_driver_sql("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_DB_ROLE,)).first()
    if not exists:
        return
    statement = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
        sql.Identifier(APP_DB_ROLE), sql.Literal(get_settings().app_db_password)
    )
    connection.connection.driver_connection.execute(statement)  # type: ignore[union-attr]


def run_migrations_online() -> None:
    engine = create_engine(get_settings().owner_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
            _sync_app_role_password(connection)
        connection.commit()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported; run against a database.")
run_migrations_online()
