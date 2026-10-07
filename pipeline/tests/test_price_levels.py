"""價格位置(docs/45 §3 F1–F7)golden cases:只給事實,不碰分數。"""
import json
import random
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar.export.stock_parts import read_merged_stock
from radar import schema
from radar.compute.price_levels import compute_price_levels
from radar.export.json_export import export_json


def _dates(n, end=date(2026, 10, 2)):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


def _rows(closes, vols=None, spread=0.0, afs=None, dates=None):
    """(date, open, high, low, close, volume, af);spread = 高低各離收盤多少。"""
    n = len(closes)
    dates = dates or _dates(n)
    vols = vols or [1000] * n
    afs = afs or [1.0] * n
    return [(dates[i], c, c + spread, c - spread, c, vols[i], afs[i]) for i, c in enumerate(closes)]


class BasicShapes(unittest.TestCase):
    def test_no_bars_is_none(self):
        self.assertIsNone(compute_price_levels([]))

    def test_insufficient_under_20(self):
        rows = _rows([100.0] * 19)
        out = compute_price_levels(rows)
        self.assertEqual(out, {"version": 2, "status": "insufficient", "as_of": rows[-1][0], "bars": 19})

    def test_monotonic_up(self):
        closes = [100.0 + i for i in range(240)]
        out = compute_price_levels(_rows(closes, vols=[1000 + i for i in range(240)]))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["close"], 339.0)
        self.assertEqual(out["ma"]["5"], 337.0)
        self.assertEqual(out["ma"]["240"], 219.5)
        self.assertEqual(out["ma_align"], "bull")
        dates = _dates(240)
        for w in ("20", "60", "120", "240"):
            self.assertEqual(out["highs"][w], {"p": 339.0, "t": dates[-1]})
            self.assertEqual(out["lows"][w], {"p": 100.0 + 240 - int(w), "t": dates[-int(w)]})
        self.assertTrue(out["new_high_20"])
        self.assertFalse(out["new_low_20"])
        self.assertEqual(out["vol_price_2d"], "up")
        # spread 0 → 每根都是單一價位;今日那根剛好在現價,兩邊都不算
        vp = out["vol_profile"]
        self.assertEqual(vp["above"], 0.0)
        self.assertGreater(vp["below"], 0.99)
        self.assertGreater(vp["at"], 0.0)
        self.assertIsNone(out["dense_above"])
        self.assertIsNotNone(out["dense_below"])
        # spread 0 且每天 +1:每根都是跳空 1 元,但寬度 < 現價 0.5%(339 × 0.5% = 1.7)→ 不列
        self.assertEqual(out["gaps_above"], [])
        self.assertEqual(out["gaps_below"], [])
        # 收盤一路在 MA20 之上:可算的 221 根全同向 → capped
        self.assertEqual(out["ma20_streak"], {"n": 221, "side": "above", "capped": True})

    def test_monotonic_down(self):
        closes = [400.0 - i for i in range(240)]
        out = compute_price_levels(_rows(closes, vols=[1000 + i for i in range(240)]))
        self.assertEqual(out["ma_align"], "bear")
        self.assertTrue(out["new_low_20"])
        self.assertFalse(out["new_high_20"])
        self.assertEqual(out["vol_price_2d"], "down")
        self.assertEqual(out["lows"]["20"]["t"], _dates(240)[-1])
        self.assertEqual(out["vol_profile"]["below"], 0.0)
        self.assertIsNone(out["dense_below"])
        self.assertEqual(out["ma20_streak"], {"n": 221, "side": "below", "capped": True})

    def test_missing_windows_are_null_not_shortened(self):
        out = compute_price_levels(_rows([100.0 + (i % 7) for i in range(100)]))
        self.assertIsNotNone(out["ma"]["60"])
        self.assertIsNone(out["ma"]["120"])
        self.assertIsNone(out["ma"]["240"])
        self.assertIsNotNone(out["highs"]["60"])
        self.assertIsNone(out["highs"]["120"])
        self.assertIsNone(out["lows"]["240"])
        self.assertIsNone(out["vol_profile"])
        self.assertIsNone(out["dense_above"])
        self.assertIsNone(out["dense_below"])

    def test_mixed_alignment_is_neutral(self):
        # 5 日均 110 > 10 日均 100 = 20 日均 100 → 不是嚴格排列
        closes = [100.0] * 10 + [90.0] * 5 + [110.0] * 5
        out = compute_price_levels(_rows(closes))
        self.assertIsNone(out["ma_align"])

    def test_same_price_same_date_across_windows(self):
        # 最高價落在近 20 根內 → 20/60/120/240 都是同一價同一天(前端合併標最長視窗)
        closes = [100.0] * 239 + [100.0]
        closes[230] = 150.0
        out = compute_price_levels(_rows(closes))
        hs = out["highs"]
        self.assertEqual(hs["20"], hs["60"])
        self.assertEqual(hs["20"], hs["240"])
        self.assertEqual(hs["20"]["p"], 150.0)

    def test_equal_highs_take_latest_date(self):
        closes = [100.0] * 30
        closes[12] = closes[25] = 120.0
        out = compute_price_levels(_rows(closes))
        self.assertEqual(out["highs"]["20"]["t"], _dates(30)[25])


class Gaps(unittest.TestCase):
    """F9:缺口只看昨天以前、近 120 根;之後的 K 棒吃掉多少就縮多少;寬度 ≥ 現價 0.5%;每側 ≤2、近者在前。"""

    def _bars(self, n, base=100.0, spread=1.0):
        dates = _dates(n)
        return [[dates[i], base, base + spread, base - spread, base, 1000, 1.0] for i in range(n)]

    def test_up_gap_partially_filled_is_support_below(self):
        rows = self._bars(150)
        # 第 100 根跳空向上:前根 high 101,當根 low 110;之後最低 106 → 剩 101–106;現價 120 在上方
        for i in range(100, 150):
            rows[i][1:5] = [120.0, 121.0, 119.0, 120.0]
        rows[100][3] = 110.0
        rows[105][3] = 106.0
        out = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(out["gaps_below"], [{"lo": 101.0, "hi": 106.0, "t": rows[100][0]}])
        self.assertEqual(out["gaps_above"], [])

    def test_down_gap_is_resistance_above_and_filled_gap_dropped(self):
        rows = self._bars(150, base=120.0)
        # 第 100 根跳空向下:前根 low 119,當根 high 110 → 缺口 110–119;現價 100 在下方
        for i in range(100, 150):
            rows[i][1:5] = [100.0, 101.0, 99.0, 100.0]
        rows[100][2] = 110.0
        out = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(out["gaps_above"], [{"lo": 110.0, "hi": 119.0, "t": rows[100][0]}])
        # 之後有一根衝到 119.5 → 回補完 → 不列
        rows[120][2] = 119.5
        out2 = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(out2["gaps_above"], [])

    def test_today_gap_and_outside_window_excluded(self):
        rows = self._bars(240)
        # 今日跳空(由技術段「今日跳空」講,這裡不列)
        rows[-1][1:5] = [110.0, 111.0, 109.0, 110.0]
        out = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(out["gaps_below"], [])
        # 第 100 根(距今 140 根,超出 120 根視窗)的向上缺口不列;第 150 根的列
        rows = self._bars(240)
        for i in range(100, 240):
            rows[i][1:5] = [110.0, 111.0, 109.0, 110.0]
        rows[100][3] = 108.0  # 缺口 101–108
        for i in range(150, 240):
            rows[i][1:5] = [120.0, 121.0, 119.0, 120.0]
        rows[150][3] = 118.0  # 缺口 111–118
        out = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(out["gaps_below"], [{"lo": 111.0, "hi": 118.0, "t": rows[150][0]}])

    def test_nearest_two_per_side(self):
        rows = self._bars(150)
        levels = [(100, 105.0), (110, 115.0), (120, 125.0)]  # 三個向上缺口,之後價格一路在上
        for j, (idx, lo_after) in enumerate(levels):
            for i in range(idx, 150):
                p = lo_after + 1
                rows[i][1:5] = [p, p + 1, p - 1, p]
            rows[idx][3] = lo_after + 2  # 當根 low 比後面高一點,缺口 = 前根 high … 之後最低
        out = compute_price_levels([tuple(r) for r in rows])
        self.assertEqual(len(out["gaps_below"]), 2)
        # 近者在前:最後一個缺口(第 120 根)離現價最近
        self.assertEqual([g["t"] for g in out["gaps_below"]], [rows[120][0], rows[110][0]])
        self.assertTrue(out["gaps_below"][0]["hi"] > out["gaps_below"][1]["hi"])

    def test_gap_adjusted_for_split(self):
        rows = self._bars(150)
        for i in range(100, 150):
            rows[i][1:5] = [120.0, 121.0, 119.0, 120.0]
        rows[100][3] = 110.0
        plain = [tuple(r) for r in rows]
        split = [
            (t, o * 2, h * 2, l * 2, c * 2, v // 2, 0.5) if i < 120 else (t, o, h, l, c, v, af)
            for i, (t, o, h, l, c, v, af) in enumerate(plain)
        ]
        self.assertEqual(compute_price_levels(plain)["gaps_below"], compute_price_levels(split)["gaps_below"])


class Ma20Streak(unittest.TestCase):
    def test_counts_from_today_and_not_capped(self):
        closes = [100.0] * 60 + [90.0] * 5 + [110.0] * 3  # 先跌破 5 天,再站上 3 天
        out = compute_price_levels(_rows(closes))
        self.assertEqual(out["ma20_streak"], {"n": 3, "side": "above", "capped": False})
        closes = [100.0] * 60 + [90.0] * 5
        out = compute_price_levels(_rows(closes))
        self.assertEqual(out["ma20_streak"], {"n": 5, "side": "below", "capped": False})

    def test_equal_counts_as_above(self):
        out = compute_price_levels(_rows([100.0] * 30))
        self.assertEqual(out["ma20_streak"], {"n": 11, "side": "above", "capped": True})


class VolumeProfile(unittest.TestCase):
    def _three_bar_rows(self):
        # 117 根零量 + 手算三根(現價 100、bin 寬 1.00)
        dates = _dates(120)
        rows = [(dates[i], 100.0, 100.0, 100.0, 100.0, 0, 1.0) for i in range(117)]
        rows.append((dates[117], 100.0, 110.0, 90.0, 100.0, 1000, 1.0))  # 上 500 / 下 500
        rows.append((dates[118], 105.0, 105.0, 105.0, 105.0, 200, 1.0))  # 鎖死在 105
        rows.append((dates[119], 100.0, 105.0, 95.0, 100.0, 800, 1.0))   # 上 400 / 下 400
        return rows

    def test_hand_computed_three_bars(self):
        out = compute_price_levels(self._three_bar_rows())
        self.assertEqual(out["vol_profile"], {"window": 120, "above": 0.55, "below": 0.45, "at": 0.0})
        # 上方:bin5 [105,106) = 50 + 200 = 250 / 2000
        self.assertEqual(out["dense_above"], {"lo": 105.0, "hi": 106.0, "share": 0.125})
        # 下方:bin -1..-5 都是 50 + 80 = 130 → 同量取近者 [99,100)
        self.assertEqual(out["dense_below"], {"lo": 99.0, "hi": 100.0, "share": 0.065})

    def test_dense_tie_takes_nearest(self):
        dates = _dates(120)
        rows = [(dates[i], 100.0, 100.0, 100.0, 100.0, 0, 1.0) for i in range(116)]
        rows.append((dates[116], 103.5, 103.5, 103.5, 103.5, 300, 1.0))
        rows.append((dates[117], 101.5, 101.5, 101.5, 101.5, 300, 1.0))
        rows.append((dates[118], 97.5, 97.5, 97.5, 97.5, 300, 1.0))
        rows.append((dates[119], 98.5, 98.5, 98.5, 98.5, 300, 1.0))  # 今日也是單一價
        out = compute_price_levels(rows)
        # 現價 98.5、bin 寬 0.985:101.5 落 k=3、103.5 落 k=5 → 近者 k=3
        self.assertTrue(101.0 < out["dense_above"]["lo"] < 102.0)
        self.assertEqual(out["dense_above"]["share"], 0.25)
        self.assertEqual(out["dense_below"]["share"], 0.25)

    def test_limit_locked_today_counts_as_at(self):
        dates = _dates(120)
        rows = [(dates[i], 90.0, 95.0, 85.0, 90.0, 1000, 1.0) for i in range(119)]
        rows.append((dates[119], 99.0, 99.0, 99.0, 99.0, 1000, 1.0))  # 一價到底鎖漲停
        out = compute_price_levels(rows)
        vp = out["vol_profile"]
        self.assertEqual(vp["above"], 0.0)
        self.assertEqual(vp["at"], round(1 / 120, 4))
        self.assertEqual(vp["below"], round(119 / 120, 4))
        self.assertIsNone(out["dense_above"])

    def test_all_zero_volume(self):
        rows = _rows([100.0 + (i % 3) for i in range(130)], vols=[0] * 130, spread=1.0)
        out = compute_price_levels(rows)
        self.assertEqual(out["status"], "ok")
        self.assertIsNone(out["vol_profile"])
        self.assertIsNone(out["dense_above"])
        self.assertIsNone(out["vol_price_2d"])


class Adjustment(unittest.TestCase):
    def test_split_invariance(self):
        rnd = random.Random(7)
        closes, vols = [], []
        p = 100.0
        for _ in range(260):
            p = max(5.0, p + rnd.choice((-2.0, -1.0, 0.0, 1.0, 2.0)))
            closes.append(p)
            vols.append(rnd.randrange(0, 5000) * 2)
        dates = _dates(260)
        plain = [(dates[i], c, c + 1.0, c - 1.0, c, vols[i], 1.0) for i, c in enumerate(closes)]
        # 第 150 根起 1 拆 2:之前的原始價 ×2、股數 /2、af = 0.5
        split = [
            (t, o * 2, h * 2, l * 2, c * 2, v // 2, 0.5) if i < 150 else (t, o, h, l, c, v, 1.0)
            for i, (t, o, h, l, c, v, _af) in enumerate(plain)
        ]
        self.assertEqual(compute_price_levels(plain), compute_price_levels(split))

    def test_today_factor_not_one(self):
        rows = _rows([100.0 + (i % 5) for i in range(40)], afs=[0.5] * 40)
        base = _rows([100.0 + (i % 5) for i in range(40)])
        self.assertEqual(compute_price_levels(rows), compute_price_levels(base))

    def test_suspended_as_of_and_future_rows_excluded(self):
        dates = _dates(45)
        rows = _rows([100.0 + i for i in range(45)], dates=dates)
        out = compute_price_levels(rows, as_of_limit=dates[39])
        self.assertEqual(out["as_of"], dates[39])
        self.assertEqual(out["close"], 139.0)
        # 停牌:資料日比最後一根晚,as_of 仍是最後一根
        out2 = compute_price_levels(rows, as_of_limit="2099-01-01")
        self.assertEqual(out2["as_of"], dates[-1])

    def test_none_close_rows_skipped(self):
        rows = _rows([100.0 + i for i in range(25)])
        rows.insert(10, ("2026-01-01x", None, None, None, None, 0, 1.0))
        self.assertEqual(compute_price_levels(rows)["bars"], 25)

    def test_deterministic(self):
        rnd = random.Random(3)
        closes = [50 + rnd.random() * 20 for _ in range(300)]
        rows = _rows(closes, vols=[rnd.randrange(1, 9999) for _ in range(300)], spread=0.7)
        a = json.dumps(compute_price_levels(rows), sort_keys=True)
        b = json.dumps(compute_price_levels(list(rows)), sort_keys=True)
        self.assertEqual(a, b)


class ExportKey(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        days = _dates(30)
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": day, "open": 100.0 + i, "high": 101.0 + i,
                 "low": 99.0 + i, "close": 100.0 + i, "volume": 1_000_000, "turnover": 1}
                for i, day in enumerate(days)
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2317", "date": day, "close": 50.0, "volume": 1_000_000, "turnover": 1}
                for day in days[-5:]
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def test_top_level_key_and_technical_untouched(self):
        out = Path(self._tmp.name) / "out"
        out.mkdir()
        export_json(out)
        p = read_merged_stock(out / "stocks", "2330")
        lv = p["price_levels"]
        self.assertEqual(lv["status"], "ok")
        self.assertEqual(lv["close"], 129.0)
        self.assertEqual(lv["highs"]["20"]["p"], 130.0)
        self.assertNotIn("price_levels", json.dumps(p.get("technical")))
        # docs/46:未評分的股票 raw_risks 是 [],鍵永遠存在;radar.json 不帶這個鍵
        self.assertEqual(p["raw_risks"], [])
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        self.assertNotIn("raw_risks", json.dumps(radar, ensure_ascii=False))
        self.assertNotIn("price_levels", json.dumps(radar, ensure_ascii=False))
        short = read_merged_stock(out / "stocks", "2317")
        self.assertEqual(short["price_levels"]["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
