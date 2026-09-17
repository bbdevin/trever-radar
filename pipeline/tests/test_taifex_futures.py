# -*- coding: utf-8 -*-
"""個股期貨資料層:對照表/行情/歷史 CSV 的解析,以及 futures_daily 的主鍵。

全部打在 tests/fixtures/ 的真實擷取上,不連網。
"""
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text as sql_text
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

# 商品表的 14 個表頭,原樣照抄官網(含 <br>)。乘數那一格的 <br> 正好切在詞中間,
# 「標準型證 券股數/ 受益權單位」這個斷法就是認欄位時真正要處理的東西。
_HEADERS = [
    "股票期貨、<br>選擇權<br>商品代碼", "標的證券", "證券代號", "標的證券<br>簡稱",
    "是否為<br>股票期貨<br>標的", "是否為<br>股票選擇權<br>標的",
    "是否為<br>股票選擇權週契約<br>標的",
    "上市普通股<br>標的證券", "上櫃普通股<br>標的證券",
    "上市ETF<br>標的證券", "上櫃ETF<br>標的證券",
    "標準型證<br>券股數/<br>受益權單位",
    "一般交易時段<br>交易時間<br>(期貨、選擇權契約)",
    "盤後交易時段<br>交易時間<br>(期貨契約)",
]


def _synthetic_page(rows, headers=None):
    """最小商品表:rows 是 14 格的字串序列(不足的格子自己補)。"""
    head = "".join(f"<th>{h}</th>" for h in (headers if headers is not None else _HEADERS))
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<html><body><table><tr>{head}</tr>{body}</table></body></html>"


def _row(product, stock_id, multiplier, mark_col=7):
    cells = [product, f"{product} 公司", stock_id, product, "●", "", "", "", "", "", "",
             multiplier, "8:45~13:45", "-"]
    cells[mark_col] = "◎"
    return cells


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

    def test_multiplier_is_read_per_row_not_inferred(self):
        by_code = {r.contract_code: r for r in _contracts()}
        # 標準型 2,000 股。
        self.assertEqual(by_code["CCF"].contract_multiplier, 2000)
        # ETF 期貨:受益權單位,官網實測 10,000(2026-09-17 全表:21 列 10,000、3 列 1,000)。
        self.assertEqual(by_code["NYF"].contract_multiplier, 10000)
        # 同一檔標的、兩個契約、兩個不同乘數 —— 這一條就是「逐列讀」與「由標的推」
        # 的分水嶺:任何從 stock_id 推乘數的寫法都過不了。
        self.assertEqual(by_code["MYF"].stock_id, by_code["OMF"].stock_id)
        self.assertEqual(by_code["MYF"].contract_multiplier, 2000)
        self.assertEqual(by_code["OMF"].contract_multiplier, 100)

    def test_multiplier_strips_thousands_separators(self):
        rows = parse_stock_list(_synthetic_page([_row("ZA", "9999", "1,000")]))
        self.assertEqual(rows[0].contract_multiplier, 1000)   # 小型 ETF 期貨
        self.assertIsInstance(rows[0].contract_multiplier, int)

    def test_unknown_multiplier_is_none_never_a_default(self):
        cases = ["", "-", "N/A", "未定", "0", "&nbsp;"]
        for cell in cases:
            with self.subTest(cell=cell):
                rows = parse_stock_list(_synthetic_page([_row("ZA", "9999", cell)]))
                # 契約本身仍然要在 —— 讀不到一個數字不該讓一整檔標的消失。
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].contract_code, "ZAF")
                # 而乘數是 None,不是 2,000:docs/38 R2b 要的是「不知道就否決」。
                self.assertIsNone(rows[0].contract_multiplier)

    def test_row_too_short_to_carry_a_multiplier_keeps_the_contract(self):
        short = _row("ZA", "9999", "2,000")[:11]   # 乘數欄之前就截斷
        rows = parse_stock_list(_synthetic_page([short]))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].contract_multiplier)

    def test_multiplier_header_is_matched_on_normalised_text(self):
        # 表頭那格的空白是 <br> 造成的排版,不是詞的一部分 —— 官網把 <br> 移到
        # 別的位置(甚至拿掉)都還是同一欄,認欄位不該被換行位置綁架。
        for header in ("標準型證<br>券股數/<br>受益權單位",   # 官網現況:切在「證|券」中間
                       "標準<br>型證券股數/受益權單位",
                       "標準型證券股數/受益權單位"):
            with self.subTest(header=header):
                headers = list(_HEADERS)
                headers[11] = header
                rows = parse_stock_list(
                    _synthetic_page([_row("ZA", "9999", "2,000")], headers=headers))
                self.assertEqual(rows[0].contract_multiplier, 2000)

    def test_missing_multiplier_header_raises_like_any_other_column(self):
        # 表頭少一欄 = 頁面改版,與 test_missing_expected_header_raises 同一個處理:
        # 大聲失敗,不是靜靜地全部回 None。
        headers = list(_HEADERS)
        headers[11] = "備註"
        with self.assertRaises(TaifexParseError):
            parse_stock_list(_synthetic_page([_row("ZA", "9999", "2,000")], headers=headers))

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


class ContractMultiplierUpsert(unittest.TestCase):
    """`import-futures` 的契約 upsert 怎麼處理乘數。"""

    def setUp(self):
        from radar import importer

        self.importer = importer
        self.engine = create_engine("sqlite://")
        schema.metadata.create_all(self.engine)

    def _upsert(self, rows, seen_on):
        with self.engine.begin() as conn:
            self.importer._upsert_futures_contracts(conn, rows, seen_on)

    def _stored(self):
        with self.engine.begin() as conn:
            return dict(conn.execute(sql_text(
                "SELECT contract_code, contract_multiplier FROM futures_contracts"
            )).fetchall())

    def test_multiplier_is_written_and_unknown_stays_null(self):
        rows = parse_stock_list(_synthetic_page([
            _row("ZA", "9991", "2,000"),
            _row("ZB", "9992", "100"),
            _row("ZC", "9993", "10,000"),
            _row("ZD", "9994", "-"),
        ]))
        self._upsert(rows, "2026-09-17")
        self.assertEqual(
            self._stored(),
            {"ZAF": 2000, "ZBF": 100, "ZCF": 10000, "ZDF": None},
        )

    def test_unknown_does_not_erase_a_previously_known_multiplier(self):
        known = parse_stock_list(_synthetic_page([_row("ZA", "9991", "2,000")]))
        self._upsert(known, "2026-09-17")
        blank = parse_stock_list(_synthetic_page([_row("ZA", "9991", "")]))
        self._upsert(blank, "2026-09-18")
        # 解析失敗不該把已知的乘數抹成 NULL:docs/38 R2b 對 NULL 一律否決,
        # 抹掉一次就等於那檔標的從此安靜地不再產生任何旗標。
        self.assertEqual(self._stored(), {"ZAF": 2000})

    def test_a_real_change_of_multiplier_does_overwrite(self):
        self._upsert(parse_stock_list(_synthetic_page([_row("ZA", "9991", "2,000")])),
                     "2026-09-17")
        self._upsert(parse_stock_list(_synthetic_page([_row("ZA", "9991", "100")])),
                     "2026-09-18")
        self.assertEqual(self._stored(), {"ZAF": 100})

    def test_first_seen_still_survives_the_refresh(self):
        rows = parse_stock_list(_synthetic_page([_row("ZA", "9991", "2,000")]))
        self._upsert(rows, "2026-09-17")
        self._upsert(rows, "2026-09-18")
        with self.engine.begin() as conn:
            got = conn.execute(sql_text(
                "SELECT first_seen, last_seen FROM futures_contracts"
            )).fetchone()
        self.assertEqual(tuple(got), ("2026-09-17", "2026-09-18"))


class ImportFuturesSummaryLine(unittest.TestCase):
    def test_summary_shows_multiplier_coverage(self):
        import contextlib
        import io as _io
        from unittest import mock

        from radar import cli

        info = {
            "date": "2026-09-17", "contracts": 320, "contracts_with_multiplier": 318,
            "stock_futures_rows": 1969, "feed_rows": 2332, "leftover_codes": 65,
            "has_regular": True, "has_after_hours": True,
        }
        buf = _io.StringIO()
        with mock.patch("radar.importer.import_futures", return_value=info):
            with contextlib.redirect_stdout(buf):
                cli.cmd_import_futures(None)
        # 涵蓋率要看得見:少一個乘數 = 少一檔標的永遠不會上榜(docs/38 R2b)。
        self.assertIn("318/320", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
