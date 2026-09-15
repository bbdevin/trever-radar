"""Equivalence proof for the branch-stats stock_id query rewrite.

compute_branch_stats.py and branch_ranking_v2_shadow.py both used to compute
"個股(排除指數)中至少有一筆 branch_trades 的 stock_id" via
``SELECT DISTINCT b.stock_id FROM branch_trades b JOIN stocks s ...``, which
forces SQLite to scan the whole 28.5M-row branch_trades_raw table. The
rewrite drives off ``stocks`` (~2,000 rows) with an ``EXISTS`` subquery
instead, which seeks branch_trades_raw by its (stock_id, ...) leading PK
column.

This test builds a fixture DB that exercises every branch of the WHERE
clause — a stock with branch rows, a stock with no branch rows, an
index-named stock with branch rows, a non-'stock' type row with branch
rows, and a branch row dated after the as_of cutoff — and asserts the old
query (kept here as a literal oracle) and the new query return the exact
same list in the exact same order.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema

# --- oracles: the exact SQL that used to run at each call site -------------

OLD_QUERY_SITE1 = """
    SELECT DISTINCT b.stock_id
    FROM branch_trades b
    JOIN stocks s ON s.id = b.stock_id
    WHERE s.type = 'stock' AND s.name NOT LIKE '%指%'
    ORDER BY b.stock_id
"""

NEW_QUERY_SITE1 = """
    SELECT s.id FROM stocks s
    WHERE s.type = 'stock' AND s.name NOT LIKE '%指%'
      AND EXISTS (SELECT 1 FROM branch_trades b WHERE b.stock_id = s.id)
    ORDER BY s.id
"""

OLD_QUERY_SITE2 = """
    SELECT DISTINCT b.stock_id
    FROM branch_trades b
    JOIN stocks s ON s.id = b.stock_id
    WHERE s.type = 'stock' AND s.name NOT LIKE '%指%' AND b.date <= :as_of
    ORDER BY b.stock_id
"""

NEW_QUERY_SITE2 = """
    SELECT s.id FROM stocks s
    WHERE s.type = 'stock' AND s.name NOT LIKE '%指%'
      AND EXISTS (SELECT 1 FROM branch_trades b WHERE b.stock_id = s.id AND b.date <= :as_of)
    ORDER BY s.id
"""


class StockIdsSeekRewriteTests(unittest.TestCase):
    AS_OF = "2026-06-15"
    AFTER_AS_OF = "2026-06-20"

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        config.DB_URL = "sqlite:///" + (self.tmp_path / "seek.db").as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()

        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                # 有分點資料的個股 —— 應該出現在結果中。
                {"id": "1101", "name": "台泥", "market": "twse", "type": "stock"},
                # 沒有任何分點資料的個股 —— 不應出現。
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock"},
                # 名稱含「指」的指數型商品,即使有分點資料也應被排除。
                {"id": "0050", "name": "元大台灣50指數", "market": "twse", "type": "stock"},
                # 非 'stock' 型別(如權證/ETN),即使有分點資料也應被排除。
                {"id": "03001", "name": "權證甲", "market": "twse", "type": "warrant"},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "b1", "branch_name": "分點一"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": "1101", "date": self.AS_OF, "branch_id": 1,
                 "buy_lots": 10, "sell_lots": 0, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "0050", "date": self.AS_OF, "branch_id": 1,
                 "buy_lots": 10, "sell_lots": 0, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "03001", "date": self.AS_OF, "branch_id": 1,
                 "buy_lots": 10, "sell_lots": 0, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                # 分點資料日期在 as_of 之後 —— site 2 的日期條件必須排除它,
                # 而它是本股唯一一筆分點資料,故排除後這檔股票不應出現。
                {"stock_id": "1216", "date": self.AFTER_AS_OF, "branch_id": 1,
                 "buy_lots": 10, "sell_lots": 0, "net_lots": 10, "pct": 1.0, "source": "fixture"},
            ])
            conn.execute(schema.stocks.insert(), {
                "id": "1216", "name": "統一", "market": "twse", "type": "stock",
            })

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def test_site1_rewrite_matches_old_query(self):
        with db.get_engine().connect() as conn:
            old = [r[0] for r in conn.execute(text(OLD_QUERY_SITE1)).fetchall()]
            new = [r[0] for r in conn.execute(text(NEW_QUERY_SITE1)).fetchall()]
        # 只有 1101 有分點資料、type='stock' 且名稱不含「指」;1216 也符合
        # (它有一筆分點資料,不受 site1 的日期條件影響)。
        self.assertEqual(old, ["1101", "1216"])
        self.assertEqual(new, old)

    def test_site2_rewrite_matches_old_query_with_date_predicate(self):
        params = {"as_of": self.AS_OF}
        with db.get_engine().connect() as conn:
            old = [r[0] for r in conn.execute(text(OLD_QUERY_SITE2), params).fetchall()]
            new = [r[0] for r in conn.execute(text(NEW_QUERY_SITE2), params).fetchall()]
        # 1216 的唯一分點資料晚於 as_of,日期條件把它濾掉;只剩 1101。
        self.assertEqual(old, ["1101"])
        self.assertEqual(new, old)


if __name__ == "__main__":
    unittest.main()
