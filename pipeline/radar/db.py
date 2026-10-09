from itertools import groupby

from sqlalchemy import create_engine, event

from . import config
from .schema import BRANCH_STOCK_PCTILE_ADDED_COLUMNS, metadata

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # timeout: wait for locks instead of failing while backfill writes in parallel
        _engine = create_engine(config.DB_URL, connect_args={"timeout": 30})
        if _engine.dialect.name == "sqlite":
            # 64 MiB page cache per connection (default is 2 MiB). docs/43: the clustered
            # WITHOUT ROWID tables re-visit the same pages within one query; with 2 MiB they
            # are re-fetched from the OS each time.
            # synchronous=NORMAL only on WAL files (docs/44 D-P0.5): in WAL mode it
            # cannot corrupt the DB, a power loss can at most drop the last commits;
            # it saves an fsync per commit. temp_store / mmap stay at their defaults.
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA cache_size = -65536")
                mode = cur.execute("PRAGMA journal_mode").fetchone()
                if mode and str(mode[0]).lower() == "wal":
                    cur.execute("PRAGMA synchronous = NORMAL")
                cur.close()
    return _engine


def init_db():
    engine = get_engine()
    metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")  # readers don't block the writer
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")  # this conn opened before WAL
            _migrate_sqlite(conn)
            _normalize_branch_names(conn)


def _normalize_branch_names(conn) -> int:
    """branch_dim 的名稱套用 radar.branch_names.canonical_name(亂碼、改名)。冪等。

    2026-10-02:「(牛牛牛)亞」→「犇亞」、「台新-營業部」→「台新」。改的是名稱,
    不是代號或交易列;branch_trades view 讀這一欄,所以全系統同時換名。
    tracked_branches 以名稱為鍵,舊名在追蹤名單裡的一併改名(新名已在就移除舊名)。
    回傳改了幾列,0 代表已經是正規名稱(每一輪都會跑,通常是 0)。
    """
    from .branch_names import canonical_name

    tables = {r[0] for r in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "branch_dim" not in tables:
        return 0
    changed = 0
    for row_id, name in conn.exec_driver_sql("SELECT id, branch_name FROM branch_dim").fetchall():
        new = canonical_name(name)
        if new == name:
            continue
        conn.exec_driver_sql("UPDATE branch_dim SET branch_name = ? WHERE id = ?", (new, row_id))
        changed += 1
        if "tracked_branches" in tables:
            exists = conn.exec_driver_sql(
                "SELECT 1 FROM tracked_branches WHERE branch_name = ?", (new,)).fetchone()
            if exists:
                conn.exec_driver_sql("DELETE FROM tracked_branches WHERE branch_name = ?", (name,))
            else:
                conn.exec_driver_sql(
                    "UPDATE tracked_branches SET branch_name = ? WHERE branch_name = ?", (new, name))
    return changed


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

    # 大盤指數(docs/49 §12):§11 時建的表沒有台指期的兩欄;舊形狀的表 export 會直接擲例外。
    idx_cols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(market_indices)").fetchall()}
    if idx_cols:
        for name, sql_type in {"contract_month": "TEXT", "settlement": "REAL"}.items():
            if name not in idx_cols:
                conn.exec_driver_sql(f"ALTER TABLE market_indices ADD COLUMN {name} {sql_type}")

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

    # 窗口內重算的次日回吐計數。這張表每次計算都整份取代,所以既有檔案的舊列
    # 會維持 NULL 直到下一次 compute;NULL 代表「這份快照沒算」,不是 0 次。
    bspc_cols = {
        r[1] for r in
        conn.exec_driver_sql("PRAGMA table_info(branch_stock_pctile_counts)").fetchall()
    }
    bspc_additions = {
        "daytrade_obs": "INTEGER",
        "daytrade_paybacks": "INTEGER",
        "stock_daytrade_obs": "INTEGER",
        "stock_daytrade_paybacks": "INTEGER",
        # 2026-10-02:張數與長線派(120 日)欄位;欄名清單只有 schema.py 那一份。
        **{name: "INTEGER" for name in BRANCH_STOCK_PCTILE_ADDED_COLUMNS},
    }
    if bspc_cols:
        for name, sql_type in bspc_additions.items():
            if name not in bspc_cols:
                conn.exec_driver_sql(
                    f"ALTER TABLE branch_stock_pctile_counts ADD COLUMN {name} {sql_type}")

    # 契約乘數(股/口)。既有列一律維持 NULL,而 NULL 是「未知」不是 2,000:
    # docs/38 §2 R2b 規定乘數未知就否決該契約該日,不得假設標準型。
    fut_cols = {
        r[1] for r in
        conn.exec_driver_sql("PRAGMA table_info(futures_contracts)").fetchall()
    }
    if fut_cols and "contract_multiplier" not in fut_cols:
        conn.exec_driver_sql(
            "ALTER TABLE futures_contracts ADD COLUMN contract_multiplier INTEGER")

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


def _bulk_write(conn, table, rows: list[dict], chunk: int, on_conflict: bool) -> int:
    """Driver-level executemany: one prepared INSERT per run of rows sharing a key set.

    docs/44 D-P0.5: the old SQLAlchemy multi-VALUES statement (800 rows x N binds,
    compiled per chunk) dominated compute_all's write phase. SQLAlchemy is still
    used for exactly what it did for us before: each column type's bind processor
    (e.g. Boolean -> 0/1) and Python-side scalar defaults (stocks.is_active,
    import_logs.rows) for columns a row leaves out. Only *consecutive* rows with
    the same key set share a statement, so the original row order is kept (a later
    row for the same PK still wins).
    """
    if not rows:
        return 0
    dialect = conn.dialect
    quote = dialect.identifier_preparer.quote
    pk = [c.name for c in table.primary_key.columns]
    columns = table.c
    written = 0
    for key_set, run in groupby(rows, key=frozenset):
        run = list(run)
        unknown = key_set - set(columns.keys())
        if unknown:
            raise ValueError(f"{table.name}: unknown column(s) {sorted(unknown)}")
        names = list(run[0])
        defaults = []
        for col in columns:
            if col.name in key_set or col.default is None:
                continue
            if not col.default.is_scalar:
                raise NotImplementedError(f"{table.name}.{col.name}: non-scalar default")
            defaults.append((col.name, col.default.arg))
        insert_cols = names + [n for n, _ in defaults]
        sql = (f"INSERT INTO {quote(table.name)} ({', '.join(quote(n) for n in insert_cols)}) "
               f"VALUES ({', '.join('?' * len(insert_cols))})")
        if on_conflict:
            target = ", ".join(quote(n) for n in pk)
            update_cols = [n for n in names if n not in pk]
            if update_cols:
                sql += (f" ON CONFLICT ({target}) DO UPDATE SET "
                        + ", ".join(f"{quote(n)} = excluded.{quote(n)}" for n in update_cols))
            else:
                sql += f" ON CONFLICT ({target}) DO NOTHING"
        default_vals = tuple(v for _, v in defaults)
        procs = [(n, columns[n].type._cached_bind_processor(dialect)) for n in names]
        if any(p for _, p in procs):
            def params(r):
                return tuple(r[n] if p is None or r[n] is None else p(r[n])
                             for n, p in procs) + default_vals
        else:
            def params(r):
                return tuple([r[n] for n in names]) + default_vals
        for i in range(0, len(run), chunk):
            conn.exec_driver_sql(sql, [params(r) for r in run[i : i + chunk]])
        written += len(run)
    return written


def upsert(conn, table, rows: list[dict], chunk: int = 5000) -> int:
    """SQLite upsert on primary key. Returns number of rows written.

    Only columns present in the row dicts are updated on conflict: columns the
    import doesn't carry (e.g. stocks.industry) keep their existing values. Rows
    may carry different key sets; each row updates only its own columns.
    `chunk` = rows per executemany call (memory bound only, not semantics).
    """
    return _bulk_write(conn, table, rows, chunk, on_conflict=True)


def insert_many(conn, table, rows: list[dict], chunk: int = 5000) -> int:
    """Plain INSERT (a PK conflict raises), same executemany path as upsert()."""
    return _bulk_write(conn, table, rows, chunk, on_conflict=False)

