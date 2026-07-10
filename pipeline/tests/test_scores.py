import unittest

from radar.compute.scores import (
    buy_concentration,
    s11_insti_breakout,
    s12_branch_accumulation,
    s13_short_squeeze,
    score_branch,
    watch_stop_prices,
)


def branch(key, name, net):
    return {
        "branch_key": key,
        "branch_name": name,
        "buy_lots": max(net, 0),
        "sell_lots": abs(min(net, 0)),
        "net_lots": net,
        "pct": None,
    }


class BranchScoreTests(unittest.TestCase):
    def test_branch_streak_and_multi_branch_score(self):
        dates = ["2026-01-05", "2026-01-02", "2026-01-01"]
        volumes = {d: 4_000_000 for d in dates}
        rows = {
            "2026-01-05": [
                branch("A", "凱基-台北", 200),
                branch("B", "元大-新店", 120),
                branch("C", "富邦-內湖", 110),
            ],
            "2026-01-02": [branch("A", "凱基-台北", 150)],
            "2026-01-01": [branch("A", "凱基-台北", 100)],
        }

        score, reasons, risks = score_branch(rows, dates, volumes)
        codes = {r["code"] for r in reasons}

        self.assertGreaterEqual(score, 35)
        self.assertIn("B1_BRANCH_STREAK", codes)
        self.assertIn("B2_MULTI_BRANCH", codes)
        self.assertEqual(risks, [])

    def test_reversal_reduces_branch_score_and_adds_risk(self):
        dates = ["2026-01-05", "2026-01-02"]
        volumes = {d: 10_000_000 for d in dates}
        rows = {
            "2026-01-05": [branch("A", "凱基-台北", -90)],
            "2026-01-02": [branch("A", "凱基-台北", 100)],
        }

        score, _reasons, risks = score_branch(rows, dates, volumes)

        self.assertEqual(score, 0)
        self.assertEqual(risks[0]["code"], "B_RISK_REVERSAL")

    def test_concentration_jump_triggers_b3(self):
        dates = ["2026-01-05", "2026-01-02", "2026-01-01"]
        volumes = {d: 4_000_000 for d in dates}
        rows = {
            "2026-01-05": [
                branch("A", "凱基-台北", 250),
                branch("B", "元大-新店", 220),
                branch("C", "富邦-內湖", 180),
                branch("D", "國泰-信義", 150),
                branch("E", "永豐-中壢", 100),
            ],
            "2026-01-02": [branch("A", "凱基-台北", 40)],
            "2026-01-01": [branch("A", "凱基-台北", 40)],
        }

        score, reasons, _risks = score_branch(rows, dates, volumes)
        codes = {r["code"] for r in reasons}
        self.assertIn("B3_BUY_CONCENTRATION", codes)


class BuyConcentrationTests(unittest.TestCase):
    def test_returns_today_ratio_and_prior_average(self):
        dates = ["2026-01-05", "2026-01-02", "2026-01-01"]
        volumes = {d: 4_000_000 for d in dates}
        rows = {
            "2026-01-05": [branch("A", "凱基-台北", 400)],
            "2026-01-02": [branch("A", "凱基-台北", 40)],
            "2026-01-01": [branch("A", "凱基-台北", 40)],
        }

        buy_conc, avg_conc = buy_concentration(rows, dates, volumes)

        self.assertAlmostEqual(buy_conc, 400 / 4_000)
        self.assertAlmostEqual(avg_conc, 40 / 4_000)

    def test_no_volume_returns_none(self):
        dates = ["2026-01-05"]
        self.assertEqual(buy_concentration({}, dates, {}), (None, None))


class WatchStopPriceTests(unittest.TestCase):
    def test_uses_box_high_when_above_todays_high(self):
        watch, stop = watch_stop_prices(high=100, low=95, ma5=90, box_high60=110)
        self.assertEqual(watch, round(110 * 1.005, 2))
        self.assertEqual(stop, 90)

    def test_uses_todays_high_when_box_missing(self):
        watch, stop = watch_stop_prices(high=100, low=95, ma5=None, box_high60=None)
        self.assertEqual(watch, round(100 * 1.005, 2))
        self.assertEqual(stop, 95)

    def test_none_high_returns_none_none(self):
        self.assertEqual(watch_stop_prices(None, 95, 90, 110), (None, None))


class S11InstiBreakoutTests(unittest.TestCase):
    """S11: (法人連買) 且 t_score>=60 且 chg>4。"""

    def test_positive(self):
        self.assertTrue(s11_insti_breakout(True, False, 70, 5))
        self.assertTrue(s11_insti_breakout(False, True, 70, 5))

    def test_boundary_t_score_exactly_60(self):
        # t_score>=60:60 觸發(正邊界),59 不觸發
        self.assertTrue(s11_insti_breakout(True, False, 60, 5))
        self.assertFalse(s11_insti_breakout(True, False, 59, 5))

    def test_boundary_chg_exactly_4(self):
        # chg>4:4 不觸發
        self.assertFalse(s11_insti_breakout(True, False, 70, 4))

    def test_negative_no_streak(self):
        self.assertFalse(s11_insti_breakout(False, False, 80, 5))

    def test_none_semantics(self):
        # t_score / chg 為 None 時應為 False(短路)
        self.assertFalse(s11_insti_breakout(True, False, None, 5))
        self.assertFalse(s11_insti_breakout(True, False, 70, None))


class S12BranchAccumulationTests(unittest.TestCase):
    """S12: buy_conc>=0.15 且(conc_avg20 為 None 或 buy_conc>=avg*1.5)且 chg5<5 且 chg<3。"""

    def test_positive_avg_none(self):
        self.assertTrue(s12_branch_accumulation(0.15, None, 0, 0))

    def test_boundary_buy_conc_exactly_0_15(self):
        # buy_conc>=0.15:0.15 觸發(正邊界),0.149 不觸發
        self.assertTrue(s12_branch_accumulation(0.15, None, 0, 0))
        self.assertFalse(s12_branch_accumulation(0.149, None, 0, 0))

    def test_boundary_conc_avg20_multiple_exactly_equal(self):
        # buy_conc >= avg*1.5:恰等觸發,avg 略高使門檻超過 buy_conc 則不觸發。
        # 用二進位可精確表示的值避免浮點誤差(0.25*1.5 == 0.375)。
        self.assertTrue(s12_branch_accumulation(0.375, 0.25, 0, 0))   # 0.25*1.5=0.375
        self.assertFalse(s12_branch_accumulation(0.375, 0.26, 0, 0))  # 0.26*1.5=0.39>0.375

    def test_boundary_chg_and_chg5(self):
        # chg<3:3 不觸發;chg5<5:5 不觸發
        self.assertFalse(s12_branch_accumulation(0.15, None, 0, 3))
        self.assertFalse(s12_branch_accumulation(0.15, None, 5, 0))

    def test_none_semantics(self):
        # buy_conc 為 None → False;chg / chg5 為 None → False(明確 is not None 判定)
        self.assertFalse(s12_branch_accumulation(None, None, 0, 0))
        self.assertFalse(s12_branch_accumulation(0.15, None, None, 0))
        self.assertFalse(s12_branch_accumulation(0.15, None, 0, None))


class S13ShortSqueezeTests(unittest.TestCase):
    """S13: short_bal<short_prev 且 short_prev>1000 且 chg>4 且 t_vr>1.5。"""

    def test_positive(self):
        self.assertTrue(s13_short_squeeze(500, 2000, 5, 2.0))

    def test_boundary_short_prev_exactly_1000(self):
        # short_prev>1000:1000 不觸發
        self.assertFalse(s13_short_squeeze(500, 1000, 5, 2.0))

    def test_boundary_chg_exactly_4(self):
        # chg>4:4 不觸發
        self.assertFalse(s13_short_squeeze(500, 2000, 4, 2.0))

    def test_boundary_t_vr_exactly_1_5(self):
        # t_vr>1.5:1.5 不觸發
        self.assertFalse(s13_short_squeeze(500, 2000, 5, 1.5))

    def test_negative_bal_not_below_prev(self):
        self.assertFalse(s13_short_squeeze(2000, 2000, 5, 2.0))

    def test_none_semantics(self):
        # short_bal / short_prev / chg / t_vr 為 None 皆 False
        self.assertFalse(s13_short_squeeze(None, 2000, 5, 2.0))
        self.assertFalse(s13_short_squeeze(500, None, 5, 2.0))
        self.assertFalse(s13_short_squeeze(500, 2000, None, 2.0))
        self.assertFalse(s13_short_squeeze(500, 2000, 5, None))


if __name__ == "__main__":
    unittest.main()
