from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import config
from .schema import metadata

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(config.DB_URL)
    return _engine


def init_db():
    metadata.create_all(get_engine())


def upsert(conn, table, rows: list[dict], chunk: int = 800) -> int:
    """SQLite upsert on primary key. Returns number of rows written."""
    if not rows:
        return 0
    pk = [c.name for c in table.primary_key.columns]
    written = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        stmt = sqlite_insert(table).values(batch)
        update_cols = {c.name: stmt.excluded[c.name] for c in table.columns if c.name not in pk}
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=pk, set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk)
        conn.execute(stmt)
        written += len(batch)
    return written
