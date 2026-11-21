"""Embedded PostgreSQL 16 with pgvector for development and tests.

No Docker and no account are needed: the `pgserver` package ships the binaries. The server keeps its
data in `<repo>/.devdb/pg16` (or in `RAHAT_DEVDB_DIR`, which the live demo on this PC uses) and stays
running between commands so they start fast. It listens on 127.0.0.1 only and trusts local connections.

    uv run python -m app.devdb url [name]   # print the URL of a database (default rahat_dev), creating it
    uv run python -m app.devdb stop         # stop the server
    uv run python -m app.devdb reset        # drop and recreate the dev database
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("RAHAT_DEVDB_DIR") or REPO_ROOT / ".devdb" / "pg16")


def _server():  # type: ignore[no-untyped-def]
    import logging

    import pgserver

    logging.getLogger("pgserver").setLevel(logging.WARNING)
    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
    return pgserver.get_server(DATA_DIR, cleanup_mode=None)


def server_uri() -> str:
    """URL of the maintenance database on the embedded server, starting it if needed."""
    return str(_server().get_uri())


def database_uri(name: str, *, recreate: bool = False) -> str:
    """URL of database `name`, created on first use. `recreate` drops it first."""
    import psycopg
    from psycopg import sql

    server = _server()
    with psycopg.connect(server.get_uri(), autocommit=True) as conn:
        if recreate:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return str(server.get_uri(database=name))


def drop_database(name: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(_server().get_uri(), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def drop_stale_databases(prefix: str, *, older_than_minutes: int = 20) -> None:
    """Remove databases left behind by test runs that were killed: only idle ones that are old enough."""
    import psycopg
    from psycopg import sql

    with psycopg.connect(_server().get_uri(), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT d.datname FROM pg_database d WHERE starts_with(d.datname, %s) "
            "AND NOT EXISTS (SELECT 1 FROM pg_stat_activity a WHERE a.datname = d.datname) "
            "AND (pg_stat_file('base/' || d.oid || '/PG_VERSION')).modification < now() - make_interval(mins => %s)",
            (prefix, older_than_minutes),
        ).fetchall()
        for (name,) in rows:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


def stop() -> None:
    import pgserver

    if (DATA_DIR / "postmaster.pid").exists():
        pgserver.pg_ctl(["stop", "-m", "fast"], pgdata=DATA_DIR)


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "url"
    if command == "url":
        print(database_uri(argv[2] if len(argv) > 2 else "rahat_dev"))
    elif command == "stop":
        stop()
        print("stopped")
    elif command == "reset":
        print(database_uri("rahat_dev", recreate=True))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
