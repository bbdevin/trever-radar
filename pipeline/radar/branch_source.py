"""FROM clause for market-wide, date-sliced reads of branch trades (docs/43).

After the WITHOUT ROWID conversion `branch_trades_raw` is clustered by stock, so a
date window across the whole market must come from the covering, date-contiguous
index `ix_branch_trades_raw_date_cover`.  With planner statistics (ANALYZE) SQLite
may prefer `branch_dim` + `ix_branch_trades_raw_branch` for these queries, which
touches far more pages; `INDEXED BY` pins the covering index.

The `branch_trades` view is `branch_trades_raw r JOIN branch_dim d ON r.branch_id = d.id`;
the clause below is that same join, so rows and values are identical.  On a
database without the covering index (the layout before the swap) it is the
plain join — same rows, no hint.

Columns: use r.stock_id, r.date, r.buy_lots, r.sell_lots, r.net_lots, r.pct and
d.branch_key, d.branch_name, d.broker_id.
"""
from __future__ import annotations

from sqlalchemy import text

COVER_INDEX = "ix_branch_trades_raw_date_cover"


def has_date_cover(conn) -> bool:
    return conn.execute(text(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :n"), {"n": COVER_INDEX}
    ).first() is not None


def date_window_from(conn) -> str:
    hint = f" INDEXED BY {COVER_INDEX}" if has_date_cover(conn) else ""
    return f"branch_trades_raw r{hint} JOIN branch_dim d ON r.branch_id = d.id"
