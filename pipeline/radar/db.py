from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from . import config
from .schema import metadata

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # timeout: wait for locks instead of failing while backfill writes in parallel
        _engine = create_engine(config.DB_URL, connect_args={"timeout": 30})
    return _engine


def init_db():
    engine = get_engine()
    metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")  # readers don't block the writer
            _migrate_sqlite(conn)


def _migrate_sqlite(conn):
    """Small additive migrations for existing SQLite files."""
    cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(daily_prices)").fetchall()}
    if "adj_factor" not in cols:
        conn.exec_driver_sql(
            "ALTER TABLE daily_prices ADD COLUMN adj_factor REAL NOT NULL DEFAULT 1.0"
        )

    score_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(daily_scores)").fetchall()}
    score_additions = {
        "branch_score": "INTEGER",
        "entry_date": "TEXT",
        "entry_price": "REAL",
        "fwd_1d": "REAL",
        "fwd_3d": "REAL",
        "fwd_5d": "REAL",
        "fwd_10d": "REAL",
        "fwd_20d": "REAL",
        "fwd_updated_at": "TEXT",
        "watch_price": "REAL",
        "stop_price": "REAL",
        "buy_concentration": "REAL",
        "concentration_avg20": "REAL",
    }
    for name, sql_type in score_additions.items():
        if name not in score_cols:
            conn.exec_driver_sql(f"ALTER TABLE daily_scores ADD COLUMN {name} {sql_type}")
            
    stock_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(stocks)").fetchall()}
    if "description" not in stock_cols:
        conn.exec_driver_sql("ALTER TABLE stocks ADD COLUMN description TEXT")


def upsert(conn, table, rows: list[dict], chunk: int = 800) -> int:
    """SQLite upsert on primary key. Returns number of rows written.

    Only columns present in the row dicts are updated on conflict — columns the
    import doesn't carry (e.g. stocks.industry) keep their existing values.
    """
    if not rows:
        return 0
    pk = [c.name for c in table.primary_key.columns]
    row_cols = [k for k in rows[0].keys() if k not in pk]
    written = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i : i + chunk]
        stmt = sqlite_insert(table).values(batch)
        update_cols = {name: stmt.excluded[name] for name in row_cols}
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=pk, set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk)
        conn.execute(stmt)
        written += len(batch)
    return written
