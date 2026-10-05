# -*- coding: utf-8 -*-
"""docs/44 P1(§3.2)個股 JSON 拆檔:core + hist(雜湊檔名)+ chips。

純函式:split/merge 互為反函式、cut 邊界、沒有 chips 鍵、沒有早於 cut 的 K 線。
種子 DB 匯出:舊單一檔逐位元不變、三份接回 == 舊檔、聯集股才有 hist、hist 內容不變
就不重寫、退出聯集就刪檔、--no-legacy-stocks、--size-report、--verify-split。
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json
from radar.export.stock_parts import (
    CHIPS_KEYS,
    StockPartsWriter,
    hist_cut,
    merge_stock_parts,
    read_merged_stock,
    split_stock_payload,
    summarize_sizes,
    size_entry,
)


def _payload(n_candles: int, first: str = "2023-06-01", **extra) -> dict:
    start = date.fromisoformat(first)
    candles = [
        {"t": (start + timedelta(days=i)).isoformat(), "o": 1.0 + i, "h": 2.0 + i,
         "l": 0.5 + i, "c": 1.5 + i, "v": 10 + i, "amt": 100 + i, "af": 1.0}
        for i in range(n_candles)
    ]
    base = {
        "id": "2330", "name": "台積電", "market": "twse", "industry": "半導體",
        "candles": candles, "technical": None, "price_levels": {"status": "ok"},
        "scores": None, "reasons": [], "raw_reasons": [], "risks": [], "raw_risks": [],
        "branches": [{"name": "凱基-台北", "buy": 1, "sell": 0, "net": 1, "pct": 0.1}],
        "branch_history": [{"t": "2024-01-02", "branches": [{"n": "凱基-台北", "b": 1, "s": 0, "net": 1}]}],
        "branch_pctile_counts": {"version": 2, "short": {}, "long": {}},
        "branch_tags": {"as_of": "2024-01-02", "tracked": []},
        "warrant": None, "warrant_history": [], "active_warrants": [],
        "insti_history": [], "margin_history": [], "holders_history": [],
        "directors_latest": None,
        "branch_pnl_est": {"as_of": "2024-01-02", "windows": {}},
        "futures": {"version": 1, "contracts": []},
    }
    base.update(extra)
    return base


class SplitMergeTests(unittest.TestCase):
    def test_hist_cut_is_jan_1_two_years_back(self):
        self.assertEqual(hist_cut("2026-10-05"), "2024-01-01")
        self.assertEqual(hist_cut("2026-01-02"), "2024-01-01")

    def test_round_trip_with_cut(self):
        p = _payload(400, first="2023-06-01")
        parts = split_stock_payload(p, cut="2024-01-01")
        core, hist, chips = parts["core"], parts["hist"], parts["chips"]
        # K 線:cut 以前進 hist,cut 當天起留核心
        self.assertEqual(hist["bars"], len([c for c in p["candles"] if c["t"] < "2024-01-01"]))
        self.assertEqual(hist["candles"][-1]["t"], "2023-12-31")
        self.assertEqual(core["candles"][0]["t"], "2024-01-01")
        self.assertEqual(hist["candles"] + core["candles"], p["candles"])
        # chips 四鍵離開核心
        for k in CHIPS_KEYS:
            self.assertNotIn(k, core)
            self.assertIn(k, chips)
        # 指標
        self.assertEqual(core["parts"]["version"], 1)
        self.assertRegex(core["parts"]["hist"]["file"], r"^hist/2330\.[0-9a-f]{8}\.json$")
        self.assertEqual(core["parts"]["hist"]["cut"], "2024-01-01")
        self.assertEqual(core["parts"]["hist"]["first"], "2023-06-01")
        self.assertEqual(core["parts"]["chips"], {"file": "chips/2330.json", "keys": list(CHIPS_KEYS)})
        # 接回 == 原 payload,連鍵序都一樣
        merged = merge_stock_parts(core, hist, {"version": 1, "id": "2330", **chips})
        self.assertEqual(merged, p)
        self.assertEqual(list(merged.keys()), list(p.keys()))
        self.assertEqual(json.dumps(merged, ensure_ascii=False), json.dumps(p, ensure_ascii=False))
        # 原 payload 沒被改到
        self.assertIn("branch_history", p)
        self.assertEqual(len(p["candles"]), 400)

    def test_no_cut_keeps_all_candles(self):
        p = _payload(50)
        parts = split_stock_payload(p, cut=None)
        self.assertIsNone(parts["hist"])
        self.assertIsNone(parts["hist_name"])
        self.assertEqual(parts["core"]["candles"], p["candles"])
        self.assertIsNone(parts["core"]["parts"]["hist"])
        self.assertEqual(merge_stock_parts(parts["core"], None, parts["chips"]), p)

    def test_cut_before_first_candle_means_no_hist(self):
        p = _payload(50, first="2025-03-01")
        parts = split_stock_payload(p, cut="2024-01-01")
        self.assertIsNone(parts["hist"])
        self.assertEqual(merge_stock_parts(parts["core"], None, parts["chips"]), p)

    def test_missing_chips_keys_are_not_invented(self):
        p = _payload(10)
        del p["branch_pnl_est"]
        del p["futures"]
        parts = split_stock_payload(p, cut=None)
        self.assertEqual(parts["core"]["parts"]["chips"]["keys"],
                         ["branch_history", "branch_pctile_counts", "branch_tags"])
        merged = merge_stock_parts(parts["core"], None, parts["chips"])
        self.assertEqual(merged, p)
        self.assertEqual(list(merged.keys()), list(p.keys()))

    def test_hash_follows_content(self):
        a = split_stock_payload(_payload(400), cut="2024-01-01")
        b = split_stock_payload(_payload(400), cut="2024-01-01")
        self.assertEqual(a["hist_name"], b["hist_name"])
        p2 = _payload(400)
        p2["candles"][0]["af"] = 0.5  # 除權息重算
        c = split_stock_payload(p2, cut="2024-01-01")
        self.assertNotEqual(a["hist_name"], c["hist_name"])

    def test_writer_reuses_unchanged_hist_and_drops_stale(self):
        with TemporaryDirectory() as tmp:
            stock_dir = Path(tmp)
            w = StockPartsWriter(stock_dir)
            parts = split_stock_payload(_payload(400), cut="2024-01-01")
            w.write(parts)
            w.finish()
            self.assertEqual((w.hist_written, w.hist_reused), (1, 0))
            self.assertTrue((stock_dir / parts["hist_name"]).exists())
            index = json.loads((stock_dir / "hist" / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["2330"]["file"], parts["hist_name"])
            self.assertEqual(read_merged_stock(stock_dir, "2330"), _payload(400))

            # 第二輪:內容相同 → 不重寫;另一個 id 的舊雜湊檔與不再匯出的 id 都被刪
            stale = stock_dir / "hist" / "2330.deadbeef.json"
            stale.write_text("{}", encoding="utf-8")
            gone = stock_dir / "hist" / "9999.00000000.json"
            gone.write_text("{}", encoding="utf-8")
            w2 = StockPartsWriter(stock_dir)
            w2.write(split_stock_payload(_payload(400), cut="2024-01-01"))
            w2.finish()
            self.assertEqual((w2.hist_written, w2.hist_reused), (0, 1))
            self.assertFalse(stale.exists())
            self.assertFalse(gone.exists())
            self.assertEqual(sorted(p.name for p in (stock_dir / "hist").glob("*.json")),
                             sorted([Path(parts["hist_name"]).name, "index.json"]))

            # 第三輪:這檔退出聯集(cut=None)→ 它的 hist 也刪
            w3 = StockPartsWriter(stock_dir)
            w3.write(split_stock_payload(_payload(400), cut=None))
            w3.finish()
            self.assertEqual([p.name for p in (stock_dir / "hist").glob("*.json")], ["index.json"])

    def test_size_report_groups(self):
        entries = {"A": size_entry(_payload(10)), "B": size_entry(_payload(20)), "C": size_entry(_payload(30))}
        rep = summarize_sizes(entries, {"A"})
        self.assertEqual(rep["union"]["stocks"], 1)
        self.assertEqual(rep["other"]["stocks"], 2)
        self.assertEqual(rep["other"]["keys"]["candles"]["n"], 2)
        self.assertGreater(rep["other"]["keys"]["_total"]["max"], rep["union"]["keys"]["_total"]["max"])


def _dates(n: int, end: str) -> list[str]:
    last = date.fromisoformat(end)
    return [(last - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


class ExportSplitTests(unittest.TestCase):
    """種子 DB:2330 成交 2 億 → 熱門榜 → 聯集(全歷史,跨 cut);2317 成交金額 NULL → 非聯集。"""

    D = "2026-07-09"

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        days = _dates(1000, self.D)  # 2023-10-14 起;cut = hist_cut("2026-07-09") = 2024-01-01 之前約 79 根
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "industry": "半導體", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "industry": "電子", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": day, "open": 100.0 + i % 7, "high": 101.0 + i % 7,
                 "low": 99.0 + i % 7, "close": 100.0 + i % 7, "volume": 5_000_000, "turnover": 200_000_000}
                for i, day in enumerate(days)
            ])
            conn.execute(schema.daily_prices.insert(), [
                # turnover NULL:熱門榜(不足 15 檔時補滿)也挑不到它 → 非聯集
                {"stock_id": "2317", "date": day, "open": 50.0, "high": 51.0, "low": 49.0,
                 "close": 50.0, "volume": 1_000_000, "turnover": None}
                for day in days
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _read(self, out: Path, rel: str) -> dict:
        return json.loads((out / rel).read_text(encoding="utf-8"))

    def test_export_writes_three_layouts_that_merge_back(self):
        out = Path(self._tmp.name) / "out"
        report = Path(self._tmp.name) / "sizes.json"
        info = export_json(out, verify_split=True, size_report=report)
        radar = self._read(out, "radar.json")
        union_ids = {s["id"] for s in radar["stocks"]}
        self.assertIn("2330", union_ids)
        self.assertNotIn("2317", union_ids)
        cut = hist_cut(self.D)
        self.assertEqual(cut, "2024-01-01")

        # 聯集股:core + hist + chips 接回 == 舊單一檔
        legacy = self._read(out, "stocks/2330.json")
        core = self._read(out, "stocks/core/2330.json")
        self.assertEqual(core["parts"]["hist"]["cut"], cut)
        hist = self._read(out, core["parts"]["hist"]["file"].replace("hist/", "stocks/hist/"))
        chips = self._read(out, "stocks/chips/2330.json")
        self.assertEqual(hist["bars"], len([c for c in legacy["candles"] if c["t"] < cut]))
        self.assertGreater(hist["bars"], 0)
        self.assertEqual(core["candles"][0]["t"], min(c["t"] for c in legacy["candles"] if c["t"] >= cut))
        self.assertEqual(merge_stock_parts(core, hist, chips), legacy)
        self.assertEqual(read_merged_stock(out / "stocks", "2330"), legacy)
        for k in CHIPS_KEYS:
            self.assertNotIn(k, core)
        self.assertEqual(set(chips) - {"version", "id"}, set(core["parts"]["chips"]["keys"]))
        self.assertEqual(info["hist_written"], 1)

        # 非聯集股:沒有 hist,K 線全在核心(600 根上限照舊)
        legacy2 = self._read(out, "stocks/2317.json")
        core2 = self._read(out, "stocks/core/2317.json")
        self.assertIsNone(core2["parts"]["hist"])
        self.assertEqual(len(core2["candles"]), 600)
        self.assertEqual(merge_stock_parts(core2, None, self._read(out, "stocks/chips/2317.json")), legacy2)

        index = self._read(out, "stocks/hist/index.json")
        self.assertEqual(list(index), ["2330"])
        self.assertEqual(index["2330"]["file"], core["parts"]["hist"]["file"])

        # 新檔緊湊序列化;舊檔維持原本有空白的序列化
        self.assertNotIn(": ", (out / "stocks/core/2330.json").read_text(encoding="utf-8")[:200])
        self.assertIn(": ", (out / "stocks/2330.json").read_text(encoding="utf-8")[:200])

        # 大小報告
        rep = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual((rep["union"]["stocks"], rep["other"]["stocks"]), (1, 1))
        self.assertIn("candles", rep["union"]["keys"])

        # 第二輪:hist 內容相同 → 不重寫(檔名相同、hist_written=0)
        before = (out / "stocks/hist").glob("2330.*.json")
        before_names = sorted(p.name for p in before)
        info2 = export_json(out)
        self.assertEqual((info2["hist_written"], info2["hist_reused"]), (0, 1))
        self.assertEqual(sorted(p.name for p in (out / "stocks/hist").glob("2330.*.json")), before_names)

    def test_no_legacy_stocks_flag(self):
        out = Path(self._tmp.name) / "out"
        export_json(out, legacy_stocks=False)
        self.assertFalse((out / "stocks/2330.json").exists())
        self.assertTrue((out / "stocks/core/2330.json").exists())
        self.assertTrue((out / "stocks/chips/2330.json").exists())
        merged = read_merged_stock(out / "stocks", "2330")
        self.assertEqual(merged["id"], "2330")
        self.assertNotIn("parts", merged)
        self.assertIn("branch_history", merged)


if __name__ == "__main__":
    unittest.main()
