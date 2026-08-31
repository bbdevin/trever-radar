"""Fail-closed helpers for report-only reads of the configured SQLite DB.

The connection URI uses ``mode=ro`` so reports see the writer's latest WAL
frames without changing database or WAL content. SQLite may update ``-shm``
reader-lock/read-mark coordination metadata while doing so; that is required
for a correct concurrent WAL read and is not a database-content write.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import NullPool

from .. import config


_SQLITE_HEADER = b"SQLite format 3\x00"


def configured_sqlite_db_path(*, report_name: str) -> Path:
    """Return an existing physical SQLite file without creating any path."""
    try:
        url = make_url(config.DB_URL)
    except Exception as exc:
        raise ValueError(f"{report_name} requires a physical SQLite DB_URL") from exc

    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError(f"{report_name} requires a physical SQLite DB_URL")

    db_path = Path(url.database).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"configured SQLite database does not exist: {db_path}")

    try:
        with db_path.open("rb") as handle:
            header = handle.read(len(_SQLITE_HEADER))
    except OSError as exc:
        raise RuntimeError(f"cannot read configured SQLite database: {db_path}") from exc
    if header != _SQLITE_HEADER:
        raise ValueError(f"configured database is not a valid SQLite file: {db_path}")
    return db_path


def get_read_only_sqlite_engine(
    *, report_name: str, required_tables: Iterable[str],
) -> Engine:
    """Open an existing SQLite DB through URI ``mode=ro`` and validate its schema.

    The validation query is deliberately a SELECT against ``sqlite_master``;
    this helper never initialises, migrates, or changes SQLite pragmas.
    """
    db_path = configured_sqlite_db_path(report_name=report_name)
    db_uri = db_path.as_uri() + "?mode=ro"
    engine = create_engine(
        "sqlite+pysqlite://",
        creator=lambda: sqlite3.connect(db_uri, uri=True, check_same_thread=False),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as conn:
            present = {
                row[0]
                for row in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )).fetchall()
            }
    except Exception as exc:
        engine.dispose()
        raise RuntimeError(
            f"{report_name} cannot read configured SQLite database: {db_path}"
        ) from exc

    missing = sorted(set(required_tables) - present)
    if missing:
        engine.dispose()
        raise RuntimeError(
            f"{report_name} cannot run: missing required SQLite table(s): {', '.join(missing)}"
        )
    return engine


def safe_report_output_path(
    out: str | Path, *, report_name: str, path_option: str = "--out",
) -> Path:
    """Resolve output and refuse the DB, its aliases, or SQLite sidecars.

    A pre-existing hardlink can name the same inode without resolving to the
    configured path, so every existing protected file is checked with
    ``samefile`` as well.
    """
    db_path = configured_sqlite_db_path(report_name=report_name)
    out_path = Path(out)
    candidate = out_path.expanduser()
    resolved = candidate.resolve()
    sidecars = tuple(
        db_path.with_name(f"{db_path.name}{suffix}")
        for suffix in ("-wal", "-shm", "-journal")
    )
    if resolved == db_path or resolved in sidecars:
        raise ValueError(
            f"{report_name} {path_option} must not be the configured SQLite database or its sidecar"
        )
    if candidate.exists():
        protected = (db_path, *(path for path in sidecars if path.exists()))
        for protected_path in protected:
            try:
                aliases_protected = os.path.samefile(candidate, protected_path)
            except OSError as exc:
                raise ValueError(f"{report_name} cannot safely verify {path_option} path") from exc
            if aliases_protected:
                kind = "database" if protected_path == db_path else "sidecar"
                raise ValueError(
                    f"{report_name} {path_option} must not alias the configured SQLite {kind}"
                )
    return out_path
