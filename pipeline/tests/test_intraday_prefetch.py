"""docs/50 §3.1(2026-10-19):Fugle 抓取搬出 export-json。

* 等價鎖:同一個 DB、同一組(假的)Fugle 回應,「export 自己抓」(舊,``fetch=True``)與
  「fetch-intraday 先抓、export 只讀快取」(新)寫出的每一個檔逐位元相同(``generated_at`` 除外),
  快取也相同,而且打 Fugle 的次數與順序相同(速率用量不變)。
* export 預設(``fetch=False``)一個請求都不發、快取一個位元都不寫。
* ``union_only`` 與 export 的聯集同一份、不寫任何檔;開關(``--fetch`` / ``RADAR_EXPORT_FETCH``)。
不發網路。
"""
import json
import os
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import cli, schema
from radar.export import intraday_bars as ib
from radar.export import intraday_prefetch, json_export, spark_day
from radar.export.json_export import export_json, export_fetch_from_env

DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10")
D = DATES[-1]
IDS = ("A1", "A2", "F3", "F4", "A5")   # F3:當日分時抓失敗;F4:歷史 5 分 K 抓失敗
GEN_AT = re.compile(rb'"generated_at":\s*"[^"]*"')


def _row(day: str, hhmm: str, px: float, v: int = 1) -> dict:
    return {"date": f"{day}T{hhmm}:00.000+08:00", "open": px, "high": px + 0.5,
            "low": px - 0.25, "close": px, "volume": v}


def _day_rows(day: str, px: float) -> list[dict]:
    out, t = [], datetime(2000, 1, 1, 9, 0)
    while t.strftime("%H:%M") <= "13:25":
        out.append(_row(day, t.strftime("%H:%M"), px))
        t += timedelta(minutes=7)
    out.append(_row(day, "13:30", px, 9))
    return out


class _FakeFugle:
    """記下每一次請求;回應只由 (代號, 日子) 決定,兩條路徑拿到的一模一樣。"""

    def __init__(self):
        self.calls: list[tuple] = []

    def sparks(self, ids):
        self.calls.append(("spark", tuple(ids)))
        out = {}
        for sid in ids:
            if sid == "F3":
                continue
            px = 100 + IDS.index(sid)
            out[sid] = {"date": D, "open": float(px), "closes": [float(px), px + 0.5, px + 1.25],
                        "rows": _day_rows(D, px)}
        return out

    def hist(self, sid, date_from, date_to):
        self.calls.append(("hist", sid, date_from, date_to))
        if sid == "F4":
            return None
        px = 50 + IDS.index(sid)
        return [r for d in DATES if date_from <= d <= date_to for r in _day_rows(d, px)]


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class _DbCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = self.root / "data0"
        config.DB_URL = "sqlite:///" + (self.root / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": sid, "market": "twse", "type": "stock", "is_active": 1}
                for sid in IDS])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": dt, "close": 100.0 + i + (1 if dt == D else 0),
                 "volume": 1000 * (i + 1), "turnover": 300_000_000 * (i + 1)}
                for i, sid in enumerate(IDS) for dt in DATES])
        self._old_env = {k: os.environ.get(k) for k in ("FUGLE_API_KEY", "RADAR_EXPORT_FETCH")}
        os.environ["FUGLE_API_KEY"] = "k"
        os.environ.pop("RADAR_EXPORT_FETCH", None)
        self.fugle = _FakeFugle()
        self._patches = [
            patch.object(spark_day, "fetch_intraday_sparks", self.fugle.sparks),
            patch.object(spark_day, "taipei_today", lambda: D),
            patch.object(ib, "taipei_today", lambda: D),
            patch.object(ib, "_default_fetch_hist", lambda key: self.fugle.hist),
        ]
        for p in self._patches:
            p.start()
        self._reset_minute_rows()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._reset_minute_rows()
        self._tmp.cleanup()

    @staticmethod
    def _reset_minute_rows():
        spark_day._minute_rows, spark_day._minute_rows_date = {}, None

    def _use_data_dir(self, name: str) -> Path:
        config.DATA_DIR = self.root / name
        self._reset_minute_rows()
        return config.DATA_DIR


class SplitFetchParityTests(_DbCase):
    def test_prefetch_then_cache_only_export_is_byte_identical_to_in_export_fetch(self):
        # 舊:export 自己抓
        data_old = self._use_data_dir("data_old")
        out_old = self.root / "out_old"
        export_json(out_old, fetch=True)
        calls_old = list(self.fugle.calls)
        self.fugle.calls.clear()

        # 新:先抓進快取(不寫任何輸出),再只讀快取 export
        data_new = self._use_data_dir("data_new")
        out_new = self.root / "out_new"
        stats = intraday_prefetch.prefetch_intraday(out_new, today=D)
        self.assertTrue(stats["ok"])
        self.assertEqual(_tree(out_new), {}, "fetch-intraday 不寫任何輸出檔")
        calls_new = list(self.fugle.calls)
        self.assertEqual(calls_new, calls_old, "同樣的請求、同樣的順序(速率用量不變)")
        self.assertTrue(any(c[0] == "spark" for c in calls_old)
                        and any(c[0] == "hist" for c in calls_old), "假 Fugle 兩個端點都要被打到")

        cache_before_export = _tree(data_new)
        export_json(out_new)          # 預設 = fetch off(RADAR_EXPORT_FETCH 未設)
        self.assertEqual(self.fugle.calls, calls_new, "export 不發任何請求")
        self.assertEqual(_tree(data_new), cache_before_export, "export 不寫快取")

        old, new = _tree(out_old), _tree(out_new)
        self.assertEqual(sorted(old), sorted(new))
        diffs = [k for k in old if GEN_AT.sub(b"", old[k]) != GEN_AT.sub(b"", new[k])]
        self.assertEqual(diffs, [], "除了 generated_at 必須逐位元相同")

        # 快取也一樣(spark_day.json + intraday5/)
        cache_keys = [k for k in _tree(data_old) if k == "spark_day.json" or k.startswith("intraday5/")]
        self.assertIn("spark_day.json", cache_keys)
        self.assertTrue(any(k.startswith("intraday5/") for k in cache_keys))
        self.assertEqual({k: _tree(data_old)[k] for k in cache_keys},
                         {k: _tree(data_new)[k] for k in cache_keys})

        # 有意義的內容:分時掛上了(F3 沒有)、分K 檔寫了(F4 只有當日那一天)
        radar = json.loads((out_new / "radar.json").read_text(encoding="utf-8"))
        with_spark = sorted(s["id"] for s in radar["stocks"] if s.get("spark_day"))
        self.assertEqual(with_spark, ["A1", "A2", "A5", "F4"])
        intraday = sorted(k for k in new if k.startswith("stocks/intraday/"))
        self.assertEqual(intraday, [f"stocks/intraday/{s}.json" for s in ("A1", "A2", "A5", "F3", "F4")])

    def test_cache_only_export_without_prefetch_fetches_nothing(self):
        data = self._use_data_dir("data_cold")
        out = self.root / "out_cold"
        export_json(out)
        self.assertEqual(self.fugle.calls, [], "fetch=False:一個請求都沒有")
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        self.assertFalse(any(s.get("spark_day") for s in radar["stocks"]))
        self.assertFalse((out / "stocks" / "intraday").exists())
        self.assertFalse((data / "spark_day.json").exists())
        self.assertFalse((data / "intraday5").exists(), "快取唯讀:不建目錄、不寫檔")

    def test_env_switch_restores_in_export_fetch(self):
        self._use_data_dir("data_env")
        os.environ["RADAR_EXPORT_FETCH"] = "1"
        export_json(self.root / "out_env")
        self.assertTrue(self.fugle.calls, "RADAR_EXPORT_FETCH=1 = 舊行為,export 自己抓")

    def test_union_only_matches_export_union_and_writes_nothing(self):
        self._use_data_dir("data_u")
        out = self.root / "out_u"
        sel = export_json(out, union_only=True)
        self.assertFalse(out.exists(), "union_only 不建輸出目錄")
        self.assertEqual(sel["date"], D)
        export_json(out)
        ids, d = ib.union_from_export(out)
        self.assertEqual((sel["union"], sel["date"]), (ids, d))

    def test_a_failing_part_is_reported_but_the_other_part_still_runs(self):
        self._use_data_dir("data_fail")

        def boom(*a, **k):
            raise RuntimeError("fugle down")
        with patch.object(intraday_prefetch, "attach_spark_day", boom), \
                self.assertLogs("radar.export.intraday_prefetch", level="WARNING"):
            stats = intraday_prefetch.prefetch_intraday(self.root / "out_f", today=D)
        self.assertFalse(stats["ok"])
        self.assertTrue(any(c[0] == "hist" for c in self.fugle.calls), "分K 那一段照跑")

    def test_not_today_gate_holds_in_prefetch(self):
        self._use_data_dir("data_gate")
        stats = intraday_prefetch.prefetch_intraday(self.root / "out_g", today="2099-01-01")
        self.assertTrue(stats["ok"])
        self.assertEqual(self.fugle.calls, [], "台北今天 ≠ 價格日 → 不打 Fugle(與 export 同一閘門)")


class SwitchAndCliTests(unittest.TestCase):
    def test_env_parsing(self):
        old = os.environ.get("RADAR_EXPORT_FETCH")
        try:
            for val, want in (("1", True), (" 1 ", True), ("0", False), ("", False), ("yes", False)):
                os.environ["RADAR_EXPORT_FETCH"] = val
                self.assertIs(export_fetch_from_env(), want, val)
            os.environ.pop("RADAR_EXPORT_FETCH")
            self.assertFalse(export_fetch_from_env())
        finally:
            if old is None:
                os.environ.pop("RADAR_EXPORT_FETCH", None)
            else:
                os.environ["RADAR_EXPORT_FETCH"] = old

    def test_cli_fetch_flag(self):
        seen = []

        def fake(out, **kw):
            seen.append(kw["fetch"])
            return {"stocks": 0, "date": D, "out": out}
        with patch.object(json_export, "export_json", fake):
            cli.main(["export-json", "--out", "x"])
            cli.main(["export-json", "--out", "x", "--fetch"])
        self.assertEqual(seen, [None, True], "不帶旗標 = 看環境變數;--fetch = 強制抓")

    def test_cli_fetch_intraday_exit_code(self):
        for ok, code in ((True, None), (False, 1)):
            with patch.object(intraday_prefetch, "prefetch_intraday", lambda out, ok=ok: {"ok": ok}):
                if code is None:
                    cli.main(["fetch-intraday"])
                else:
                    with self.assertRaises(SystemExit) as cm:
                        cli.main(["fetch-intraday"])
                    self.assertEqual(cm.exception.code, code)


class SparkCacheAtomicTests(unittest.TestCase):
    def test_save_is_atomic_and_format_unchanged(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "spark_day.json"
            stocks = {"2330": {"open": 1000.0, "closes": [1000.0, 1005.5]}, "中": {"open": 1, "closes": [1, 2]}}
            spark_day.save_cache(D, stocks, p)
            self.assertEqual(p.read_text(encoding="utf-8"),
                             json.dumps({"date": D, "stocks": stocks}, ensure_ascii=False,
                                        separators=(",", ":")))
            self.assertEqual([x.name for x in Path(tmp).iterdir()], ["spark_day.json"], "不留 tmp 檔")
            self.assertEqual(spark_day.load_cache(p)["stocks"], stocks)


if __name__ == "__main__":
    unittest.main()
