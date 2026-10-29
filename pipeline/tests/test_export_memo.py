"""export 記憶(docs/44 §3.7):第二次 export 沿用第一次的純計算結果,輸出必須與全量重算逐位元相同。

情境照晚上分點輪:第一次 export → 寫入今天的權證分點列(含新分點名)＋重算分點排行統計
(branch_stock_stats / branch_rankings / tracked_branches)→ 第二次 export 寫進同一個目錄。
另一棵樹用 RADAR_EXPORT_MEMO=0 在空目錄全量重算;兩棵樹逐檔比對:位元組相同,或只差
``generated_at``(其餘鍵序、值一個都不能差)。再測各種「輸入變了」都會讓對應的段重算。
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import radar.config as config
import radar.db as db
from radar.export import export_memo
from radar.export.stock_parts import RawJSON, compose_chips, dumps_compact, CHIPS_VERSION
from tools.make_synthetic_branch_db import build

VOLATILE = {"generated_at"}


def _strip(obj):
    """generated_at 拿掉,物件保留鍵序(以 (鍵, 值) 串列比對 → 鍵序不同也算不同)。"""
    if isinstance(obj, list) and obj and all(isinstance(x, tuple) and len(x) == 2 for x in obj):
        return [(k, _strip(v)) for k, v in obj if k not in VOLATILE]
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def _pairs(text: str):
    return _strip(json.loads(text, object_pairs_hook=lambda kv: list(kv)))


def compare_trees(test: unittest.TestCase, got: Path, want: Path) -> int:
    """want 的每一個檔在 got 都要有、內容相同(位元組或只差 generated_at)。回傳比過的檔數。"""
    n = 0
    for p in sorted(want.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(want)
        q = got / rel
        test.assertTrue(q.exists(), f"missing {rel}")
        a, b = q.read_bytes(), p.read_bytes()
        n += 1
        if a == b:
            continue
        test.assertTrue(rel.suffix == ".json", f"{rel} differs")
        test.assertEqual(_pairs(a.decode("utf-8")), _pairs(b.decode("utf-8")), f"{rel} differs")
    # got 裡多出來的只能是被換掉雜湊、還在寬限期的舊 hist 檔
    extra = [p.relative_to(got) for p in got.rglob("*") if p.is_file() and not (want / p.relative_to(got)).exists()]
    test.assertTrue(all(e.parts[:2] == ("stocks", "hist") for e in extra), extra)
    return n


class ComposeChipsTest(unittest.TestCase):
    def test_compose_equals_dumps(self):
        rnd = random.Random(5)

        def value(depth=0):
            k = rnd.randrange(8 if depth < 3 else 5)
            if k == 0:
                return rnd.randint(-10**12, 10**12)
            if k == 1:
                return rnd.choice([0.1, 1.0, -0.0, 1e-300, 12345.678901234567, float("inf"), float("nan")])
            if k == 2:
                return rnd.choice(["", "富邦-新店", 'a"b\\c', " ", "x,y:{}"])
            if k == 3:
                return rnd.choice([None, True, False])
            if k == 4:
                return []
            if k in (5, 6):
                return [value(depth + 1) for _ in range(rnd.randrange(4))]
            return {rnd.choice(["a", "名", "b c", "1"]) + str(i): value(depth + 1) for i in range(rnd.randrange(4))}

        for _ in range(300):
            chips = {k: value() for k in ("branch_days", "branch_pctile_counts", "branch_tags", "branch_pnl_est")
                     if rnd.random() < 0.8}
            sid = rnd.choice(["2330", "6488", "00878"])
            want = dumps_compact({"version": CHIPS_VERSION, "id": sid, **chips})
            text, offsets = compose_chips(sid, chips)
            self.assertEqual(text, want)
            for k, (a, b) in offsets.items():
                self.assertEqual(text[a:b], dumps_compact(chips[k]))
            # 切下來的段原樣拼回去也一樣
            raw = {k: RawJSON(text[a:b]) for k, (a, b) in offsets.items()}
            self.assertEqual(compose_chips(sid, raw)[0], want)

    def test_digest_is_type_and_value_sensitive(self):
        d = export_memo.digest
        self.assertEqual(d("s", [("2026-10-01", 1, 5, 0, 5)]), d("s", [("2026-10-01", 1, 5, 0, 5)]))
        self.assertNotEqual(d("s", [("2026-10-01", 1, 5, 0, 5)]), d("s", [("2026-10-01", 1, 5.0, 0, 5)]))
        self.assertNotEqual(d("s", [("2026-10-01", 1, 5, 0, 5)]), d("s", [("2026-10-01", 1, "5", 0, 5)]))
        self.assertNotEqual(d("s", [("2026-10-01", 1, None, 0, 5)]), d("s", [("2026-10-01", 1, 0, 0, 5)]))
        self.assertNotEqual(d("s", [1, 2]), d("s", [2, 1]))
        self.assertNotEqual(d("s", "ab", "c"), d("s", "a", "bc"))


class ExportMemoEndToEnd(unittest.TestCase):
    """小型合成庫上跑真的 export_json。"""

    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.seed_db = cls.root / "seed.db"
        build(cls.seed_db, stocks=10, days=70, branches=24, warrants_per_stock=6, seed=11,
              stock_rows=(3, 15), warrant_branch_days=30)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.case = Path(self._tmp.name) / self.id().rsplit(".", 1)[-1]
        self.case.mkdir()
        self.db_path = self.case / "radar.db"
        with closing(sqlite3.connect(self.seed_db)) as src, closing(sqlite3.connect(self.db_path)) as dst:
            src.backup(dst)
        self._old = (config.DB_URL, config.DATA_DIR, db._engine)
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.case / "data"
        config.DATA_DIR.mkdir()
        db._engine = None
        db.init_db()
        from radar.compute.branch_stock_pctile_counts import compute_branch_stock_pctile_counts
        from radar.compute.compute_branch_stats import compute_all
        self.d = self._q("SELECT MAX(date) FROM daily_prices")[0][0]
        compute_all()
        compute_branch_stock_pctile_counts(as_of=self.d)
        self._env = mock.patch.dict(os.environ, {"RADAR_EXPORT_MEMO": "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        if db._engine is not None:
            db._engine.dispose()
        config.DB_URL, config.DATA_DIR, db._engine = self._old

    # ---- helpers -------------------------------------------------------------------------
    def _q(self, sql, args=()):
        with closing(sqlite3.connect(self.db_path)) as c:
            return c.execute(sql, args).fetchall()

    def _x(self, sql, args=()):
        if db._engine is not None:
            db._engine.dispose()
        with closing(sqlite3.connect(self.db_path)) as c, c:
            c.execute(sql, args)

    def _export(self, out: Path, *, memo: bool = True) -> str:
        from radar.export.json_export import export_json
        import contextlib, io
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"RADAR_EXPORT_MEMO": "1" if memo else "0"}), \
                contextlib.redirect_stdout(buf):
            export_json(out)
        line = next(l for l in buf.getvalue().splitlines() if l.startswith("export memo:"))
        return line

    @staticmethod
    def _stats(line: str) -> dict:
        return {k: (int(v) if v.lstrip("-").isdigit() else v)
                for k, v in (kv.split("=") for kv in line.split(":", 1)[1].split())}

    def _evening_phase_two(self):
        """第一段與第二段之間:今天的權證分點列(含一個新分點名)寫入、分點排行統計重算。"""
        from radar.compute.compute_branch_stats import compute_all
        wids = [r[0] for r in self._q("SELECT id FROM warrants ORDER BY id LIMIT 12")]
        self._x("INSERT INTO branch_dim (id, branch_key, broker_id, branch_name) "
                "VALUES (9001, 'W9001', '9999', '新分點-權證限定')")
        with closing(sqlite3.connect(self.db_path)) as c, c:
            c.execute("DELETE FROM branch_trades_raw WHERE date = ? AND LENGTH(stock_id) = 6", (self.d,))
            rows = []
            for i, w in enumerate(wids):
                for b in (1, 2, 3, 9001):
                    rows.append((w, self.d, b, 100 + i * 7 + b, 3, 97 + i * 7 + b, 0.5, "moneydj"))
            c.executemany("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, "
                          "net_lots, pct, source) VALUES (?,?,?,?,?,?,?,?)", rows)
            # 排行統計換一版:追蹤名單也動一下
            c.execute("DELETE FROM tracked_branches WHERE source = 'auto'")
        compute_all()

    def _stock_with_rows(self, skip=()):
        return next(r[0] for r in self._q(
            "SELECT DISTINCT stock_id FROM branch_trades_raw WHERE LENGTH(stock_id) = 4 ORDER BY stock_id")
            if r[0] not in skip)

    # ---- tests ---------------------------------------------------------------------------
    def test_second_export_identical_to_full_recompute(self):
        live, full = self.case / "live", self.case / "full"
        first = self._stats(self._export(live))
        self.assertEqual((first["loaded"], first["branch"], first["pnl"]), (0, 0, 0))
        self._evening_phase_two()
        second = self._stats(self._export(live))
        n_stocks = second["stocks"]
        self.assertEqual(second["loaded"], n_stocks)
        self.assertEqual(second["names_ok"], 1)
        self.assertEqual(second["branch"], n_stocks)      # 每一檔的分點段都沿用
        self.assertEqual(second["pnl"], n_stocks)
        self.assertEqual(second["pctile"], n_stocks)
        self.assertEqual(second["levels"], n_stocks)
        self.assertEqual(second["chips_bad"], 0)
        off = self._stats(self._export(full, memo=False))
        self.assertEqual((off["enabled"], off["branch"]), (0, 0))
        self.assertGreater(compare_trees(self, live, full), 50)
        # 第二段確實有東西變了(不是兩次一模一樣的空測試)
        chips = json.loads((live / "stocks" / "chips" / f"{self._stock_with_rows()}.json").read_text("utf-8"))
        self.assertIn("branch_tags", chips)
        wb = [(live / "branches" / f"warrant_branches_{tf}.json").read_text("utf-8")
              for tf in ("1d", "2d", "5d", "30d", "120d")]
        self.assertIn("新分點-權證限定", "".join(wb))
        # 第三次(沒有任何變動)仍全部命中,輸出不變
        third = self._stats(self._export(live))
        self.assertEqual(third["branch"], n_stocks)
        compare_trees(self, live, full)

    def test_changed_branch_row_or_price_invalidates(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        self._evening_phase_two()
        sid_b = self._stock_with_rows()
        sid_p = self._stock_with_rows(skip={sid_b})
        # 一列舊的現股分點列改了張數;另一檔一天的收盤改了(都不是今天)
        old_day = self._q("SELECT date FROM branch_trades_raw WHERE stock_id = ? AND date < ? "
                          "ORDER BY date DESC LIMIT 1", (sid_b, self.d))[0][0]
        self._x("UPDATE branch_trades_raw SET buy_lots = buy_lots + 7, net_lots = net_lots + 7 "
                "WHERE stock_id = ? AND date = ? AND branch_id = (SELECT MIN(branch_id) FROM branch_trades_raw "
                "WHERE stock_id = ? AND date = ?)", (sid_b, old_day, sid_b, old_day))
        p_day = self._q("SELECT date FROM daily_prices WHERE stock_id = ? AND date < ? ORDER BY date DESC "
                        "LIMIT 1 OFFSET 3", (sid_p, self.d))[0][0]
        self._x("UPDATE daily_prices SET close = close * 1.01 WHERE stock_id = ? AND date = ?", (sid_p, p_day))
        st = self._stats(self._export(live))
        n = st["stocks"]
        self.assertEqual(st["branch"], n - 1)          # 只有改了分點列的那檔重算 branch_days
        self.assertEqual(st["pnl"], n - 2)             # 損益:分點列那檔 + 收盤那檔
        self.assertEqual(st["levels"], n - 1)          # 價格位置:收盤那檔
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_adj_factor_change_invalidates(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        sid = self._stock_with_rows()
        self._x("UPDATE daily_prices SET adj_factor = 0.9 WHERE stock_id = ? AND date < "
                "(SELECT MAX(date) FROM daily_prices WHERE stock_id = ?)", (sid, sid))
        st = self._stats(self._export(live))
        self.assertEqual(st["levels"], st["stocks"] - 1)
        self.assertEqual(st["pnl"], st["stocks"] - 1)
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_pctile_snapshot_change_invalidates(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        sid = self._stock_with_rows()
        self._x("UPDATE branch_stock_pctile_counts SET buy_pctile_known = buy_pctile_known + 3 "
                "WHERE stock_id = ? AND rowid = (SELECT MIN(rowid) FROM branch_stock_pctile_counts "
                "WHERE stock_id = ?)", (sid, sid))
        st = self._stats(self._export(live))
        self.assertEqual(st["pctile"], st["stocks"] - 1)
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_branch_rename_disables_branch_reuse(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        self._x("UPDATE branch_dim SET branch_name = branch_name || '(改名)' WHERE id = 1")
        st = self._stats(self._export(live))
        self.assertEqual((st["names_ok"], st["branch"], st["pnl"]), (0, 0, 0))
        self.assertGreater(st["levels"], 0)
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_orphan_row_reload_disables_and_drops_memo(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        sid = self._stock_with_rows()
        self._x("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, net_lots, pct, source) "
                "VALUES (?, ?, 77777, 5, 0, 5, 0, 'x')", (sid, self.d))
        st = self._stats(self._export(live))
        self.assertGreaterEqual(st["reloads"], 1)
        self.assertFalse(export_memo.memo_path(live).exists())    # 重讀過 → 不留記憶
        self._export(full, memo=False)
        compare_trees(self, live, full)
        st = self._stats(self._export(live))
        self.assertEqual(st["loaded"], 0)

    def test_rename_seen_by_mid_run_reload_stops_reuse(self):
        """不持鎖的並行 export:迴圈中途因孤兒列重讀查表時,剛好有分點改名。之後的個股照舊程式
        會用新名字——記憶命中的那幾檔不可以還拿上一次(舊名字)的 branch_days。"""
        from radar.export import json_export as je
        live, full = self.case / "live", self.case / "full"
        order: list[str] = []
        real_raw = je._branch_history_raw

        def spy(conn, sid, d):
            order.append(sid)
            return real_raw(conn, sid, d)

        with mock.patch.object(je, "_branch_history_raw", spy):
            self._export(live)
        with_rows = {r[0] for r in self._q(
            "SELECT DISTINCT stock_id FROM branch_trades_raw WHERE LENGTH(stock_id) = 4 AND branch_id = 1")}
        first = next(s for s in order if s in with_rows)
        self._x("INSERT INTO branch_trades_raw (stock_id, date, branch_id, buy_lots, sell_lots, net_lots, pct, source) "
                "VALUES (?, ?, 77777, 5, 0, 5, 0, 'x')", (first, self.d))
        name1 = self._q("SELECT branch_name FROM branch_dim WHERE id = 1")[0][0]
        real_lookup = je._BranchNames.lookup_missing

        def rename_then_lookup(names, conn, bid):
            conn.exec_driver_sql("UPDATE branch_dim SET branch_name = ? WHERE id = 1", (name1 + "(新)",))
            return real_lookup(names, conn, bid)

        with mock.patch.object(je._BranchNames, "lookup_missing", rename_then_lookup):
            st = self._stats(self._export(live))
            self._x("UPDATE branch_dim SET branch_name = ? WHERE id = 1", (name1,))
            self._export(full, memo=False)
        self.assertGreaterEqual(st["reloads"], 1)
        self.assertGreater(len([s for s in order[order.index(first) + 1:] if s in with_rows]), 0)
        compare_trees(self, live, full)

    def test_tampered_chips_file_is_not_trusted(self):
        live, full = self.case / "live", self.case / "full"
        self._export(live)
        sid = self._stock_with_rows()
        p = live / "stocks" / "chips" / f"{sid}.json"
        p.write_text(p.read_text("utf-8").replace('"version":2', '"version":2 ', 1), encoding="utf-8")
        st = self._stats(self._export(live))
        self.assertEqual(st["chips_bad"], 1)
        self.assertEqual(st["branch"], st["stocks"] - 1)
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_code_change_or_new_data_day_misses(self):
        live = self.case / "live"
        self._export(live)
        with mock.patch.object(export_memo, "_SALT", "different-code"):
            st = self._stats(self._export(live))
        self.assertEqual(st["loaded"], 0)
        # 新的資料日(14:05 匯入今天的報價):分點/損益/價格位置的摘要含 d → 全部重算;
        # 分位計數不看 d(那張表 00:05 才換)→ 照樣沿用。
        self._export(live)
        nxt = "2026-10-05"
        self._x("INSERT INTO daily_prices (stock_id, date, open, high, low, close, adj_factor, volume, turnover) "
                "SELECT stock_id, ?, open, high, low, close, adj_factor, volume, turnover FROM daily_prices "
                "WHERE date = ?", (nxt, self.d))
        st = self._stats(self._export(live))
        self.assertEqual((st["branch"], st["pnl"], st["levels"]), (0, 0, 0))
        self.assertEqual(st["pctile"], st["stocks"])
        full = self.case / "full"
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_source_changed_on_disk_mid_run_is_not_saved(self):
        """verifier 2026-10-25:正式機 pipeline 是 bind mount,sync_code(git pull)可能在 export 跑到一半
        換掉原始碼。程式雜湊是匯入時的快照;存檔前磁碟上的不同 → 不存,下一個行程(新雜湊)全算。"""
        import shutil
        from radar.export import json_export as je
        tree = self.case / "radar_src"
        shutil.copytree(Path(export_memo.__file__).resolve().parents[1], tree,
                        ignore=shutil.ignore_patterns("__pycache__"))
        live, full = self.case / "live", self.case / "full"
        with mock.patch.object(export_memo, "_PKG_ROOT", tree):
            with mock.patch.object(export_memo, "_SALT", export_memo.disk_salt()):   # 匯入時的快照
                st = self._stats(self._export(live))
                self.assertEqual(st["saved"], "saved")
                # 匯入之後、export 開跑之前就 pull 了(verifier 的重現:雜湊若在建 ExportMemo 時才讀
                # 磁碟,舊程式的輸出會被存在新程式的雜湊下)
                f0 = tree / "compute" / "branch_interval_pnl.py"
                f0.write_text(f0.read_text("utf-8").replace('"pnl-avgcost-v1"', '"pnl-avgcost-v2"'),
                              encoding="utf-8")
                st = self._stats(self._export(live))
                self.assertEqual(st["saved"], "code_changed")
                self.assertFalse(export_memo.memo_path(live).exists())
                f0.write_text(f0.read_text("utf-8").replace('"pnl-avgcost-v2"', '"pnl-avgcost-v1"'),
                              encoding="utf-8")
                self.assertEqual(self._stats(self._export(live))["saved"], "saved")
                real_levels = je.compute_price_levels
                edited = []

                def pull_mid_run(*a, **kw):
                    if not edited:      # 迴圈第一檔時「git pull」:價格位置的版本號改了
                        f = tree / "compute" / "price_levels.py"
                        f.write_text(f.read_text("utf-8") + "\n# VERSION bumped by a pull\n", encoding="utf-8")
                        edited.append(f)
                    return real_levels(*a, **kw)

                self._x("UPDATE daily_prices SET close = close * 1.01 WHERE date = ?", (self.d,))
                with mock.patch.object(je, "compute_price_levels", pull_mid_run):
                    st = self._stats(self._export(live))
                self.assertTrue(edited)
                self.assertEqual(st["saved"], "code_changed")
                self.assertFalse(export_memo.memo_path(live).exists())
            # 下一個行程:匯入時看到的是新程式
            with mock.patch.object(export_memo, "_SALT", export_memo.disk_salt()):
                st = self._stats(self._export(live))
                self.assertEqual((st["loaded"], st["branch"], st["levels"]), (0, 0, 0))
        self._export(full, memo=False)
        compare_trees(self, live, full)

    def test_save_failure_never_aborts_export(self):
        live, full = self.case / "live", self.case / "full"
        self._export(full, memo=False)
        # ① 記憶檔的路徑被一個目錄佔住
        export_memo.memo_path(live).mkdir(parents=True)
        st = self._stats(self._export(live))
        self.assertEqual(st["saved"], "error")
        compare_trees(self, live, full)          # 後面的 groups/branches/rankings 照樣寫完
        export_memo.memo_path(live).rmdir()
        # ② export-memo 本身是一個檔案
        memo_dir = export_memo.memo_path(live).parent
        memo_dir.rmdir()
        memo_dir.write_text("not a dir", encoding="utf-8")
        st = self._stats(self._export(live))
        self.assertEqual((st["saved"], st["loaded"]), ("error", 0))
        compare_trees(self, live, full)
        # ③ 寫入時出錯(磁碟滿):tmp 不留下,舊記憶檔刪掉
        memo_dir.unlink()
        self._export(live)
        self.assertTrue(export_memo.memo_path(live).exists())
        with mock.patch("pathlib.Path.write_text", side_effect=OSError(28, "No space left on device")):
            from radar.export.export_memo import ExportMemo
            m = ExportMemo(live, d=self.d, names={})
            self.assertEqual(m.save(reloaded=False), "error")
        self.assertFalse(export_memo.memo_path(live).exists())
        self.assertEqual([p.name for p in memo_dir.iterdir() if ".tmp-" in p.name], [])

    def test_tmp_names_are_unique_per_save(self):
        """docker --init:每個容器的 PID 都一樣,tmp 名不可只靠 PID。"""
        from radar.export.export_memo import ExportMemo
        live = self.case / "live"
        seen = []
        real_replace = os.replace

        def spy(src, dst):
            seen.append(Path(src).name)
            return real_replace(src, dst)

        with mock.patch("os.replace", spy):
            for _ in range(2):
                ExportMemo(live, d=self.d, names={}).save(reloaded=False)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])

    def test_disabled_writes_nothing(self):
        live = self.case / "live"
        st = self._stats(self._export(live, memo=False))
        self.assertEqual(st["enabled"], 0)
        self.assertFalse(export_memo.memo_path(live).exists())


if __name__ == "__main__":
    unittest.main()
