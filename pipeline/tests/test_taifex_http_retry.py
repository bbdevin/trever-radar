# -*- coding: utf-8 -*-
"""TAIFEX 瞬時錯誤的小重試(2026-10-22:stockLists ReadTimeout、futDataDown HTTP 520)。

只重試逾時/連線中斷/5xx,最多兩次(5 → 15 秒);4xx 不重試;用完仍失敗 → 原例外。
"""
import unittest
from unittest import mock

import requests

from radar.providers import taifex


def _resp(status: int, content: bytes = b"", text: str = "") -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = content or text.encode("utf-8")
    r.url = "https://www.taifex.com.tw/x"
    return r


HISTORY_CSV = (
    "交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,"
    "未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,"
    "價差對單式委託成交量\r\n"
    "2026/10/22,TX,202611,23000,23100,22900,23050,50,0.2%,1000,23050,90000,,,,,,一般,\r\n"
).encode("big5")


class TaifexRetry(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(taifex.time, "sleep")
        self.sleep = p.start()
        self.addCleanup(p.stop)

    def test_read_timeout_then_ok(self):
        calls = [requests.ReadTimeout("read timed out"), _resp(200, HISTORY_CSV)]
        with mock.patch.object(taifex.requests, "request", side_effect=calls) as req:
            rows = taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(req.call_count, 2)
        self.assertEqual(req.call_args.args[:2], ("POST", taifex.HISTORY_URL))
        self.assertEqual([r.contract_code for r in rows], ["TX"])
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [5.0])

    def test_520_twice_then_ok(self):
        calls = [_resp(520), _resp(502), _resp(200, HISTORY_CSV)]
        with mock.patch.object(taifex.requests, "request", side_effect=calls) as req:
            taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(req.call_count, 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [5.0, 15.0])

    def test_gives_up_after_two_retries_with_the_original_error(self):
        calls = [_resp(520), _resp(520), _resp(520), _resp(200, HISTORY_CSV)]
        with mock.patch.object(taifex.requests, "request", side_effect=calls) as req:
            with self.assertRaises(requests.HTTPError) as cm:
                taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(cm.exception.response.status_code, 520)
        self.assertEqual(req.call_count, 3)

    def test_stock_list_timeout_is_retried(self):
        calls = [requests.ReadTimeout("read timed out"), requests.ConnectionError("reset"),
                 requests.ReadTimeout("read timed out")]
        with mock.patch.object(taifex.requests, "request", side_effect=calls) as req:
            with self.assertRaises(requests.ReadTimeout):
                taifex.fetch_stock_list()
        self.assertEqual(req.call_count, 3)
        self.assertEqual(req.call_args.args[:2], ("GET", taifex.STOCK_LIST_URL))

    def test_4xx_is_not_retried(self):
        with mock.patch.object(taifex.requests, "request", side_effect=[_resp(404)]) as req:
            with self.assertRaises(requests.HTTPError):
                taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(req.call_count, 1)
        self.sleep.assert_not_called()

    def test_parse_errors_are_not_retried(self):
        with mock.patch.object(taifex.requests, "request", side_effect=[_resp(200, b"\xff\xfe\xfa")]) as req:
            with self.assertRaises(taifex.TaifexParseError):
                taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(req.call_count, 1)

    def test_header_only_csv_is_still_no_data_not_retried(self):
        header_only = HISTORY_CSV.split(b"\r\n")[0] + b"\r\n"
        from radar.providers import NoDataError
        with mock.patch.object(taifex.requests, "request", side_effect=[_resp(200, header_only)]) as req:
            with self.assertRaises(NoDataError):
                taifex.fetch_history("2026-10-22", "2026-10-22")
        self.assertEqual(req.call_count, 1)


if __name__ == "__main__":
    unittest.main()
