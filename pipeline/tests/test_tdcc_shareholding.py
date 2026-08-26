"""TDCC shareholding parse + threshold aggregate (docs/34 B1)."""
from __future__ import annotations

import unittest

from radar.compute.shareholding import (
    aggregate_all_thresholds,
    aggregate_retail,
    aggregate_threshold,
)
from radar.providers.tdcc_shareholding import parse_tdcc_csv, parse_tdcc_date, parse_tier


SAMPLE = """資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%
1140815,2330,12,100,400000000,10.0
1140815,2330,13,50,300000000,8.0
1140815,2330,14,20,200000000,6.0
1140815,2330,15,5,100000000,4.0
1140815,2330,16,10,1,0.01
1140815,2330,17,合計,999,999,100.0
1140815,0050,15,3,50000000,2.5
"""


class TestTdccParse(unittest.TestCase):
    def test_roc_date(self):
        self.assertEqual(parse_tdcc_date("1140815"), "2025-08-15")

    def test_western_date(self):
        self.assertEqual(parse_tdcc_date("20250815"), "2025-08-15")

    def test_tier_skip_total(self):
        self.assertIsNone(parse_tier("16"))
        self.assertIsNone(parse_tier("17"))
        self.assertIsNone(parse_tier("合計"))
        self.assertEqual(parse_tier("15"), 15)

    def test_parse_csv(self):
        rows = parse_tdcc_csv(SAMPLE)
        self.assertEqual(len(rows), 5)  # 4 for 2330 + 1 for 0050; skip 16/17
        tsmc = [r for r in rows if r.stock_id == "2330"]
        self.assertEqual({r.tier for r in tsmc}, {12, 13, 14, 15})
        self.assertEqual(tsmc[0].as_of, "2025-08-15")


class TestThreshold(unittest.TestCase):
    def test_1000_is_tier15_only(self):
        tiers = {
            12: (100, 1, 10.0),
            13: (50, 1, 8.0),
            14: (20, 1, 6.0),
            15: (5, 1, 4.0),
        }
        self.assertEqual(aggregate_threshold(tiers, 1000), {"holders": 5, "shares_pct": 4.0})
        self.assertEqual(aggregate_threshold(tiers, 400)["holders"], 175)
        self.assertAlmostEqual(aggregate_threshold(tiers, 400)["shares_pct"], 28.0)

    def test_all(self):
        rows = [(12, 100, 1, 10.0), (13, 50, 1, 8.0), (14, 20, 1, 6.0), (15, 5, 1, 4.0)]
        out = aggregate_all_thresholds(rows)
        self.assertEqual(out["1000"]["holders"], 5)
        self.assertEqual(out["800"]["holders"], 25)

    def test_retail_under_400(self):
        tiers = {
            1: (1000, 1, 5.0),
            11: (200, 1, 12.0),
            12: (100, 1, 10.0),
            15: (5, 1, 4.0),
        }
        retail = aggregate_retail(tiers)
        self.assertEqual(retail["holders"], 1200)
        self.assertAlmostEqual(retail["shares_pct"], 17.0)


if __name__ == "__main__":
    unittest.main()
