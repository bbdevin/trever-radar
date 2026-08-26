"""董監 OpenAPI parse (docs/34 §4.6 D1)."""
from __future__ import annotations

import unittest

from radar.providers.directors import (
    insider_numerator_shares,
    parse_director_rows,
    parse_roc_ym,
)


SAMPLE_TWSE = [
    {
        "出表日期": "1150820",
        "資料年月": "11507",
        "公司代號": "2330",
        "公司名稱": "台積電",
        "職稱": "董事長",
        "姓名": "魏哲家",
        "選任時持股 ": "6392834",
        "目前持股": "7452349",
        "設質股數": "1600000",
        "設質股數佔持股比例": "21.46%",
        "內部人關係人目前持股合計": "700261",
        "內部人關係人設質股數": "0",
        "內部人關係人設質比例": "0.00%",
    }
]


class TestDirectorParse(unittest.TestCase):
    def test_roc_ym(self):
        self.assertEqual(parse_roc_ym("11507"), "2026-07")
        self.assertEqual(parse_roc_ym("202607"), "2026-07")

    def test_parse_row(self):
        rows = parse_director_rows(SAMPLE_TWSE, "twse")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r.stock_id, "2330")
        self.assertEqual(r.as_of_ym, "2026-07")
        self.assertEqual(r.name, "魏哲家")
        self.assertEqual(r.shares, 7452349)
        self.assertEqual(r.shares_at_election, 6392834)
        self.assertEqual(r.pledged_shares, 1600000)
        self.assertAlmostEqual(r.pledged_pct or 0, 21.46)

    def test_insider_numerator_dedup_plus_related(self):
        # 兼職雙列同名只計一次；每人 = 目前 + 關係人
        rows = [
            ("林映誌", 3_588_439, 950_533),
            ("林映誌", 3_588_439, 950_533),  # 董事＋副總
            ("林於晃", 8_612_089, 5_687_897),
        ]
        self.assertEqual(
            insider_numerator_shares(rows),
            3_588_439 + 950_533 + 8_612_089 + 5_687_897,
        )


if __name__ == "__main__":
    unittest.main()
