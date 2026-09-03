"""docs/37 C: 題材 lifecycle、export 與 H1 fail-closed 契約。"""
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json
from radar.importer import import_themes
from radar.pocket import hot_theme_names
from radar.theme_lifecycle import displayed_status


class ThemeLifecycleTests(unittest.TestCase):
    D = "2026-08-27"
    P = "2026-08-26"

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

    def test_ttl_and_retired_lifecycle(self):
        self.assertEqual(displayed_status("active", self.D, None, self.D), "active")
        self.assertEqual(displayed_status("active", "2026-07-01", None, self.D), "stale")
        self.assertEqual(displayed_status("active", "2026-08-28", None, self.D), "stale")
        self.assertEqual(displayed_status("retired", self.D, None, self.D), "retired")
        self.assertIsNone(displayed_status(None, None, None, self.D))

    def test_runtime_migration_adds_lifecycle_columns_to_legacy_themes(self):
        if db._engine is not None:
            db._engine.dispose()
        legacy = Path(self._tmp.name) / "legacy.db"
        raw = sqlite3.connect(legacy)
        raw.execute("CREATE TABLE themes (id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT)")
        raw.execute("INSERT INTO themes VALUES ('A', '甲', 'fubon', '2026-07-01')")
        raw.commit()
        raw.close()
        config.DB_URL = "sqlite:///" + legacy.as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().connect() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(themes)").fetchall()}
            row = conn.exec_driver_sql("SELECT name, status FROM themes WHERE id='A'").fetchone()
        self.assertTrue({"source_updated_at", "data_date", "status"}.issubset(columns))
        self.assertEqual(row, ("甲", None))

    def test_full_source_is_the_only_path_to_active(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [{
                "id": "OLD", "name": "舊題材", "source": "fubon", "status": "stale",
            }])
        with patch("radar.providers.fubon.fetch_theme_list", return_value=[("A", "甲"), ("B", "乙")]), \
             patch("radar.providers.fubon.fetch_theme_members", side_effect=lambda code: ["1001"] if code == "A" else ["1002"]):
            result = import_themes()
        self.assertEqual(result["status"], "active")
        with db.get_engine().connect() as conn:
            rows = conn.exec_driver_sql("SELECT id, status, data_date FROM themes ORDER BY id").fetchall()
        self.assertEqual(rows[0][0:2], ("A", "active"))
        self.assertIsNotNone(rows[0][2])
        self.assertEqual(rows[-1][0:2], ("OLD", "stale"))  # missing from source is not auto-retired

    def test_full_source_does_not_revive_explicitly_retired_theme_or_membership(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [{
                "id": "R", "name": "保留停用", "source": "fubon", "status": "retired",
                "data_date": "2026-08-01",
            }])
            conn.execute(schema.stock_themes.insert(), [{"theme_id": "R", "stock_id": "1001"}])
        with patch("radar.providers.fubon.fetch_theme_list", return_value=[("R", "來源新名稱")]), \
             patch("radar.providers.fubon.fetch_theme_members", return_value=["1002"]):
            result = import_themes()
        self.assertEqual(result["status"], "active")
        with db.get_engine().connect() as conn:
            row = conn.exec_driver_sql("SELECT name, status FROM themes WHERE id='R'").fetchone()
            members = conn.exec_driver_sql("SELECT stock_id FROM stock_themes WHERE theme_id='R'").fetchall()
        self.assertEqual(row, ("保留停用", "retired"))
        self.assertEqual(members, [("1001",)])

    def test_partial_empty_and_limit_keep_existing_memberships(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [{"id": "A", "name": "甲", "source": "fubon", "status": "active"}])
            conn.execute(schema.stock_themes.insert(), [{"theme_id": "A", "stock_id": "1001"}])

        with patch("radar.providers.fubon.fetch_theme_list", return_value=[("A", "甲"), ("B", "乙")]), \
             patch("radar.providers.fubon.fetch_theme_members", side_effect=[["1002"], RuntimeError("down")]):
            partial = import_themes()
        self.assertEqual(partial["status"], "stale")

        with db.get_engine().connect() as conn:
            self.assertEqual(conn.exec_driver_sql("SELECT status FROM themes WHERE id='A'").scalar(), "stale")
            self.assertEqual(conn.exec_driver_sql("SELECT stock_id FROM stock_themes WHERE theme_id='A'").scalar(), "1001")

        with patch("radar.providers.fubon.fetch_theme_list", return_value=[("A", "甲")]), \
             patch("radar.providers.fubon.fetch_theme_members", return_value=[]):
            empty = import_themes()
        self.assertEqual(empty["status"], "stale")
        with patch("radar.providers.fubon.fetch_theme_list", return_value=[("A", "甲")]), \
             patch("radar.providers.fubon.fetch_theme_members", return_value=["1002"]):
            limited = import_themes(limit=1)
        self.assertEqual(limited["status"], "stale")

    @staticmethod
    def _run(names, empties):
        """Run import_themes over ``names`` where ``empties`` return no members."""
        members = {code: ([] if code in empties else [f"100{i}"])
                   for i, code in enumerate(names)}
        with patch("radar.providers.fubon.fetch_theme_list",
                   return_value=[(code, f"題材{code}") for code in names]), \
             patch("radar.providers.fubon.fetch_theme_members",
                   side_effect=lambda code: members[code]):
            return import_themes()

    def test_successfully_observed_empty_categories_do_not_block_completion(self):
        # 台股沒有白酒/煙草類的成分股：抓得到卻沒有成員是事實，不是抓取不完整。
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [
                {"id": "B", "name": "白酒", "source": "fubon", "status": "active"},
            ])
        result = self._run(["A", "B", "C"], empties={"B"})
        self.assertEqual(result["status"], "active")
        with db.get_engine().connect() as conn:
            rows = dict(conn.exec_driver_sql(
                "SELECT id, status FROM themes ORDER BY id").fetchall())
            staged = conn.exec_driver_sql(
                "SELECT data_date, source_updated_at FROM themes WHERE id='A'").fetchone()
            empty_members = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM stock_themes WHERE theme_id='B'").scalar()
        self.assertEqual(rows, {"A": "active", "B": "stale", "C": "active"})
        self.assertTrue(all(staged))  # lifecycle columns finally get written
        self.assertEqual(empty_members, 0)

    def test_a_single_failed_fetch_still_forces_the_partial_path(self):
        with patch("radar.providers.fubon.fetch_theme_list",
                   return_value=[("A", "甲"), ("B", "乙")]), \
             patch("radar.providers.fubon.fetch_theme_members",
                   side_effect=[["1001"], RuntimeError("down")]):
            result = import_themes()
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["empty"], 0)

    def test_implausible_empty_sweep_keeps_prior_data(self):
        # 來源整體壞掉時每頁都「格式正確但空白」，不得被當成一次乾淨的全空。
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [
                {"id": "A", "name": "甲", "source": "fubon", "status": "active"}])
            conn.execute(schema.stock_themes.insert(), [{"theme_id": "A", "stock_id": "1001"}])
        names = [chr(ord("A") + i) for i in range(4)]
        result = self._run(names, empties=set(names[1:]))  # 3/4 空
        self.assertEqual(result["status"], "stale")
        with db.get_engine().connect() as conn:
            self.assertEqual(conn.exec_driver_sql(
                "SELECT status FROM themes WHERE id='A'").scalar(), "stale")
            self.assertEqual(conn.exec_driver_sql(
                "SELECT stock_id FROM stock_themes WHERE theme_id='A'").scalar(), "1001")

    def test_empty_share_threshold_boundary(self):
        names = [chr(ord("A") + i) for i in range(10)]
        self.assertEqual(self._run(names, empties=set(names[:5]))["status"], "active")   # 恰 50%
        self.assertEqual(self._run(names, empties=set(names[:6]))["status"], "stale")    # 60%

    def test_retired_survives_a_complete_run_that_contains_empties(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [{
                "id": "A", "name": "保留停用", "source": "fubon", "status": "retired"}])
            conn.execute(schema.stock_themes.insert(), [{"theme_id": "A", "stock_id": "1001"}])
        result = self._run(["A", "B", "C"], empties={"B"})
        self.assertEqual(result["status"], "active")
        with db.get_engine().connect() as conn:
            row = conn.exec_driver_sql(
                "SELECT name, status FROM themes WHERE id='A'").fetchone()
            members = conn.exec_driver_sql(
                "SELECT stock_id FROM stock_themes WHERE theme_id='A'").fetchall()
        self.assertEqual(row, ("保留停用", "retired"))
        self.assertEqual(members, [("1001",)])

    def test_source_list_failure_marks_existing_rows_stale_without_deleting(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.themes.insert(), [{"id": "A", "name": "甲", "source": "fubon", "status": "active"}])
            conn.execute(schema.stock_themes.insert(), [{"theme_id": "A", "stock_id": "1001"}])
        with patch("radar.providers.fubon.fetch_theme_list", side_effect=RuntimeError("source down")):
            result = import_themes()
        self.assertEqual(result["status"], "stale")
        with db.get_engine().connect() as conn:
            status = conn.exec_driver_sql("SELECT status FROM themes WHERE id='A'").scalar()
            member = conn.exec_driver_sql("SELECT stock_id FROM stock_themes WHERE theme_id='A'").scalar()
        self.assertEqual(status, "stale")
        self.assertEqual(member, "1001")

    def test_export_keeps_legacy_categories_but_h1_only_uses_current_active_data(self):
        ids = ["1001", "1002", "1003"]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": f"股{sid}", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1}
                for sid in ids
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 100 if day == self.P else 105,
                 "volume": 1_000_000, "turnover": 100_000_000 if day == self.P else 600_000_000}
                for sid in ids for day in (self.P, self.D)
            ])
            conn.execute(schema.themes.insert(), [
                {"id": "active", "name": "有效", "source": "fubon", "status": "active", "data_date": self.D, "source_updated_at": self.D},
                {"id": "active_alias", "name": "有效", "source": "fubon", "status": "active", "data_date": self.D, "source_updated_at": self.D},
                {"id": "stale", "name": "過時", "source": "fubon", "status": "active", "data_date": "2026-07-01", "source_updated_at": "2026-07-01"},
                {"id": "retired", "name": "停用", "source": "fubon", "status": "retired", "data_date": self.D, "source_updated_at": self.D},
                {"id": "legacy", "name": "舊格式", "source": "fubon",
                 "status": None, "data_date": None, "source_updated_at": None},
                {"id": "future", "name": "未來", "source": "fubon", "status": "active", "data_date": "2026-08-28", "source_updated_at": "2026-08-28"},
            ])
            conn.execute(schema.stock_themes.insert(), [
                {"theme_id": tid, "stock_id": sid}
                for tid in ("active", "active_alias", "stale", "retired", "legacy", "future") for sid in ids
            ])
        out = Path(self._tmp.name) / "out"
        export_json(out)
        stock = json.loads((out / "stocks" / "1001.json").read_text(encoding="utf-8"))
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        # New stock fields are optional: a pre-C snapshot has no lifecycle keys,
        # but retains every pre-existing payload field for the TypeScript fallback.
        old_json = dict(stock)
        old_json.pop("company_themes")
        old_json.pop("recent_theme_heat")
        self.assertEqual(old_json["id"], "1001")
        self.assertIn("candles", old_json)
        self.assertNotIn("company_themes", old_json)
        status = {item["name"]: item["status"] for item in stock["company_themes"]}
        self.assertEqual(status, {"有效": "active", "過時": "stale", "停用": "retired", "舊格式": None, "未來": "stale"})
        heat = {item["name"]: item for item in stock["recent_theme_heat"]}
        self.assertTrue(heat["有效"]["eligible"])
        self.assertFalse(heat["過時"]["eligible"])
        self.assertFalse(heat["停用"]["eligible"])
        self.assertFalse(heat["舊格式"]["eligible"])
        self.assertNotIn("未來", heat)  # future membership remains classified, never current heat
        codes = {tag["code"] for tag in stock["pocket_tags"]}
        self.assertIn("H1_HOT_THEME", codes)
        self.assertIn("有效", next(tag["text"] for tag in stock["pocket_tags"] if tag["code"] == "H1_HOT_THEME"))
        self.assertNotIn("未來", next(tag["text"] for tag in stock["pocket_tags"] if tag["code"] == "H1_HOT_THEME"))
        self.assertTrue(all("status" in theme and "heat_date" in theme for theme in radar["themes"]))
        self.assertNotIn("未來", [theme["name"] for theme in radar["themes"]])
        current = next(theme for theme in radar["themes"] if theme["name"] == "有效")
        self.assertEqual(current["turnover"], 1_800_000_000)  # same-name IDs do not double count
        self.assertEqual(current["vs20"], 6.0)                 # prior also deduplicates stock/date
        self.assertEqual([item["id"] for item in current["top"]], ids)
        semi = next(sector for sector in radar["sectors"] if sector["name"] == "半導體")
        sub = next(item for item in semi["subs"] if item["name"] == "有效")
        self.assertEqual(sub["turnover"], 1_800_000_000)
        self.assertEqual(sub["vs20"], 6.0)
        self.assertEqual([item["id"] for item in sub["top"]], ids)
        self.assertEqual(radar["freshness"]["themes"]["date"], self.D)
        self.assertTrue(all("_active_themes" not in item for item in radar["stocks"]))

    def test_heat_date_mismatch_and_future_data_never_make_h1_candidates(self):
        themes = [{"name": "未來", "vs20": 2.0, "turnover": 1,
                   "status": "active", "data_date": "2026-08-28", "heat_date": self.D}]
        self.assertEqual(hot_theme_names(themes, self.D), [])
        themes[0]["data_date"] = self.D
        themes[0]["heat_date"] = "2026-08-28"
        self.assertEqual(hot_theme_names(themes, self.D), [])


if __name__ == "__main__":
    unittest.main()
