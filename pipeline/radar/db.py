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

    theme_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(themes)").fetchall()}
    theme_additions = {
        "source_updated_at": "TEXT",
        "data_date": "TEXT",
        "status": "TEXT",
    }
    for name, sql_type in theme_additions.items():
        if name not in theme_cols:
            conn.exec_driver_sql(f"ALTER TABLE themes ADD COLUMN {name} {sql_type}")

    profile_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(company_profiles)").fetchall()}
    profile_additions = {
        "industry_code": "TEXT",
        "transfer_agent": "TEXT",
        "transfer_agent_phone": "TEXT",
        "transfer_agent_address": "TEXT",
        "source": "TEXT",
        "source_updated_at": "TEXT",
    }
    for name, sql_type in profile_additions.items():
        if name not in profile_cols:
            conn.exec_driver_sql(f"ALTER TABLE company_profiles ADD COLUMN {name} {sql_type}")

    margin_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(daily_margins)").fetchall()}
    margin_additions = {
        "margin_buy": "INTEGER",
        "margin_sell": "INTEGER",
        "margin_repay": "INTEGER",
        "short_buy": "INTEGER",
        "short_sell": "INTEGER",
        "short_repay": "INTEGER",
    }
    for name, sql_type in margin_additions.items():
        if name not in margin_cols:
            conn.exec_driver_sql(f"ALTER TABLE daily_margins ADD COLUMN {name} {sql_type}")

    # 分點隔日沖改版:pooled 比率 → 配對比例。舊快照的這些欄位維持 NULL,
    # 該 NULL 就是版本標記,用來區分 pooled 時代與新版的 branch_rankings 快照。
    rank_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(branch_rankings)").fetchall()}
    rank_additions = {
        "matured_samples": "INTEGER",
        "daytrade_pairs_determined": "INTEGER",
        "daytrade_pairs_flagged": "INTEGER",
    }
    for name, sql_type in rank_additions.items():
        if name not in rank_cols:
            conn.exec_driver_sql(f"ALTER TABLE branch_rankings ADD COLUMN {name} {sql_type}")

    bss_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(branch_stock_stats)").fetchall()}
    bss_additions = {
        "daytrade_obs": "INTEGER",
        "daytrade_paybacks": "INTEGER",
    }
    for name, sql_type in bss_additions.items():
        if name not in bss_cols:
            conn.exec_driver_sql(f"ALTER TABLE branch_stock_stats ADD COLUMN {name} {sql_type}")

    view_check = conn.exec_driver_sql("SELECT type FROM sqlite_master WHERE name='branch_trades'").scalar()
    if view_check == 'table':
        conn.exec_driver_sql("ALTER TABLE branch_trades RENAME TO branch_trades_old")
        conn.exec_driver_sql("INSERT OR IGNORE INTO branch_dim (branch_key, broker_id, branch_name) SELECT DISTINCT branch_key, broker_id, branch_name FROM branch_trades_old")
        conn.exec_driver_sql("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, net_lots, pct, source) SELECT o.stock_id, o.date, d.id, o.buy_lots, o.sell_lots, o.net_lots, o.pct, o.source FROM branch_trades_old o JOIN branch_dim d ON o.branch_key = d.branch_key")
        conn.exec_driver_sql("DROP TABLE branch_trades_old")
    
    if view_check != 'view':
        conn.exec_driver_sql("""
            CREATE VIEW branch_trades AS 
            SELECT r.stock_id, r.date, d.branch_key, d.broker_id, d.branch_name, r.buy_lots, r.sell_lots, r.net_lots, r.pct, r.source 
            FROM branch_trades_raw r 
            JOIN branch_dim d ON r.branch_id = d.id
        """)


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
