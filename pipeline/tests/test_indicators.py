import json
import unittest

from radar.compute.indicators import compute_series, score_technical


def row(i, close, volume=1000):
    return {
        "stock_id": "T",
        "date": f"2026-01-{i:02d}",
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "adj_factor": 1.0,
        "volume": volume,
    }


def tech_kwargs(**overrides):
    """score_technical 的最小合法 kwargs:平盤序列,除被覆寫者外不觸發任何規則。"""
    n = 30
    base = dict(
        idx=n - 1, open_=100.0, high=101.0, low=99.0, close=100.0,
        opens=[100.0] * n, closes=[100.0] * n, highs=[101.0] * n,
        lows=[99.0] * n, volumes=[1000.0] * n,
        ma5=None, ma10=None, ma20=None, ma60=None, std20=None,
        high20=None, box_high60=None, box_low60=None,
        adv20=None, volume_ratio=None, rsi14=None,
        macd=None, macd_signal=None, macd_hist=None, prev_macd_hist=None,
        k9=None, d9=None, prev_k=None, prev_d=None,
        is_limit_up_20d=False, has_volume_surge_5d=False,
        is_macd_golden_cross=False,
        is_surge_7pct_20d=False, has_volume_surge_1_5x_5d=False,
        is_macd_golden_cross_any=False,
    )
    base.update(overrides)
    return base


class IndicatorTests(unittest.TestCase):
    def test_ma_and_breakout_score_reasons(self):
        rows = [row(i + 1, 100 + i, 1000 + i * 10) for i in range(65)]
        rows[-1]["close"] = 180
        rows[-1]["high"] = 181
        rows[-1]["low"] = 179
        rows[-1]["volume"] = 5000

        out = compute_series(rows)
        last = out[-1]
        reasons = {r["code"] for r in json.loads(last["reasons"])}

        self.assertGreater(last["ma20"], last["ma60"])
        self.assertIn("T1_MA20", reasons)
        self.assertIn("T1_MA60", reasons)
        self.assertIn("T2_20D_HIGH", reasons)
        self.assertIn("T2_VOLUME_BREAKOUT", reasons)
        self.assertGreaterEqual(last["tech_score"], 40)

    def test_rsi_overheat_is_risk_not_score(self):
        rows = [row(i + 1, 100 + i, 1000) for i in range(40)]

        last = compute_series(rows)[-1]
        risks = {r["code"] for r in json.loads(last["risks"])}

        self.assertIn("R_RSI_OVERHEAT", risks)


class S1DualTrackTests(unittest.TestCase):
    STRICT = dict(is_limit_up_20d=True, has_volume_surge_5d=True,
                  is_macd_golden_cross=True)
    RELAXED = dict(is_surge_7pct_20d=True, has_volume_surge_1_5x_5d=True,
                   is_macd_golden_cross_any=True)

    @staticmethod
    def _codes(reasons):
        return {r["code"]: r["points"] for r in reasons}

    def test_strict_flags_hit_s1_rebound_20(self):
        _, reasons, _ = score_technical(**tech_kwargs(**self.STRICT))
        codes = self._codes(reasons)
        self.assertEqual(codes.get("S1_REBOUND"), 20)
        self.assertNotIn("S1_REBOUND_RELAXED", codes)

    def test_relaxed_flags_hit_s1_relaxed_15(self):
        _, reasons, _ = score_technical(**tech_kwargs(**self.RELAXED))
        codes = self._codes(reasons)
        self.assertEqual(codes.get("S1_REBOUND_RELAXED"), 15)
        self.assertNotIn("S1_REBOUND", codes)

    def test_both_tracks_score_strict_only(self):
        _, reasons, _ = score_technical(**tech_kwargs(**self.STRICT, **self.RELAXED))
        codes = self._codes(reasons)
        self.assertEqual(codes.get("S1_REBOUND"), 20)
        self.assertNotIn("S1_REBOUND_RELAXED", codes)

    def test_no_flags_no_s1(self):
        _, reasons, _ = score_technical(**tech_kwargs())
        codes = self._codes(reasons)
        self.assertNotIn("S1_REBOUND", codes)
        self.assertNotIn("S1_REBOUND_RELAXED", codes)

    def test_compute_series_wires_relaxed_flags(self):
        """緩跌後 +7.2% 反彈日:hist 由負轉正但 MACD<0、量 1.6x、20 日內漲 >7%
        → 旗標接通應觸發 RELAXED;全序列不得出現嚴謹版。"""
        def srow(i, close, volume=1000.0):
            r = row(1, round(close, 2), volume)
            r["date"] = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
            r["open"] = r["close"]
            r["high"] = round(r["close"] * 1.01, 2)
            r["low"] = round(r["close"] * 0.99, 2)
            return r

        rows, c = [], 100.0
        for i in range(40):          # 每日 -0.6% 緩跌,MACD 壓到零軸下
            rows.append(srow(i, c))
            c *= 0.994
        c = rows[-1]["close"]
        for k in range(4):           # 反彈:首日 +7.2%(<9.5%),量 1.6x(<2x)
            c = round(c * (1.072 if k == 0 else 1.015), 2)
            rows.append(srow(40 + k, c, 1600.0))

        out = compute_series(rows)
        jump = out[40]               # +7.2% 當日即為金叉日
        self.assertLess(jump["macd"], 0)
        self.assertGreater(jump["macd_hist"], 0)
        codes = {r["code"] for r in json.loads(jump["reasons"])}
        self.assertIn("S1_REBOUND_RELAXED", codes)
        all_codes = {r["code"] for o in out for r in json.loads(o["reasons"])}
        self.assertNotIn("S1_REBOUND", all_codes)


if __name__ == "__main__":
    unittest.main()
