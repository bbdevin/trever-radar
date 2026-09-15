# -*- coding: utf-8 -*-
"""個股期貨資料層:對照表/行情/歷史 CSV 的解析,以及 futures_daily 的主鍵。

全部打在 tests/fixtures/ 的真實擷取上,不連網。
"""
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from radar import schema
from radar.providers import taifex
from radar.providers.taifex import (
    SESSION_AFTER_HOURS,
    SESSION_REGULAR,
    TaifexParseError,
    parse_daily_report,
    parse_history_csv,
    parse_stock_list,
    split_stock_futures,
)

FIXTURES = Path(__file__).parent / "fixtures"
DAILY_JSON = FIXTURES / "taifex_daily_market_report_fut.json"
STOCK_LIST_HTML = FIXTURES / "taifex_stock_lists.html"
HISTORY_CSV = FIXTURES / "taifex_fut_history.csv"

# fixture 只留下這幾個對照商品 + 三個指數期貨,好讓 join 的切分看得見。
FIXTURE_LEFTOVER = ["MTX", "TE", "TX"]


def _daily():
    return parse_daily_report(DAILY_JSON.read_text(encoding="utf-8"))


def _contracts():
    return parse_stock_list(STOCK_LIST_HTML.read_text(encoding="utf-8"))


class StockListParsing(unittest.TestCase):
    def test_totals_row_is_not_a_contract(self):
        rows = _contracts()
        # 末列「標的合計數:」沒有商品代碼,必須被丟掉而不是變成一檔標的。
        self.assertTrue(rows)
        self.assertTrue(all(r.product_code and r.stock_id for r in rows))
        self.assertNotIn("F", {r.contract_code for r in rows})

    def test_markers_and_market(self):
        by_code = {r.contract_code: r for r in _contracts()}
        cc = by_code["CCF"]  # 2303 聯電:三個標記都是 ●,上市普通股
        self.assertEqual(cc.stock_id, "2303")
        self.assertEqual(cc.stock_name, "聯電")
        self.assertEqual(cc.market, "twse")
        self.assertTrue(cc.is_stock_future)
        self.assertTrue(cc.is_stock_option)
        self.assertTrue(cc.is_weekly_option)

        cb = by_code["CBF"]  # 2002 中鋼:週契約欄是空的
        self.assertTrue(cb.is_stock_option)
        self.assertFalse(cb.is_weekly_option)

        na = by_code["NAF"]  # 3105 穩懋:上櫃普通股
        self.assertEqual(na.market, "tpex")
        self.assertFalse(na.is_stock_option)

        ny = by_code["NYF"]  # 0050:上市 ETF 也算 twse
        self.assertEqual(ny.stock_id, "0050")
        self.assertEqual(ny.market, "twse")

    def test_one_stock_can_carry_two_contracts(self):
        # 1565 精華同時有 2,000 股的 MYF 與 100 股小型的 OMF,
        # 所以主鍵必須是契約代碼,不是 stock_id。
        rows = [r for r in _contracts() if r.stock_id == "1565"]
        self.assertEqual({r.contract_code for r in rows}, {"MYF", "OMF"})

    def test_missing_expected_header_raises(self):
        html = STOCK_LIST_HTML.read_text(encoding="utf-8").replace("證券代號", "XXXXX")
        with self.assertRaises(TaifexParseError):
            parse_stock_list(html)

    def test_only_the_product_table_is_picked(self):
        # fixture 保留了頁面上的兩張表;認錯表的話會解析出「類型:」那張篩選表。
        tables = taifex._collect_tables(STOCK_LIST_HTML.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(tables), 2)
        picked = taifex._pick_product_table(tables)
        self.assertIn("商品代碼", "".join(taifex._text(c) for c in picked[0]))


class DailyReportParsing(unittest.TestCase):
    def test_join_rule_splits_stock_futures_from_the_rest(self):
        daily, contracts = _daily(), _contracts()
        kept, leftover = split_stock_futures(daily, contracts)
        mapped = {c.contract_code for c in contracts}
        feed = {r.contract_code for r in daily}
        # 對照表每一列都對得到行情代碼,一列都不落空 —— 這才是 join 規則,
        # 300-something / 80-something 那組數字只是某一天的當下值。
        self.assertEqual(mapped - feed, set())
        self.assertEqual(len(mapped & feed), len(mapped))
        self.assertEqual(leftover, FIXTURE_LEFTOVER)
        self.assertEqual({r.contract_code for r in kept}, mapped)
        self.assertLess(len(kept), len(daily))

    def test_both_sessions_survive_with_the_same_date(self):
        rows = [r for r in _daily() if r.contract_code == "CCF"]
        sessions = {r.session for r in rows}
        self.assertEqual(sessions, {SESSION_REGULAR, SESSION_AFTER_HOURS})
        # 盤後**不是**掛在次日:同一個 Date。
        self.assertEqual(len({r.date for r in rows}), 1)
        keys = [(r.contract_month, r.session) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_missing_numbers_are_none_not_zero(self):
        rows = {(r.contract_code, r.contract_month, r.session): r for r in _daily()}
        # 盤後列的結算價是 'NULL',未沖銷契約數是 '-' —— 兩種都是「沒有這個數字」。
        after = rows[("CCF", "202609", SESSION_AFTER_HOURS)]
        self.assertIsNone(after.settlement_price)
        self.assertIsNone(after.open_interest)
        # 而成交量 0 是事實,不可以變成 None。
        zero = [r for r in _daily() if r.volume == 0]
        self.assertTrue(zero)
        self.assertTrue(all(r.volume is not None for r in zero))

    def test_spread_month_is_kept_verbatim(self):
        months = {r.contract_month for r in _daily() if r.contract_code == "CCF"}
        self.assertIn("202609/202610", months)

    def test_iso_date(self):
        self.assertEqual({len(r.date) for r in _daily()}, {10})
        self.assertRegex(_daily()[0].date, r"^\d{4}-\d{2}-\d{2}$")

    def test_non_list_payload_raises(self):
        with self.assertRaises(TaifexParseError):
            parse_daily_report({"Contract": "CCF"})


class HistoryCsvParsing(unittest.TestCase):
    def test_big5_round_trips_a_chinese_contract_name(self):
        raw = HISTORY_CSV.read_bytes()
        # 表頭本身就是中文,Big5 解錯的話欄位認不出來,parse 會丟 TaifexParseError。
        self.assertIn("交易日期".encode("big5"), raw)
        rows = parse_history_csv(raw)
        self.assertTrue(rows)
        self.assertEqual({r.session for r in rows}, {SESSION_REGULAR, SESSION_AFTER_HOURS})

    def test_decode_error_fails_loud(self):
        with self.assertRaises(TaifexParseError):
            parse_history_csv("交易日期,契約\n2026/09/10,CCF\n".encode("utf-8"))

    def test_same_row_shape_as_the_daily_report(self):
        rows = parse_history_csv(HISTORY_CSV.read_bytes())
        self.assertEqual(type(rows[0]), type(_daily()[0]))
        dates = sorted({r.date for r in rows})
        self.assertEqual(dates, ["2026-09-10", "2026-09-11"])
        by_key = {(r.contract_code, r.date, r.contract_month, r.session): r for r in rows}
        self.assertEqual(len(by_key), len(rows))
        after = by_key[("CCF", "2026-09-10", "202609", SESSION_AFTER_HOURS)]
        self.assertIsNone(after.settlement_price)   # '-'
        self.assertIsNone(after.open_interest)      # '-'
        self.assertIsNotNone(after.last)

    def test_headerless_payload_raises(self):
        with self.assertRaises(TaifexParseError):
            parse_history_csv("a,b,c\r\n1,2,3\r\n".encode("big5"))


class FuturesDailyPrimaryKey(unittest.TestCase):
    def test_pk_rejects_a_duplicate_contract_date_month_session(self):
        engine = create_engine("sqlite://")
        schema.metadata.create_all(engine)
        row = {
            "contract_code": "CCF", "date": "2026-09-14",
            "contract_month": "202609", "session": SESSION_REGULAR,
            "open": 1.0, "high": 1.0, "low": 1.0, "last": 1.0, "change": 0.0,
            "volume": 10, "settlement_price": None, "open_interest": None,
        }
        with engine.begin() as conn:
            conn.execute(schema.futures_daily.insert().values(row))
            # 同一天、同一契約、同一月份,但不同時段 → 不同的列,必須插得進去。
            conn.execute(schema.futures_daily.insert().values(
                dict(row, session=SESSION_AFTER_HOURS)))
        with self.assertRaises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(schema.futures_daily.insert().values(row))


if __name__ == "__main__":
    unittest.main()
