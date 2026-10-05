"""TPEx margin/balance parser vs. a real captured response (raw-data parity).

Fixture = live https://www.tpex.org.tw/www/zh-tw/margin/balance?date=115/10/02
trimmed to 5 rows, cells unchanged. The parser used to look up 資買進/券賣出/…,
which TPEx never published, so margin_buy & co. were NULL for every OTC row.
"""
import json
from pathlib import Path
from unittest.mock import patch
import unittest

from radar.providers import tpex

FIXTURE = Path(__file__).parent / "fixtures" / "tpex_margin_balance_20261002.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TpexMarginParseTests(unittest.TestCase):
    def _rows(self, payload=None):
        with patch.object(tpex, "get_json", return_value=payload or _payload()) as get:
            rows = tpex.fetch_margin("20261002")
        self.assertEqual(get.call_args.args[1]["date"], "115/10/02")
        return {r.code: r for r in rows}

    def test_exact_values_match_source_row(self):
        rows = self._rows()
        self.assertEqual(sorted(rows), ["00411A", "1815", "3105", "3219", "8069"])
        # 3105 穩懋: 45,243 | 1,878 | 2,528 | 1 | 44,592 | … | 105,985 | 1,364 | 488 | 8 | 2 | 1,842
        r = rows["3105"]
        self.assertEqual(
            (r.margin_prev, r.margin_buy, r.margin_sell, r.margin_repay,
             r.margin_balance, r.margin_limit),
            (45243, 1878, 2528, 1, 44592, 105985),
        )
        self.assertEqual(
            (r.short_prev, r.short_sell, r.short_buy, r.short_repay, r.short_balance),
            (1364, 488, 8, 2, 1842),
        )
        # 00411A: thousand separators in buy column (1,345) and limit (103,019)
        r = rows["00411A"]
        self.assertEqual((r.margin_buy, r.margin_sell, r.margin_repay), (1345, 98, 17))
        self.assertEqual((r.margin_balance, r.margin_limit), (9519, 103019))
        self.assertEqual((r.short_sell, r.short_buy, r.short_repay), (0, 0, 0))
        # 3219 倚強科: non-empty 備註 column does not shift anything
        r = rows["3219"]
        self.assertEqual((r.margin_buy, r.margin_sell, r.margin_repay), (186, 189, 0))
        self.assertEqual((r.short_sell, r.short_buy, r.short_repay, r.short_balance),
                         (144, 19, 4, 1085))

    def test_every_row_satisfies_balance_identities(self):
        # Confirms the column semantics (券賣 = short_sell, 券買 = short_buy) and that
        # no flow field is NULL.
        for code, r in self._rows().items():
            with self.subTest(code=code):
                self.assertEqual(
                    r.margin_prev + r.margin_buy - r.margin_sell - r.margin_repay,
                    r.margin_balance)
                self.assertEqual(
                    r.short_prev + r.short_sell - r.short_buy - r.short_repay,
                    r.short_balance)

    def test_missing_flow_column_fails_loudly_instead_of_null(self):
        payload = _payload()
        payload["tables"][0]["fields"] = [
            "資買進" if f == "資買" else f for f in payload["tables"][0]["fields"]]
        with self.assertRaisesRegex(RuntimeError, "missing fields.*資買"):
            self._rows(payload)


if __name__ == "__main__":
    unittest.main()
