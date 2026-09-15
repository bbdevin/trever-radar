"""Regression tests for the half-empty-date bug in backfill()/backfill_margin().

TWSE and TPEx quotes (and margin) come from two independent sources fetched in
one import_daily() call. When one source fails while the other logs "ok", the
date gets *some* rows in daily_prices/daily_margins — so the old "date exists"
check considered it permanently done and could never repair it. These tests
build small throwaway SQLite DBs shaped like the measured production gaps
(2026-07-16..08-19 TPEx quotes outage, 2026-08-11..08-13 TWSE quotes outage,
2026-09-02 TPEx margin outage) and assert the market-relative check catches
them, without ever making a network request (import_daily is monkeypatched).
"""
import datetime as real_datetime
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

import radar.config as config
import radar.db as db
from radar import schema
from radar.importer import _incomplete_markets, backfill, backfill_margin

# Reference pool sizes for the toy DB (proportions mirror production, not the
# absolute magnitudes — that's the point: no hardcoded row counts).
TWSE_N, TPEX_N = 30, 20

# Weekdays only (no Sat/Sun), all in one calendar month so window math is easy.
HISTORY_DATES = [
    "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07",
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14",
    "2026-08-17", "2026-08-18",
]
TARGET = "2026-08-19"  # Wednesday


def _tz_now(iso_date: str) -> real_datetime.datetime:
    y, m, d = (int(x) for x in iso_date.split("-"))
    return real_datetime.datetime(y, m, d, 12, 0, tzinfo=ZoneInfo(config.TZ))


class _BaseSqliteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        self._seed_stocks()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def _seed_stocks(self):
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": f"TW{i:04d}", "name": "x", "market": "twse",
                 "type": "stock", "is_active": 1}
                for i in range(TWSE_N)
            ] + [
                {"id": f"TP{i:04d}", "name": "x", "market": "tpex",
                 "type": "stock", "is_active": 1}
                for i in range(TPEX_N)
            ])

    def _seed_quotes(self, date_iso: str, twse_n: int, tpex_n: int):
        rows = [
            {"stock_id": f"TW{i:04d}", "date": date_iso, "close": 10,
             "volume": 100, "turnover": 1000}
            for i in range(twse_n)
        ] + [
            {"stock_id": f"TP{i:04d}", "date": date_iso, "close": 10,
             "volume": 100, "turnover": 1000}
            for i in range(tpex_n)
        ]
        if rows:
            with db.get_engine().begin() as conn:
                conn.execute(schema.daily_prices.insert(), rows)

    def _seed_margin(self, date_iso: str, twse_n: int, tpex_n: int):
        rows = [
            {"stock_id": f"TW{i:04d}", "date": date_iso, "margin_buy": 1}
            for i in range(twse_n)
        ] + [
            {"stock_id": f"TP{i:04d}", "date": date_iso, "margin_buy": 1}
            for i in range(tpex_n)
        ]
        if rows:
            with db.get_engine().begin() as conn:
                conn.execute(schema.daily_margins.insert(), rows)

    def _seed_full_history(self, dates=HISTORY_DATES):
        for d in dates:
            self._seed_quotes(d, TWSE_N, TPEX_N)


def _fake_import_daily(calls):
    def fake(ds, datasets=None):
        calls.append(ds)
        return [
            {"source": "twse", "dataset": "quotes", "status": "ok", "rows": 1},
            {"source": "tpex", "dataset": "quotes", "status": "ok", "rows": 1},
            {"source": "twse", "dataset": "margin", "status": "ok", "rows": 1},
            {"source": "tpex", "dataset": "margin", "status": "ok", "rows": 1},
        ]
    return fake


class BackfillOutcomeIsMeasuredNotAssumedTests(_BaseSqliteTest):
    """「試過了」不等於「補好了」,而在這支程式裡差別是看不見的。

    `importer._run` 的 docstring 明講 "never raise":每一次抓取失敗都被轉成
    import_logs 裡的一列然後正常返回。`backfill()` 對任何日期都不拋出,而
    `cmd_backfill` 在本次改動之前沒有 `sys.exit`。三者合起來的後果是:**25 個
    日期全部抓取失敗,指令仍會印出「N market-gaps repaired」並 exit 0**,而那個
    N 是在呼叫 import_daily **之前**就累加的——它數的是嘗試,不是成果。

    這很重要,因為 `repair-window.sh` 把後面三個步驟(帳本補寫、
    compute-performance --all、融資券)全部鏈在這個離開碼上。鏈在一個永遠為零的
    離開碼上,等於沒有閘門:報價沒補成,後面照跑,而且都是對正式資料庫的寫入。

    這裡的 fake import 刻意**不寫任何列**——正是「跑完了但沒補到」的形狀。
    """

    def test_a_failed_repair_is_reported_as_still_incomplete(self):
        self._seed_full_history()
        self._seed_quotes(TARGET, TWSE_N, 0)      # tpex 全缺
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])

        self.assertIn("20260819", calls, "先決條件:它必須真的試過重抓")
        self.assertTrue(
            any(r["date"] == TARGET and r["market"] == "tpex"
                for r in result["still_incomplete"]),
            "重抓之後 tpex 仍然是 0 列,必須出現在 still_incomplete;"
            f"實際為 {result['still_incomplete']}",
        )
        self.assertEqual(
            result["attempted"], result["repaired"],
            "`repaired` 是保留給既有讀者的舊鍵名,語意等同 attempted",
        )

    def test_a_successful_repair_leaves_nothing_still_incomplete(self):
        self._seed_full_history()
        self._seed_quotes(TARGET, TWSE_N, 0)

        seeded = []

        def repairing_import(ds, datasets=None):
            # 這一版的 fake 真的把缺的列補上,模擬抓取成功。
            iso = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
            with db.get_engine().begin() as conn:
                conn.execute(schema.daily_prices.insert(), [
                    {"stock_id": f"TP{i:04d}", "date": iso, "close": 10,
                     "volume": 100, "turnover": 1000}
                    for i in range(TPEX_N)
                ])
            seeded.append(ds)
            return [{"source": "tpex", "dataset": "quotes", "status": "ok", "rows": TPEX_N}]

        with patch("radar.importer.import_daily", side_effect=repairing_import), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])

        self.assertEqual(seeded, ["20260819"])
        self.assertEqual(
            result["still_incomplete"], [],
            "缺的列補回來之後就不該再列為未完成——否則這個判準只會永遠說失敗",
        )

    def test_the_cli_exit_code_reports_the_outcome(self):
        """離開碼必須講結果,不是「跑完了」。

        `repair-window.sh` 的步驟一就是靠這個碼決定要不要往下做。
        """
        from radar import cli

        self._seed_full_history()
        self._seed_quotes(TARGET, TWSE_N, 0)
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["backfill", "--days", "1", "--datasets", "quotes"])
        self.assertEqual(
            ctx.exception.code, 1,
            "補不成必須非零。改動前這裡是 exit 0,而後續三個正式資料庫寫入"
            "全部鏈在它上面",
        )


class BackfillQuotesGapTests(_BaseSqliteTest):
    """backfill(): a date needs every market adequately represented, not just one row."""

    def test_half_empty_date_is_detected_and_reimported(self):
        # Exact 07-16..08-19 shape: TWSE full, TPEx zero.
        self._seed_full_history()
        self._seed_quotes(TARGET, TWSE_N, 0)
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])
        self.assertIn("20260819", calls, "half-empty date must trigger a re-import")
        self.assertTrue(
            any(r["date"] == TARGET and r["market"] == "tpex" for r in result["repaired"]),
            f"repaired list should name tpex for {TARGET}: {result['repaired']}",
        )

    def test_outage_longer_than_half_the_window_is_still_detected(self):
        """The reference must not be definable by the outage it exists to catch.

        This is the shape of the real incident and the reason the reference is a
        high quantile rather than a median. TPEx was short for 25 consecutive
        trading days; whether those days are a minority of the scanned window
        depends entirely on the caller's `days` argument, which the detector must
        not be sensitive to. Here 8 of 12 history dates are degraded — a median
        would land on the degraded value and pronounce every one of them healthy.
        """
        good = HISTORY_DATES[:4]
        degraded = HISTORY_DATES[4:]          # 8 of 12 — the majority
        for d in good:
            self._seed_quotes(d, TWSE_N, TPEX_N)
        for d in degraded:
            self._seed_quotes(d, TWSE_N, TPEX_N // 4)
        self._seed_quotes(TARGET, TWSE_N, TPEX_N // 4)

        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])

        self.assertIn(
            "20260819", calls,
            "an outage occupying most of the window must still be flagged — "
            "the reference is meant to describe what the market delivers when "
            "it is healthy, not what it delivered while broken",
        )
        self.assertTrue(
            any(r["market"] == "tpex" for r in result["repaired"]),
            f"tpex should be named as the incomplete market: {result['repaired']}",
        )

    def test_reference_quantile_tracks_the_healthy_level_not_the_majority(self):
        """Same point at the unit level, so a failure says which half is wrong."""
        from radar.importer import _REFERENCE_QUANTILE, _quantile

        # 4 healthy days at 20, 8 broken days at 5 — broken is the majority.
        vals = [20] * 4 + [5] * 8
        self.assertEqual(
            _quantile(vals, _REFERENCE_QUANTILE), 20,
            "the reference must be the healthy level; a median here returns 5 "
            "and silently blesses every broken date",
        )
        # Nearest-rank means the reference is always a count some date reported.
        self.assertIn(_quantile(vals, _REFERENCE_QUANTILE), vals)

    def test_a_market_starved_below_the_sample_floor_says_so(self):
        """The check's blind spot must announce itself instead of passing quietly.

        The reference needs >= `_MIN_MARKET_SAMPLES` dates carrying rows, and the
        sample count is starved by exactly what we are hunting: the more total the
        outage, the fewer dates have any rows. Below the floor the market is
        exempted, so the worst outages produce the least output — silence that
        reads identically to a clean result. Independent verification reproduced
        this: a market present on only 4 of 29 window dates, then absent entirely
        on the target date, is not flagged at all.

        The exemption itself is correct — you cannot infer "normal" from four
        samples. What must not happen is it passing without a word.
        """
        for d in HISTORY_DATES[:4]:
            self._seed_quotes(d, TWSE_N, TPEX_N)
        for d in HISTORY_DATES[4:]:
            self._seed_quotes(d, TWSE_N, 0)      # tpex starved below the floor
        self._seed_quotes(TARGET, TWSE_N, 0)

        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])

        self.assertEqual(
            result["unverified_markets"], ["tpex"],
            "tpex has 4 sampled dates, below the floor — it must be reported as "
            "unverified rather than silently omitted",
        )
        self.assertEqual(result["samples"]["tpex"], 4)
        self.assertNotIn("tpex", result["reference"])
        self.assertIn("twse", result["reference"],
                      "the healthy market must still be checked normally")

    def test_describe_reference_separates_checked_from_unverifiable(self):
        from radar.importer import describe_reference

        lines = describe_reference({"twse": 30}, {"twse": 12, "tpex": 3})
        joined = "\n".join(lines)
        self.assertIn("twse: reference=30 from 12 dates", joined)
        self.assertIn("UNVERIFIED", joined)
        self.assertIn("NOT checked", joined,
                      "the line must say the market was not checked, not merely "
                      "that a number was unavailable")

    def test_full_strength_date_is_skipped_with_zero_import_calls(self):
        self._seed_full_history()
        self._seed_quotes(TARGET, TWSE_N, TPEX_N)
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])
        self.assertEqual(calls, [], "a fully represented date must cost zero requests")
        self.assertEqual(result["repaired"], [])
        self.assertEqual(result["trading_days"], 1)

    def test_missing_date_is_imported_existing_behavior_preserved(self):
        self._seed_full_history()
        # TARGET has no rows at all.
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            backfill(1, ["quotes"])
        self.assertIn("20260819", calls)

    def test_sparse_db_does_not_flag_everything(self):
        # Only 2 history dates: below _MIN_MARKET_SAMPLES(5), so the market
        # reference must not be trusted, and a partial date must be accepted
        # as-is rather than producing nonsense re-imports.
        self._seed_quotes(HISTORY_DATES[0], TWSE_N, TPEX_N)
        self._seed_quotes(HISTORY_DATES[1], TWSE_N, TPEX_N)
        self._seed_quotes(TARGET, TWSE_N, 0)  # would be "half-empty" if trusted
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(TARGET)
            result = backfill(1, ["quotes"])
        self.assertEqual(calls, [], "too few reference dates must not flag anything")
        self.assertEqual(result["trading_days"], 1)

    def test_0811_0813_shape_detected_via_twse_side(self):
        # TWSE at ~40% of reference (well under the 50% cutoff), TPEx normal.
        history = HISTORY_DATES[:8]
        target = "2026-08-13"
        self._seed_full_history(history)
        self._seed_quotes(target, int(TWSE_N * 0.4), TPEX_N)
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now(target)
            result = backfill(1, ["quotes"])
        self.assertIn("20260813", calls)
        self.assertTrue(
            any(r["date"] == target and r["market"] == "twse" for r in result["repaired"])
        )

    def test_multi_day_repair_names_every_incomplete_date(self):
        # Three consecutive dates all TWSE-starved, mirroring the 08-11..08-13
        # outage window; a single backfill(days=3) run must repair all three
        # and the caller must be able to tell which market on which date.
        history = HISTORY_DATES[:6]  # 08-03..08-10, excludes the target dates below
        targets = ["2026-08-11", "2026-08-12", "2026-08-13"]
        self._seed_full_history(history)
        for t in targets:
            self._seed_quotes(t, int(TWSE_N * 0.4), TPEX_N)
        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)), \
             patch("radar.importer.datetime") as mock_dt:
            mock_dt.now.return_value = _tz_now("2026-08-13")
            result = backfill(3, ["quotes"])
        for t in targets:
            self.assertIn(t.replace("-", ""), calls)
        repaired_dates = {r["date"] for r in result["repaired"]}
        self.assertEqual(repaired_dates, set(targets))


class IncompleteMarketsBoundaryTests(unittest.TestCase):
    """Unit-level check of the exact fraction cutoff, independent of median noise."""

    def test_boundary_is_inclusive_at_the_threshold(self):
        reference = {"twse": 100, "tpex": 20}
        counts = {"2026-08-19": {"twse": 100, "tpex": 10}}  # tpex exactly 50%
        missing = _incomplete_markets("2026-08-19", counts, reference, 0.5)
        self.assertEqual(missing, [], "exactly at the fraction must not be flagged")

    def test_just_below_threshold_is_flagged(self):
        reference = {"twse": 100, "tpex": 20}
        counts = {"2026-08-19": {"twse": 100, "tpex": 9}}  # tpex 45% < 50%
        missing = _incomplete_markets("2026-08-19", counts, reference, 0.5)
        self.assertEqual(missing, ["tpex"])

    def test_just_above_threshold_is_not_flagged(self):
        reference = {"twse": 100, "tpex": 20}
        counts = {"2026-08-19": {"twse": 100, "tpex": 11}}  # tpex 55% > 50%
        missing = _incomplete_markets("2026-08-19", counts, reference, 0.5)
        self.assertEqual(missing, [])


class BackfillMarginGapTests(_BaseSqliteTest):
    """backfill_margin(): the 2026-09-02 shape (floor cleared, one market gutted)."""

    def _seed_trading_day(self, date_iso):
        # backfill_margin discovers trading days from daily_prices; content
        # doesn't matter, only that the date is registered.
        self._seed_quotes(date_iso, 1, 1)

    def test_shape_clears_absolute_floor_but_is_flagged_by_market_check(self):
        history = HISTORY_DATES[:8]
        target = "2026-09-02"
        for d in history:
            self._seed_trading_day(d)
            self._seed_margin(d, TWSE_N, TPEX_N)
        self._seed_trading_day(target)
        # TWSE near-full (like real 83/1211 missing), TPEx gutted (980/985).
        twse_n, tpex_n = TWSE_N - 2, 1
        self._seed_margin(target, twse_n, tpex_n)
        self.assertGreater(twse_n + tpex_n, 20, "sanity: total clears the toy floor")

        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)):
            result = backfill_margin(days=1, sleep_s=0, min_rows=20)
        self.assertIn("20260902", calls,
                       "market-relative check must catch a date the floor alone would miss")
        self.assertTrue(
            any(r["date"] == target and r["market"] == "tpex" for r in result["repaired"])
        )

    def test_absolute_floor_still_fires_on_a_nearly_empty_date(self):
        history = HISTORY_DATES[:8]
        target = "2026-09-02"
        for d in history:
            self._seed_trading_day(d)
            self._seed_margin(d, TWSE_N, TPEX_N)
        self._seed_trading_day(target)
        self._seed_margin(target, 2, 1)  # total=3, well under any reasonable floor

        calls = []
        # strict_markets disabled to isolate the pre-existing floor behaviour.
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)):
            backfill_margin(days=1, sleep_s=0, min_rows=20, strict_markets=False)
        self.assertIn("20260902", calls, "floor must still catch a near-empty date on its own")

    def test_full_strength_margin_date_is_skipped(self):
        history = HISTORY_DATES[:8]
        target = "2026-09-02"
        for d in history:
            self._seed_trading_day(d)
            self._seed_margin(d, TWSE_N, TPEX_N)
        self._seed_trading_day(target)
        self._seed_margin(target, TWSE_N, TPEX_N)

        calls = []
        with patch("radar.importer.import_daily", side_effect=_fake_import_daily(calls)):
            backfill_margin(days=1, sleep_s=0, min_rows=20)
        self.assertEqual(calls, [], "a fully represented margin date must cost zero requests")


if __name__ == "__main__":
    unittest.main()
