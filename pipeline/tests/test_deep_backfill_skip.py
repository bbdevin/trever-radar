"""Regression tests for the deep_backfill freshness check.

The old predicate asked whether a stock's earliest stored row was before
2010-01-01. A stock that listed after 2010 can never satisfy that, so every
post-2010 listing — and nearly every ETF — was re-fetched from IPO every single
night, for ever. Production showed it: the "already deep" figure never grew,
and ~1,100 FinMind requests at --sleep 6.5 held the database lock for ~2 hours
a night writing rows that already existed.

The check now asks whether the earliest row predates DEEP_HISTORY_BEFORE. No
daily importer writes dates that old, so such a row can only have come from an
earlier since-IPO fetch. These tests run deep_backfill against a throwaway
SQLite DB with FinMind monkeypatched, so they never make a network request.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import DEEP_HISTORY_BEFORE, deep_backfill, is_deep_enough


class DeepEnoughPredicateTests(unittest.TestCase):
    """The predicate alone, so a failure says which half is wrong."""

    def test_post_2010_pre_2026_listing_counts_as_deep(self):
        # The whole bug in one case: under the old "< 2010-01-01" rule this was
        # False, and the stock was re-fetched from IPO every night.
        self.assertTrue(is_deep_enough("2015-04-21"))

    def test_pre_2010_listing_counts_as_deep(self):
        self.assertTrue(is_deep_enough("2008-03-11"))

    def test_listing_from_the_current_year_is_not_deep(self):
        self.assertFalse(is_deep_enough("2026-02-09"))

    def test_no_rows_at_all_is_not_deep(self):
        self.assertFalse(is_deep_enough(None))

    def test_boundary_is_exclusive(self):
        self.assertFalse(is_deep_enough(DEEP_HISTORY_BEFORE))


class DeepBackfillSkipTests(unittest.TestCase):
    """Same four cases end-to-end: who actually costs a FinMind request."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed(self, stock_id: str, earliest: str | None):
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": stock_id, "name": "x", "market": "twse",
                 "type": "stock", "is_active": 1}])
            if earliest:
                conn.execute(schema.daily_prices.insert(), [
                    {"stock_id": stock_id, "date": earliest, "close": 10,
                     "volume": 100, "turnover": 1000},
                    {"stock_id": stock_id, "date": "2026-09-04", "close": 11,
                     "volume": 100, "turnover": 1000},
                ])

    def _run(self, ids=None, all_stocks=False):
        fetched = []

        def fake_history(sid):
            fetched.append(sid)
            return [{"stock_id": sid, "date": "2026-03-02", "open": 1, "high": 1,
                     "low": 1, "close": 1, "volume": 1, "turnover": 1,
                     "transactions": 1}]

        with patch("radar.providers.finmind.fetch_daily_history",
                   side_effect=fake_history):
            result = deep_backfill(ids=ids, all_stocks=all_stocks, sleep_s=0)
        return fetched, result

    def test_a_2015_listing_is_skipped(self):
        self._seed("1101", "2015-04-21")
        fetched, result = self._run(all_stocks=True)
        self.assertEqual(fetched, [], "a stock with 2015 history has already been "
                                      "deep-filled; re-fetching it is pure waste")
        self.assertEqual(result["skipped"], 1)

    def test_a_2008_listing_is_skipped(self):
        self._seed("2330", "2008-03-11")
        fetched, result = self._run(all_stocks=True)
        self.assertEqual(fetched, [])
        self.assertEqual(result["skipped"], 1)

    def test_a_2026_listing_is_still_fetched(self):
        self._seed("00999", "2026-02-09")
        fetched, result = self._run(all_stocks=True)
        self.assertEqual(fetched, ["00999"], "this year's listings carry no proof "
                                             "of a since-IPO fetch and must run")
        self.assertEqual(result["done"], 1)
        self.assertEqual(result["skipped"], 0)

    def test_a_stock_with_no_rows_is_fetched(self):
        # No daily_prices rows, so the --all query never sees it; --ids does,
        # and min_date is None there, which must not count as deep.
        self._seed("6666", None)
        fetched, result = self._run(ids=["6666"])
        self.assertEqual(fetched, ["6666"])
        self.assertEqual(result["skipped"], 0)

    def test_mixed_universe_only_pays_for_the_new_listings(self):
        self._seed("2330", "2008-03-11")
        self._seed("1101", "2015-04-21")
        self._seed("00999", "2026-02-09")
        fetched, result = self._run(all_stocks=True)
        self.assertEqual(fetched, ["00999"])
        self.assertEqual((result["done"], result["skipped"], result["failed"]),
                         (1, 2, 0))

    def test_the_repeat_fetch_never_touches_adj_factor(self):
        """Severity check: the waste is cost, not corruption.

        FinMind rows carry only OHLC/volume/turnover/transactions, and upsert
        updates only the columns a row carries, so a redundant deep fetch leaves
        adjustment work alone. If this ever fails, the nightly re-fetch is
        actively destroying data rather than merely burning the lock.
        """
        self._seed("00999", "2026-02-09")
        # the row the fake fetch will rewrite, carrying a computed adjustment
        with db.get_engine().begin() as conn:
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "00999", "date": "2026-03-02", "close": 5,
                 "adj_factor": 0.87}])
        self._run(ids=["00999"])
        with db.get_engine().connect() as conn:
            adj = conn.execute(schema.daily_prices.select()
                               .where(schema.daily_prices.c.stock_id == "00999")
                               .where(schema.daily_prices.c.date == "2026-03-02")
                               ).mappings().one()["adj_factor"]
        self.assertEqual(adj, 0.87, "a redundant deep fetch must not clobber adj_factor")


if __name__ == "__main__":
    unittest.main()
