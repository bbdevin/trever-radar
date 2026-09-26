"""Contracts for the homepage composite-score list (docs/04 §10)."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json, score_list_gate

# 排序那條測試用的八檔,外加兩檔**資料完整、低於門檻**的填充股:讓缺分點的
# 比例恰好是 1/10,落在資料齊全閘門的界線上(不超過一成 → 照常排名)。
_ORDERING = ("high", "branch_high", "turnover_high", "turnover_low",
             "branch_low", "branch_missing", "threshold", "below")
_FILLERS = ("filler1", "filler2")


class _ExportFixture(unittest.TestCase):
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

    def seed(self, rows: dict[str, dict]):
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": sid, "market": "twse", "type": "stock", "is_active": 1}
                for sid in rows
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 100, "volume": 1000,
                 "turnover": spec.get("turnover", 100_000_000)}
                for sid, spec in rows.items()
                for day in ("2026-08-03", "2026-08-04")
            ])
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": sid, "date": "2026-08-04", "final": spec["final"],
                 "branch_score": spec.get("branch"), "inst_score": spec.get("inst", 50),
                 "reasons": "[]", "risks": "[]"}
                for sid, spec in rows.items()
            ])

    def radar(self) -> dict:
        out = Path(self._tmp.name) / "out"
        export_json(out)
        return json.loads((out / "radar.json").read_text(encoding="utf-8"))


class ScoreListContractTests(_ExportFixture):
    """The composite list is a threshold, not a fixed-length market scan."""

    def test_score_list_is_strict_final_threshold_without_minimum_fill(self):
        self.seed({
            "high": {"final": 80, "branch": 1, "turnover": 100_000_000},
            "branch_high": {"final": 70, "branch": 60, "turnover": 150_000_000},
            "turnover_high": {"final": 70, "branch": 25, "turnover": 300_000_000},
            "turnover_low": {"final": 70, "branch": 25, "turnover": 200_000_000},
            "branch_low": {"final": 70, "branch": 10, "turnover": 900_000_000},
            "branch_missing": {"final": 70, "branch": None, "turnover": 1_000_000_000},
            "threshold": {"final": 65, "branch": 99},
            "below": {"final": 64.99, "branch": 100},
            **{sid: {"final": 40, "branch": 10} for sid in _FILLERS},
        })
        radar = self.radar()
        self.assertEqual(radar["lists"]["score"], [
            "high", "branch_high", "turnover_high", "turnover_low",
            "branch_low", "branch_missing", "threshold",
        ])
        self.assertLess(len(radar["lists"]["score"]), 15)
        self.assertFalse(radar["score_list_meta"]["withheld"])


class ScoreListGateTests(_ExportFixture):
    """資料齊全閘門(2026-09-24)。

    缺分項時 combine() 把權重重分給其他分項,缺資料的列反而容易過 65:歷史上
    23 次上榜有 17 次來自缺分點的列。閘門不改 final,只決定今天排不排名。
    """

    def test_an_intraday_version_without_branch_data_is_withheld(self):
        """09-24 14:16 的形狀:全部缺分點與法人,卻有高分列。"""
        self.seed({f"s{i}": {"final": 75 if i < 3 else 50, "branch": None, "inst": None}
                   for i in range(10)})
        radar = self.radar()
        self.assertEqual(radar["lists"]["score"], [])
        meta = radar["score_list_meta"]
        self.assertTrue(meta["withheld"])
        self.assertEqual(meta["scored"], 10)
        self.assertEqual(meta["missing_branch"], 10)
        self.assertEqual(meta["missing_inst"], 10)

    def test_withheld_is_not_reported_as_nothing_reaching_the_threshold(self):
        """扣留時摘要不可以說「暫無達門檻」——那是把「不知道」講成「知道沒有」。"""
        self.seed({f"s{i}": {"final": 75, "branch": None} for i in range(10)})
        summary = "".join(self.radar()["summary_text"])
        self.assertIn("尚未到齊", summary)
        self.assertNotIn("暫無達門檻", summary)

    def test_summary_names_the_market_in_chinese(self):
        """stocks.market 存 twse / tpex;對照表以前只認 tse / otc,正式站印出
        「twse成交額 7238 億」(2026-09-24 16:10 那版)。"""
        self.seed({f"s{i}": {"final": 50, "branch": 20} for i in range(3)})
        summary = "".join(self.radar()["summary_text"])
        self.assertIn("上市成交額", summary)
        self.assertNotIn("twse", summary)

    def test_missing_institutional_data_alone_also_withholds(self):
        self.seed({f"s{i}": {"final": 70, "branch": 20, "inst": None if i < 2 else 50}
                   for i in range(10)})
        self.assertTrue(self.radar()["score_list_meta"]["withheld"])

    def test_a_complete_day_with_nobody_at_65_is_an_empty_list_not_withheld(self):
        self.seed({f"s{i}": {"final": 50 + i, "branch": 20} for i in range(10)})
        radar = self.radar()
        self.assertEqual(radar["lists"]["score"], [])
        self.assertFalse(radar["score_list_meta"]["withheld"])
        self.assertEqual(radar["score_list_meta"]["max_final"], 59)
        self.assertIn("暫無達門檻", "".join(radar["summary_text"]))

    def test_the_boundary_is_strictly_more_than_one_tenth(self):
        def rows(missing, total):
            return [{"scores": {"final": 70, "branch": None if i < missing else 1, "inst": 1}}
                    for i in range(total)]
        self.assertFalse(score_list_gate(rows(1, 10))["withheld"])
        self.assertTrue(score_list_gate(rows(2, 10))["withheld"])
        self.assertIsNone(score_list_gate([])["max_final"])

    def test_no_scored_rows_is_withheld_not_complete(self):
        """一列評分都沒有 = 沒有算過。判成「資料齊全」會讓前端說「今日沒有任何
        一檔達 65 分」——正是這道閘門要擋的「把不知道講成知道沒有」(驗證者抓到)。"""
        meta = score_list_gate([])
        self.assertTrue(meta["withheld"])
        self.assertEqual(meta["scored"], 0)

    def test_missing_warrant_does_not_count(self):
        """約兩成股票本來就沒有權證,那是結構性缺值,不是資料沒到齊。"""
        row = {"scores": {"final": 70, "branch": 1, "inst": 1, "warrant": None}}
        self.assertFalse(score_list_gate([row] * 10)["withheld"])

    def test_meta_is_integers_and_one_boolean_no_rates(self):
        meta = score_list_gate([{"scores": {"final": 70, "branch": None, "inst": 1}}] * 3)
        self.assertEqual(sorted(meta), ["max_final", "min_final", "missing_branch",
                                        "missing_inst", "scored", "withheld"])
        self.assertIsInstance(meta["withheld"], bool)
        for key in ("max_final", "min_final", "missing_branch", "missing_inst", "scored"):
            self.assertIsInstance(meta[key], int)
            self.assertNotIsInstance(meta[key], bool)
        self.assertEqual(meta["min_final"], 65)


class ThemeFreshnessTests(_ExportFixture):
    """題材分類的**資料集**新鮮度,與個別題材的 lifecycle 分開(2026-09-26)。

    以前「任一個題材不是 active」就把整個資料集標成 stale,而 lifecycle 只降級、
    不自動退休——來源下架過一個題材,題材分類就永遠「尚未更新,稍後自動補齊」。
    fixture 的資料日是 2026-08-04(週二)。
    """

    def seed_themes(self, rows):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [
                {"id": tid, "name": tid, "source": "fubon", "status": status,
                 "data_date": day, "source_updated_at": day}
                for tid, status, day in rows
            ])

    def freshness(self):
        return self.radar()["freshness"]["themes"]

    def test_one_delisted_theme_does_not_make_the_dataset_stale(self):
        self.seed({"s1": {"final": 50, "branch": 20}})
        self.seed_themes([("A", "active", "2026-08-03"), ("B", "active", "2026-08-03"),
                          ("GONE", "stale", "2026-07-20")])
        themes = self.freshness()
        self.assertFalse(themes["stale"])
        self.assertEqual(themes["date"], "2026-08-03")
        self.assertNotIn("題材分類", "".join(self.radar()["summary_text"]))

    def test_a_missed_monday_import_is_stale(self):
        self.seed({"s1": {"final": 50, "branch": 20}})
        self.seed_themes([("A", "active", "2026-07-28")])     # 7 天前的週二
        self.assertTrue(self.freshness()["stale"])

    def test_six_days_is_still_fresh(self):
        self.seed({"s1": {"final": 50, "branch": 20}})
        self.seed_themes([("A", "active", "2026-07-29")])
        self.assertFalse(self.freshness()["stale"])

    def test_no_active_theme_at_all_is_stale(self):
        self.seed({"s1": {"final": 50, "branch": 20}})
        self.seed_themes([("A", "stale", "2026-08-03")])
        self.assertTrue(self.freshness()["stale"])

    def test_no_theme_rows_is_stale(self):
        self.seed({"s1": {"final": 50, "branch": 20}})
        self.assertTrue(self.freshness()["stale"])


if __name__ == "__main__":
    unittest.main()
