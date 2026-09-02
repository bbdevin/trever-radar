"""docs/13 §8 排行 V2 shadow 報表測試。

固定裝置(fixture)刻意把成熟度級距與隔日沖觀察數卡在門檻上:9/10/29/30 事件、
3/4/7/8 筆隔日沖觀察,以及一個「事件多但成熟少」的分點 —— 那正是 V1 把
``samples`` 與成熟樣本混為一談所掩蓋的情況。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import event

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_ranking_v2_shadow import (
    build_branch_ranking_v2_shadow_report,
    daytrade_verdicts,
    maturity_tier,
    write_branch_ranking_v2_shadow_report,
)
from radar.compute.read_only_sqlite import get_read_only_sqlite_engine

CALENDAR_DAYS = 140  # 事件日 index <= CALENDAR_DAYS - 6 才可能成熟(需 5 根後續 K)


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


class MaturityTierTests(unittest.TestCase):
    def test_tier_boundaries(self):
        self.assertEqual(maturity_tier(0), "insufficient")
        self.assertEqual(maturity_tier(9), "insufficient")
        self.assertEqual(maturity_tier(10), "provisional")
        self.assertEqual(maturity_tier(29), "provisional")
        self.assertEqual(maturity_tier(30), "sufficient")


class DaytradeVerdictTests(unittest.TestCase):
    def test_three_observations_are_unknown_under_both_minimums(self):
        verdicts = daytrade_verdicts([(10, 10)] * 3)
        self.assertEqual(verdicts["observations"], 3)
        self.assertIsNone(verdicts["payback_rate"])
        self.assertEqual(verdicts["payback_rate_status"], "below_v1_min_obs")
        # V1 未判定卻回傳 False;報表必須把那個 False 標成「未判定」。
        self.assertIs(verdicts["v1_min4"]["verdict"], False)
        self.assertEqual(verdicts["v1_min4"]["status"], "not_determined_defaults_false")
        self.assertIsNone(verdicts["v2_min8"]["verdict"])
        self.assertEqual(verdicts["v2_min8"]["status"], "unknown")

    def test_four_observations_determine_v1_but_not_v2(self):
        verdicts = daytrade_verdicts([(10, 10)] * 4)
        self.assertEqual(verdicts["v1_min4"], {"min_obs": 4, "verdict": True, "status": "determined"})
        self.assertEqual(verdicts["v2_min8"], {"min_obs": 8, "verdict": None, "status": "unknown"})
        self.assertEqual(verdicts["payback_rate"], 1.0)
        self.assertTrue(verdicts["verdict_differs"])

    def test_seven_observations_still_unknown_under_v2(self):
        verdicts = daytrade_verdicts([(10, 10)] * 7)
        self.assertEqual(verdicts["observations"], 7)
        self.assertIs(verdicts["v1_min4"]["verdict"], True)
        self.assertEqual(verdicts["v2_min8"]["status"], "unknown")

    def test_eight_observations_determine_both(self):
        verdicts = daytrade_verdicts([(10, 10)] * 8)
        self.assertEqual(verdicts["v2_min8"], {"min_obs": 8, "verdict": True, "status": "determined"})
        self.assertFalse(verdicts["verdict_differs"])

    def test_eight_observations_below_payback_rate_are_determined_false(self):
        observations = [(10, 10)] * 4 + [(10, 0)] * 4     # rate 0.5 < 0.6
        verdicts = daytrade_verdicts(observations)
        self.assertEqual(verdicts["payback_rate"], 0.5)
        self.assertIs(verdicts["v1_min4"]["verdict"], False)
        self.assertIs(verdicts["v2_min8"]["verdict"], False)
        self.assertEqual(verdicts["v2_min8"]["status"], "determined")

    def test_zero_observations_are_unknown_not_false(self):
        verdicts = daytrade_verdicts([])
        self.assertEqual(verdicts["observations"], 0)
        self.assertIsNone(verdicts["v2_min8"]["verdict"])


class BranchRankingV2ShadowTests(unittest.TestCase):
    # (branch, stock, daily drift rate)
    BRANCH_STOCKS = {
        "B04_BELOW": ("S04", 0.005),
        "B09_INSUF": ("S09", 0.020),
        "BMIX_INSUF": ("SMIX", 0.019),
        "B10_PROV": ("S10", 0.0008),
        "B29_PROV": ("S29", 0.0009),
        "B30_SUFF": ("S30", 0.0010),
        "BFLAT_SUFF": ("SFLAT", 0.0),
        "DT3": ("SDT", 0.003),
        "DT4": ("SDT", 0.003),
        "DT7": ("SDT", 0.003),
        "DT8": ("SDT", 0.003),
    }
    # 事件日 index(彼此不相鄰,故事件數 == 資格日數 == 隔日沖觀察數)
    EVENT_INDICES = {
        "B04_BELOW": [0, 2, 4, 6],
        "B09_INSUF": list(range(0, 18, 2)),
        "BMIX_INSUF": list(range(0, 18, 2)) + [135, 137, 139],
        "B10_PROV": list(range(0, 20, 2)),
        "B29_PROV": list(range(0, 58, 2)),
        "B30_SUFF": list(range(0, 60, 2)),
        "BFLAT_SUFF": list(range(0, 60, 2)),
        "DT3": [0, 2, 4],
        "DT4": [0, 2, 4, 6],
        "DT7": list(range(0, 14, 2)),
        "DT8": list(range(0, 16, 2)),
    }
    DAYTRADE_BRANCHES = ("DT3", "DT4", "DT7", "DT8")

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "report.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        self.report_db_url = config.DB_URL
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 1), CALENDAR_DAYS)
        self.as_of = self.days[-1]

        stocks = {}
        for _branch, (stock_id, rate) in self.BRANCH_STOCKS.items():
            stocks[stock_id] = rate
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": stock_id, "name": f"Stock {stock_id}", "market": "twse", "type": "stock"}
                for stock_id in sorted(stocks)
            ])
            prices = []
            for stock_id, rate in sorted(stocks.items()):
                for index, day in enumerate(self.days):
                    value = round(100.0 * (1.0 + rate * index), 4)
                    prices.append({
                        "stock_id": stock_id, "date": day,
                        "open": value, "close": value, "adj_factor": 1.0,
                    })
            conn.execute(schema.daily_prices.insert(), prices)

            branch_names = sorted(self.BRANCH_STOCKS)
            self.branch_ids = {name: index for index, name in enumerate(branch_names, 1)}
            conn.execute(schema.branch_dim.insert(), [
                {"id": self.branch_ids[name], "branch_key": name.lower(), "branch_name": name}
                for name in branch_names
            ])

            trades = []
            for branch_name, indices in self.EVENT_INDICES.items():
                stock_id, _rate = self.BRANCH_STOCKS[branch_name]
                branch_id = self.branch_ids[branch_name]
                for index in indices:
                    trades.append({
                        "stock_id": stock_id, "date": self.days[index], "branch_id": branch_id,
                        "buy_lots": 10, "sell_lots": 0, "net_lots": 10, "pct": 1.5,
                        "source": "fixture",
                    })
                    if branch_name in self.DAYTRADE_BRANCHES and index + 1 < CALENDAR_DAYS:
                        # 次日大量賣出 = 回吐;pct 為 None 故本身不是資格買超日。
                        trades.append({
                            "stock_id": stock_id, "date": self.days[index + 1],
                            "branch_id": branch_id, "buy_lots": 0, "sell_lots": 100,
                            "net_lots": -100, "pct": None, "source": "fixture",
                        })
            conn.execute(schema.branch_trades_raw.insert(), trades)

            conn.execute(schema.branch_rankings.insert(), {
                "branch_name": "B30_SUFF", "as_of": self.days[100], "rank_score": 61.0,
                "win_rate": 100.0, "avg_ret5": 0.4, "samples": 26,
                "style": "swing", "is_daytrade": False, "source": "candidate",
            })

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _report(self):
        return build_branch_ranking_v2_shadow_report(as_of=self.as_of)

    def _row(self, report, branch_name):
        return next(row for row in report["branch_rows"] if row["branch_name"] == branch_name)

    # --- events / matured split -------------------------------------------------

    def test_events_and_matured_samples_are_split(self):
        report = self._report()
        mixed = self._row(report, "BMIX_INSUF")
        self.assertEqual(mixed["events_count"], 12)
        self.assertEqual(mixed["matured_samples"], 9)
        self.assertEqual(mixed["immature_events"], 3)
        # V1 寫進 branch_rankings.samples 的就是事件總數 —— 缺陷本身。
        self.assertEqual(mixed["v1_samples"], mixed["events_count"])
        self.assertNotEqual(mixed["v1_samples"], mixed["matured_samples"])
        self.assertEqual(mixed["maturity_tier"], "insufficient")
        self.assertTrue(mixed["v1_ranked"], "12 events clears the V1 >=5 event gate")

        summary = report["summary"]
        self.assertEqual(summary["total_immature_events"], 3)
        self.assertEqual(
            summary["total_events"] - summary["total_matured_samples"],
            summary["total_immature_events"],
        )

    def test_maturity_tier_boundaries_in_report_rows(self):
        report = self._report()
        observed = {
            name: (self._row(report, name)["matured_samples"], self._row(report, name)["maturity_tier"])
            for name in ("B09_INSUF", "B10_PROV", "B29_PROV", "B30_SUFF")
        }
        self.assertEqual(observed, {
            "B09_INSUF": (9, "insufficient"),
            "B10_PROV": (10, "provisional"),
            "B29_PROV": (29, "provisional"),
            "B30_SUFF": (30, "sufficient"),
        })
        tiers = report["summary"]["maturity_tiers"]
        self.assertEqual(sum(tiers.values()), report["summary"]["branches_evaluated"])
        self.assertEqual(tiers["sufficient"], 2)          # B30_SUFF, BFLAT_SUFF
        self.assertEqual(tiers["provisional"], 2)         # B10_PROV, B29_PROV

    def test_immature_events_never_enter_win_rate_denominator(self):
        report = self._report()
        insufficient = self._row(report, "B09_INSUF")
        mixed = self._row(report, "BMIX_INSUF")
        # 兩者成熟樣本相同(9),事件數不同;勝率分母只看成熟樣本。
        self.assertEqual(insufficient["matured_samples"], mixed["matured_samples"])
        self.assertEqual(insufficient["win_rate"], 100.0)
        self.assertEqual(mixed["win_rate"], 100.0)
        self.assertEqual(mixed["win_rate_status"], "computed")

    # --- the three interpretations ----------------------------------------------

    def test_interpretation_a_changes_nothing_about_the_ranking(self):
        report = self._report()
        summary = report["summary"]["interpretations"]["a_score_and_flag"]
        self.assertEqual(summary["listed_count"], report["summary"]["v1_ranked_count"])
        self.assertEqual(summary["scored_count"], report["summary"]["v1_ranked_count"])
        self.assertEqual(summary["left_count"], 0)
        self.assertEqual(summary["entered_count"], 0)
        self.assertEqual(summary["rank_drift"]["moved"], 0)
        self.assertEqual(summary["rank_drift"]["mean_abs"], 0)
        for row in report["branch_rows"]:
            entry = row["v2_interpretations"]["a_score_and_flag"]
            self.assertEqual(entry["rank"], row["v1_rank"])
            self.assertEqual(entry["score"], row["v1_score"] if row["v1_ranked"] else None)
            if row["v1_ranked"] and row["maturity_tier"] == "insufficient":
                self.assertEqual(entry["status"], "scored_insufficient_maturity_flagged")

    def test_interpretation_b_keeps_branches_listed_but_unscored(self):
        report = self._report()
        summary = report["summary"]["interpretations"]["b_no_score"]
        self.assertEqual(summary["listed_count"], report["summary"]["v1_ranked_count"])
        self.assertEqual(summary["left_count"], 0)
        self.assertGreater(summary["listed_without_score_count"], 0)
        insufficient = self._row(report, "B09_INSUF")["v2_interpretations"]["b_no_score"]
        self.assertTrue(insufficient["listed"])
        self.assertFalse(insufficient["scored"])
        self.assertIsNone(insufficient["score"])
        self.assertIsNone(insufficient["rank"])
        self.assertIsNone(insufficient["rank_drift"])
        self.assertEqual(insufficient["rank_drift_status"], "not_ranked_in_v2")
        self.assertEqual(insufficient["status"], "listed_without_score")

    def test_interpretation_c_removes_branches_from_the_list(self):
        report = self._report()
        summary = report["summary"]["interpretations"]["c_exclude"]
        self.assertEqual(summary["listed_without_score_count"], 0)
        self.assertEqual(summary["listed_count"], summary["scored_count"])
        self.assertIn("B09_INSUF", summary["left_ranked_set"])
        self.assertIn("BMIX_INSUF", summary["left_ranked_set"])
        removed = self._row(report, "B09_INSUF")["v2_interpretations"]["c_exclude"]
        self.assertFalse(removed["listed"])
        self.assertEqual(removed["status"], "excluded_insufficient_maturity")

    def test_b_and_c_score_the_same_branches_and_only_differ_by_listing(self):
        report = self._report()
        interpretations = report["summary"]["interpretations"]
        # 同一批低成熟度分點:B 留在榜上但不給分,C 直接移出榜單。
        self.assertEqual(
            interpretations["b_no_score"]["listed_without_score"],
            interpretations["c_exclude"]["left_ranked_set"],
        )
        self.assertEqual(interpretations["b_no_score"]["left_ranked_set"], [])
        self.assertEqual(
            interpretations["b_no_score"]["scored_count"],
            interpretations["c_exclude"]["scored_count"],
        )
        for row in report["branch_rows"]:
            self.assertEqual(
                row["v2_interpretations"]["b_no_score"]["rank"],
                row["v2_interpretations"]["c_exclude"]["rank"],
            )
        self.assertEqual(
            interpretations["b_no_score"]["listed_count"]
            - interpretations["c_exclude"]["listed_count"],
            interpretations["b_no_score"]["listed_without_score_count"],
        )

    def test_rank_drift_equals_removed_branches_ranked_above_each_survivor(self):
        report = self._report()
        removed_ranks = sorted(
            row["v1_rank"] for row in report["branch_rows"]
            if row["v1_ranked"] and not row["v2_interpretations"]["c_exclude"]["listed"]
        )
        self.assertTrue(removed_ranks, "fixture must remove at least one ranked branch")
        drifts = []
        for row in report["branch_rows"]:
            entry = row["v2_interpretations"]["c_exclude"]
            if entry["rank"] is None:
                continue
            expected = sum(1 for rank in removed_ranks if rank < row["v1_rank"])
            self.assertEqual(entry["rank_drift"], expected, row["branch_name"])
            drifts.append(entry["rank_drift"])
        self.assertGreater(max(drifts), 0, "at least one survivor must move up")
        self.assertEqual(
            report["summary"]["interpretations"]["c_exclude"]["rank_drift"]["survivors"],
            len(drifts),
        )
        self.assertEqual(
            report["summary"]["interpretations"]["c_exclude"]["rank_drift"]["max_improvement"],
            max(drifts),
        )

    def test_no_branch_can_enter_the_ranked_set_under_any_interpretation(self):
        report = self._report()
        for key, info in report["summary"]["interpretations"].items():
            self.assertEqual(info["entered_count"], 0, key)
            self.assertEqual(info["entered_ranked_set"], [], key)

    def test_below_event_threshold_branch_is_never_ranked(self):
        report = self._report()
        row = self._row(report, "B04_BELOW")
        self.assertEqual(row["events_count"], 4)
        self.assertFalse(row["v1_ranked"])
        self.assertIsNone(row["v1_rank"])
        self.assertEqual(row["v1_rank_status"], "below_v1_event_threshold")
        for key in ("a_score_and_flag", "b_no_score", "c_exclude"):
            entry = row["v2_interpretations"][key]
            self.assertFalse(entry["listed"])
            self.assertEqual(entry["status"], "below_v1_event_threshold")
            self.assertEqual(entry["rank_drift_status"], "not_ranked_in_v1")

    # --- day-trade minimums ------------------------------------------------------

    def test_daytrade_minimum_boundary_and_unknown_state_from_real_rows(self):
        report = self._report()
        observed = {}
        for name in self.DAYTRADE_BRANCHES:
            daytrade = self._row(report, name)["daytrade"]
            observed[name] = (
                daytrade["observations"],
                daytrade["v1_min4"]["verdict"], daytrade["v1_min4"]["status"],
                daytrade["v2_min8"]["verdict"], daytrade["v2_min8"]["status"],
            )
        self.assertEqual(observed, {
            "DT3": (3, False, "not_determined_defaults_false", None, "unknown"),
            "DT4": (4, True, "determined", None, "unknown"),
            "DT7": (7, True, "determined", None, "unknown"),
            "DT8": (8, True, "determined", True, "determined"),
        })
        summary = report["summary"]["daytrade"]
        self.assertEqual(summary["branches"], report["summary"]["branches_evaluated"])
        self.assertEqual(summary["flagged_min4"], 3)      # DT4, DT7, DT8
        self.assertEqual(summary["flagged_min8"], 1)      # DT8 only
        self.assertGreaterEqual(summary["unknown_min8"], 3)
        self.assertEqual(
            summary["determined_min8"] + summary["unknown_min8"], summary["branches"],
        )

    # --- honesty about what is not computable ------------------------------------

    def test_stored_snapshot_is_reported_as_evidence_not_fabricated(self):
        report = self._report()
        present = self._row(report, "B30_SUFF")["stored_ranking_snapshot"]
        self.assertEqual(present["status"], "present")
        self.assertEqual(present["as_of"], self.days[100])
        self.assertEqual(present["samples"], 26)
        absent = self._row(report, "B10_PROV")["stored_ranking_snapshot"]
        self.assertEqual(absent["status"], "absent_from_snapshot")
        self.assertIsNone(absent["rank_score"])
        self.assertIsNone(absent["samples"])
        self.assertEqual(report["coverage"]["stored_ranking_snapshot_as_of"], self.days[100])

    def test_metadata_declares_read_only_and_no_schema_change(self):
        report = self._report()
        metadata = report["metadata"]
        self.assertEqual(metadata["report"], "branch_ranking_v2_shadow")
        self.assertIs(metadata["read_only"], True)
        self.assertIs(metadata["schema_changes"], False)
        self.assertIs(metadata["ranking_or_score_changes"], False)
        self.assertEqual(metadata["as_of"], self.as_of)
        self.assertEqual(metadata["thresholds"]["v2_daytrade_min_obs"], 8)
        self.assertEqual(metadata["thresholds"]["v1_daytrade_min_obs"], 4)

    def test_as_of_is_a_real_cutoff(self):
        early = build_branch_ranking_v2_shadow_report(as_of=self.days[30])
        full = self._report()
        early_mixed = self._row(early, "BMIX_INSUF")
        # 135/137/139 的事件在 as_of=days[30] 時尚不存在,不得被計入。
        self.assertEqual(early_mixed["events_count"], 9)
        self.assertEqual(self._row(full, "BMIX_INSUF")["events_count"], 12)
        self.assertEqual(early["coverage"]["market_trading_days_through_as_of"], 31)
        self.assertIsNone(early["coverage"]["stored_ranking_snapshot_as_of"])

    def test_invalid_as_of_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            build_branch_ranking_v2_shadow_report(as_of="2026/01/02")

    # --- read-only guarantees ----------------------------------------------------

    def test_report_only_selects_and_writes_nothing_to_the_database(self):
        db_before = self.db_path.read_bytes()
        sidecars_before = {
            suffix: (
                (self.tmp_path / f"report.db{suffix}").exists(),
                (self.tmp_path / f"report.db{suffix}").read_bytes()
                if (self.tmp_path / f"report.db{suffix}").exists() else None,
            )
            for suffix in ("-wal", "-journal")
        }
        statements: list[str] = []
        engine = get_read_only_sqlite_engine(
            report_name="test", required_tables=("branch_trades", "daily_prices"),
        )

        def capture(_conn, _cursor, statement, _params, _context, _many):
            statements.append(statement.lstrip().lower())

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch("radar.db.init_db", side_effect=AssertionError("report must not initialise DB")):
                with patch(
                    "radar.compute.branch_ranking_v2_shadow.get_read_only_sqlite_engine",
                    return_value=engine,
                ):
                    first = self._report()
                    second = self._report()
        finally:
            event.remove(engine, "before_cursor_execute", capture)
            engine.dispose()

        self.assertEqual(first, second, "report must be deterministic")
        self.assertTrue(statements)
        self.assertTrue(all(statement.startswith("select") for statement in statements))
        self.assertEqual(self.db_path.read_bytes(), db_before)
        for suffix, before in sidecars_before.items():
            path = self.tmp_path / f"report.db{suffix}"
            after = (path.exists(), path.read_bytes() if path.exists() else None)
            self.assertEqual(after, before, suffix)

    def test_missing_configured_database_is_not_created(self):
        missing = self.tmp_path / "missing.db"
        config.DB_URL = "sqlite:///" + missing.as_posix()
        try:
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                self._report()
            self.assertFalse(missing.exists())
        finally:
            config.DB_URL = self.report_db_url

    def test_writer_rejects_the_database_and_its_sidecars_as_output(self):
        before = self.db_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not be"):
            write_branch_ranking_v2_shadow_report(as_of=self.as_of, out=self.db_path)
        for suffix in ("-wal", "-shm", "-journal"):
            with self.assertRaisesRegex(ValueError, "sidecar"):
                write_branch_ranking_v2_shadow_report(
                    as_of=self.as_of, out=self.tmp_path / f"report.db{suffix}",
                )
        self.assertEqual(self.db_path.read_bytes(), before)

    def test_writer_and_cli_emit_the_same_json(self):
        direct_out = self.tmp_path / "direct.json"
        report = write_branch_ranking_v2_shadow_report(as_of=self.as_of, out=direct_out)
        self.assertEqual(json.loads(direct_out.read_text(encoding="utf-8")), report)

        cli_out = self.tmp_path / "cli.json"
        main(["branch-ranking-v2-shadow", "--as-of", self.as_of, "--out", str(cli_out)])
        written = json.loads(cli_out.read_text(encoding="utf-8"))
        self.assertEqual(written, report)
        self.assertEqual(written["metadata"]["as_of"], self.as_of)
        self.assertEqual(sorted(written["summary"]["interpretations"]),
                         ["a_score_and_flag", "b_no_score", "c_exclude"])


if __name__ == "__main__":
    unittest.main()
