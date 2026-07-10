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


class TestTechnicalBaseScore(unittest.TestCase):
    def test_s_strategies_do_not_add_to_score(self):
        # 觸發 S1 嚴謹版
        score, reasons, _ = score_technical(**tech_kwargs(
            is_limit_up_20d=True, has_volume_surge_5d=True, is_macd_golden_cross=True
        ))
        codes = {r["code"]: r["points"] for r in reasons}
        self.assertIn("S1_REBOUND", codes)
        self.assertEqual(score, 0)  # S1 的 20 分不應加到 tech_score


def s6_kwargs(**over):
    """S6 需要 60 根以上序列(_val(closes,30) 要有值)。
    平台前有一段拉升(80→100),近 15 日高檔盤整(100)。"""
    n = 40
    closes = [80.0] * 25 + [100.0] * 15
    highs = [81.0] * 25 + [101.0] * 15
    lows = [79.0] * 25 + [99.0] * 15
    base = tech_kwargs(
        idx=n - 1, close=101.0, open_=100.0, high=101.0, low=99.0,
        opens=[100.0] * n, closes=closes, highs=highs, lows=lows,
        volumes=[1000.0] * n, ma20=95.0, volume_ratio=1.5,
    )
    base.update(over)
    return base


def s9_kwargs(**over):
    """S9 需要每日收盤都在 5 日線上(單調上升序列),且突破 3 日高。"""
    n = 30
    closes = [80.0 + 2 * j for j in range(n)]
    highs = closes[:]
    lows = [c - 2 for c in closes]
    base = tech_kwargs(
        idx=n - 1, close=closes[-1], open_=closes[-1], high=closes[-1],
        low=closes[-1] - 2, opens=closes[:], closes=closes, highs=highs,
        lows=lows, volumes=[1000.0] * n, ma5=140.0, volume_ratio=1.5,
    )
    base.update(over)
    return base


class S2_to_S10_Tests(unittest.TestCase):
    def test_s2_breakout20_positive(self):
        score, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=100, high=121, low=99,
            volume_ratio=2.5, ma5=110, ma10=105, ma20=101,
            macd=1, macd_hist=1
        ))
        codes = {r["code"]: r["points"] for r in reasons}
        self.assertIn("S2_BREAKOUT20", codes)
        self.assertEqual(score, 50) # T1_MA20(10)+T1_BULL_MA(15)+T2_20D_HIGH(15)+T2_VOLUME_BREAKOUT(10)=50

    def test_s3_ma_converge_positive(self):
        score, reasons, _ = score_technical(**tech_kwargs(
            close=105, open_=100, high=105, low=100,
            volume_ratio=1.6, ma5=101, ma10=100, ma20=100,
            macd_hist=1, prev_macd_hist=0.1, rsi14=60
        ))
        codes = {r["code"]: r["points"] for r in reasons}
        self.assertIn("S3_MA_CONVERGE_BREAKOUT", codes)
        self.assertNotIn("S2_BREAKOUT20", codes)

    def test_s10_bottom_macd_positive(self):
        score, reasons, _ = score_technical(**tech_kwargs(
            close=50, box_high60=100, macd_hist=1, prev_macd_hist=-1,
            macd=-2, ma20=45, volume_ratio=1.5, rsi14=55
        ))
        codes = {r["code"]: r["points"] for r in reasons}
        self.assertIn("S10_BOTTOM_MACD", codes)

    def test_s10_negative(self):
        # 跌幅不夠 (close=90, box_high60=100) -> 應反例
        score, reasons, _ = score_technical(**tech_kwargs(
            close=90, box_high60=100, macd_hist=1, prev_macd_hist=-1,
            macd=-2, ma20=85, volume_ratio=1.5, rsi14=55
        ))
        codes = {r["code"]: r["points"] for r in reasons}
        self.assertNotIn("S10_BOTTOM_MACD", codes)


class S2_to_S10_BoundaryTests(unittest.TestCase):
    """每個策略:正例 + 翻轉單一(邊界)條件的反例。比較運算子以現行程式碼為準。"""

    @staticmethod
    def _codes(reasons):
        return {r["code"]: r["points"] for r in reasons}

    # --- S2:20 日新高爆量突破;量能條件為 vol_ratio > 2.0 ---
    def test_s2_boundary_vol_ratio_exactly_2(self):
        # vol_ratio 恰 2.0(條件 >2.0)→ 不觸發;T2_VOLUME_BREAKOUT(>=1.5)仍在
        _, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=100, high=121, low=99,
            volume_ratio=2.0, ma5=110, ma10=105, ma20=101, macd=1, macd_hist=1))
        codes = self._codes(reasons)
        self.assertNotIn("S2_BREAKOUT20", codes)
        self.assertIn("T2_VOLUME_BREAKOUT", codes)

    # --- S3:均線糾結;收斂條件為 max/min < 1.03 ---
    def test_s3_boundary_convergence_exactly_3pct(self):
        # 均線最大/最小 = 1.03(條件 <1.03)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            close=105, open_=100, high=105, low=100,
            volume_ratio=1.6, ma5=103, ma10=100, ma20=100,
            macd_hist=1, prev_macd_hist=0.1, rsi14=60))
        self.assertNotIn("S3_MA_CONVERGE_BREAKOUT", self._codes(reasons))

    # --- S4:波動收斂後突破 ---
    def test_s4_volatility_contraction_positive(self):
        _, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=100, high=121, low=99,
            volume_ratio=2.5, adv20=2000, std20=1, ma20=100))
        self.assertIn("S4_VOLATILITY_CONTRACTION", self._codes(reasons))

    def test_s4_boundary_bollinger_width_exactly_0_15(self):
        # std20*4/ma20 = 0.15(條件 <0.15)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=100, high=121, low=99,
            volume_ratio=2.5, adv20=2000, std20=3.75, ma20=100))
        self.assertNotIn("S4_VOLATILITY_CONTRACTION", self._codes(reasons))

    # --- S5:強勢股量縮回踩;量縮條件為 vol_ratio < 1.0 ---
    def test_s5_pullback_positive(self):
        _, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=110, low=100, volume_ratio=0.8,
            ma5=105, ma10=104, ma20=103))
        self.assertIn("S5_PULLBACK_SUPPORT", self._codes(reasons))

    def test_s5_boundary_vol_ratio_exactly_1(self):
        # vol_ratio 恰 1.0(條件 <1.0)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            close=120, open_=110, low=100, volume_ratio=1.0,
            ma5=105, ma10=104, ma20=103))
        self.assertNotIn("S5_PULLBACK_SUPPORT", self._codes(reasons))

    # --- S6:高檔平台再突破;量能條件為 vol_ratio > 1.2 ---
    def test_s6_high_base_positive(self):
        _, reasons, _ = score_technical(**s6_kwargs())
        self.assertIn("S6_HIGH_BASE_BREAKOUT", self._codes(reasons))

    def test_s6_boundary_vol_ratio_exactly_1_2(self):
        # vol_ratio 恰 1.2(條件 >1.2)→ 不觸發
        _, reasons, _ = score_technical(**s6_kwargs(volume_ratio=1.2))
        self.assertNotIn("S6_HIGH_BASE_BREAKOUT", self._codes(reasons))

    # --- S7:MACD 零軸上金叉 ---
    def test_s7_macd_zero_cross_positive(self):
        _, reasons, _ = score_technical(**tech_kwargs(
            close=105, ma20=100, volume_ratio=2.0, rsi14=60,
            macd=1, macd_signal=0.5, macd_hist=0.5, prev_macd_hist=-0.1))
        self.assertIn("S7_MACD_ZERO_CROSS", self._codes(reasons))

    def test_s7_boundary_vol_ratio_exactly_1_5(self):
        # vol_ratio 恰 1.5(條件 >1.5)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            close=105, ma20=100, volume_ratio=1.5, rsi14=60,
            macd=1, macd_signal=0.5, macd_hist=0.5, prev_macd_hist=-0.1))
        self.assertNotIn("S7_MACD_ZERO_CROSS", self._codes(reasons))

    def test_s7_boundary_prev_hist_zero_not_truthy(self):
        # prev_macd_hist 恰 0:程式用 `prev_macd_hist and prev_macd_hist<=0`,
        # 0 為 falsy 故金叉不成立 → 不觸發(此邊界易被誤改為 <=0 比較)
        _, reasons, _ = score_technical(**tech_kwargs(
            close=105, ma20=100, volume_ratio=2.0, rsi14=60,
            macd=1, macd_signal=0.5, macd_hist=0.5, prev_macd_hist=0))
        self.assertNotIn("S7_MACD_ZERO_CROSS", self._codes(reasons))

    # --- S8:跳空突破不回補;跳空條件 prev_high*1.02 < open_ < prev_high*1.06
    #        (prev_high 取自 highs 陣列 = 101) ---
    def test_s8_gap_breakout_positive(self):
        _, reasons, _ = score_technical(**tech_kwargs(
            open_=105, low=102, close=110, high=111, volume_ratio=2.5))
        self.assertIn("S8_GAP_BREAKOUT", self._codes(reasons))

    def test_s8_boundary_gap_exactly_2pct(self):
        # open_ 恰 +2%(條件 open_ > prev_high*1.02)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            open_=101 * 1.02, low=102, close=110, high=111, volume_ratio=2.5))
        self.assertNotIn("S8_GAP_BREAKOUT", self._codes(reasons))

    def test_s8_boundary_gap_exactly_6pct(self):
        # open_ 恰 +6%(條件 open_ < prev_high*1.06)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            open_=101 * 1.06, low=102, close=110, high=111, volume_ratio=2.5))
        self.assertNotIn("S8_GAP_BREAKOUT", self._codes(reasons))

    # --- S9:五日線強勢續攻;量能條件為 vol_ratio > 1.0 ---
    def test_s9_ma5_trend_positive(self):
        _, reasons, _ = score_technical(**s9_kwargs())
        self.assertIn("S9_MA5_TREND", self._codes(reasons))

    def test_s9_boundary_vol_ratio_exactly_1(self):
        # vol_ratio 恰 1.0(條件 >1.0)→ 不觸發
        _, reasons, _ = score_technical(**s9_kwargs(volume_ratio=1.0))
        self.assertNotIn("S9_MA5_TREND", self._codes(reasons))

    # --- S10:底部 MACD 轉強;跌深條件為 close < box_high60*0.8 ---
    def test_s10_boundary_close_exactly_80pct(self):
        # close 恰 box_high60*0.8(條件 <0.8)→ 不觸發
        _, reasons, _ = score_technical(**tech_kwargs(
            close=80, box_high60=100, macd_hist=1, prev_macd_hist=-1,
            macd=-2, ma20=45, volume_ratio=1.5, rsi14=55))
        self.assertNotIn("S10_BOTTOM_MACD", self._codes(reasons))


class StrategyDecouplingTests(unittest.TestCase):
    """證明 S code 只進 reasons、不進 tech_score:破壞策略特有條件、保留 T1-T5
    相關輸入,score 不變;且 score 恆等於 T-prefixed reasons 的 points 總和。
    抓「有人把 add_strategy 改回 add」的回歸。"""

    @staticmethod
    def _t_points_sum(reasons):
        return sum(r["points"] for r in reasons if r["code"].startswith("T"))

    def _assert_decoupled(self, s_code, trigger_kw, broken_kw):
        s_trig, r_trig, _ = score_technical(**trigger_kw)
        s_brk, r_brk, _ = score_technical(**broken_kw)
        codes_trig = {r["code"] for r in r_trig}
        codes_brk = {r["code"] for r in r_brk}
        # 策略觸發與否
        self.assertIn(s_code, codes_trig)
        self.assertNotIn(s_code, codes_brk)
        # score 與 T reasons 完全相等:S 分數沒有混進 tech_score
        self.assertEqual(s_trig, s_brk)
        self.assertEqual(s_trig, self._t_points_sum(r_trig))
        # 兩組的 T codes 相同(確認破壞的是策略條件,而非 T 條件)
        t_trig = {c for c in codes_trig if c.startswith("T")}
        t_brk = {c for c in codes_brk if c.startswith("T")}
        self.assertEqual(t_trig, t_brk)

    def test_s2_score_unchanged_when_strategy_broken(self):
        # 破壞:vol_ratio 2.5→2.0(仍 >=1.5 故 T2_VOLUME_BREAKOUT 不變),S2 消失
        base = dict(close=120, open_=100, high=121, low=99,
                    ma5=110, ma10=105, ma20=101, macd=1, macd_hist=1)
        self._assert_decoupled(
            "S2_BREAKOUT20",
            tech_kwargs(volume_ratio=2.5, **base),
            tech_kwargs(volume_ratio=2.0, **base))

    def test_s7_score_unchanged_when_strategy_broken(self):
        # 破壞:prev_macd_hist -0.1→0。T5_MACD_HIST_POS 用 macd_hist>0>=prev
        # 兩者皆成立(0.5>0>=0 與 0.5>0>=-0.1),故 T 不變;但 S7 的 truthy
        # 檢查使 0 失效,S7 消失。
        base = dict(close=105, ma20=100, volume_ratio=2.0, rsi14=60,
                    macd=1, macd_signal=0.5, macd_hist=0.5)
        self._assert_decoupled(
            "S7_MACD_ZERO_CROSS",
            tech_kwargs(prev_macd_hist=-0.1, **base),
            tech_kwargs(prev_macd_hist=0, **base))

    def test_s10_score_unchanged_when_strategy_broken(self):
        # 破壞:box_high60 100→55(T3 需 box_low60,此處為 None 故 T 不變),
        # close=50 不再 < 55*0.8=44,S10 消失。
        base = dict(close=50, macd_hist=1, prev_macd_hist=-1,
                    macd=-2, ma20=45, volume_ratio=1.5, rsi14=55)
        self._assert_decoupled(
            "S10_BOTTOM_MACD",
            tech_kwargs(box_high60=100, **base),
            tech_kwargs(box_high60=55, **base))


if __name__ == "__main__":
    unittest.main()
