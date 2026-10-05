"""Lock the current behaviour of scores.risk_deductions() (docs/04 §8).

docs/04 §8 was aligned to the code on 2026-10-05 by reading it; these tests
make the six implemented codes, their boundaries and the −40 cap something
pytest asserts rather than something a reader has to trust. They describe
behaviour, they do not endorse it: any change here is a scoring change and
needs a full-market recompute plus diff report first.
"""
import unittest

from radar.compute.scores import risk_deductions


def run(**kw):
    """Call with a quiet baseline (no risk fires) and override what matters."""
    base = dict(
        chg5_pct=0.0, chg10_pct=0.0,
        open_=100.0, high=101.0, close=100.5, prev_close=100.0,
        volume_ratio=1.0, tech_risks=[], f_streak5_sell=False, margin_use=0.3,
    )
    base.update(kw)
    return risk_deductions(**base)


def codes(risks):
    return [r["code"] for r in risks]


class QuietBaselineTests(unittest.TestCase):
    def test_nothing_fires(self):
        penalty, risks = run()
        self.assertEqual(penalty, 0)
        self.assertEqual(risks, [])

    def test_all_none_inputs_are_tolerated(self):
        penalty, risks = risk_deductions(
            None, None, None, None, None, None, None, None, None, None)
        self.assertEqual((penalty, risks), (0, []))

    def test_risk_entry_shape(self):
        _, risks = run(chg5_pct=25.0)
        self.assertEqual(set(risks[0]), {"code", "points", "text", "value"})
        self.assertEqual(risks[0]["points"], -15)


class ShortTermOverheatTests(unittest.TestCase):
    """R_HOT5 / R_HOT10: strict >, if/elif so at most one −15."""

    def test_hot5_boundary(self):
        self.assertEqual(run(chg5_pct=20.0)[0], 0)
        penalty, risks = run(chg5_pct=20.01)
        self.assertEqual(penalty, -15)
        self.assertEqual(codes(risks), ["R_HOT5"])

    def test_hot10_boundary(self):
        self.assertEqual(run(chg10_pct=35.0)[0], 0)
        penalty, risks = run(chg10_pct=35.01)
        self.assertEqual(penalty, -15)
        self.assertEqual(codes(risks), ["R_HOT10"])

    def test_both_hot_deduct_once_and_prefer_hot5(self):
        penalty, risks = run(chg5_pct=30.0, chg10_pct=50.0)
        self.assertEqual(penalty, -15)
        self.assertEqual(codes(risks), ["R_HOT5"])

    def test_hot10_fires_when_chg5_is_none(self):
        penalty, risks = run(chg5_pct=None, chg10_pct=40.0)
        self.assertEqual(penalty, -15)
        self.assertEqual(codes(risks), ["R_HOT10"])


class ShootingStarTests(unittest.TestCase):
    """R_SHOOTING: volume_ratio >= 2.5, body > 0, upper shadow >= 2 × body."""

    def test_fires_at_exact_volume_ratio(self):
        # body 1, upper shadow 2 → exactly 2× body
        penalty, risks = run(open_=100.0, close=101.0, high=103.0, volume_ratio=2.5)
        self.assertEqual(penalty, -10)
        self.assertEqual(codes(risks), ["R_SHOOTING"])

    def test_below_volume_ratio_does_not_fire(self):
        self.assertEqual(run(open_=100.0, close=101.0, high=103.0, volume_ratio=2.49)[0], 0)

    def test_shadow_below_two_bodies_does_not_fire(self):
        self.assertEqual(run(open_=100.0, close=101.0, high=102.99, volume_ratio=3.0)[0], 0)

    def test_doji_is_exempt(self):
        # open == close → body 0 → no deduction even with a huge upper shadow (docs/04 §8 待確認)
        self.assertEqual(run(open_=100.0, close=100.0, high=110.0, volume_ratio=5.0)[0], 0)

    def test_black_candle_measures_shadow_from_open(self):
        # open 102, close 101 → body 1; high 104 → upper shadow 2 above max(open, close)
        penalty, risks = run(open_=102.0, close=101.0, high=104.0, prev_close=101.0, volume_ratio=3.0)
        self.assertIn("R_SHOOTING", codes(risks))

    def test_missing_volume_ratio_does_not_fire(self):
        self.assertEqual(run(open_=100.0, close=101.0, high=103.0, volume_ratio=None)[0], 0)


class GapFadeTests(unittest.TestCase):
    """R_GAP_FADE: open >= prev_close × 1.03 and close < open."""

    def test_fires_at_exact_three_percent(self):
        penalty, risks = run(prev_close=100.0, open_=103.0, close=102.0, high=103.5)
        self.assertEqual(penalty, -8)
        self.assertEqual(codes(risks), ["R_GAP_FADE"])

    def test_below_three_percent_does_not_fire(self):
        self.assertEqual(run(prev_close=100.0, open_=102.99, close=102.0, high=103.5)[0], 0)

    def test_close_equal_to_open_does_not_fire(self):
        self.assertEqual(run(prev_close=100.0, open_=103.0, close=103.0, high=103.5)[0], 0)

    def test_zero_prev_close_does_not_fire(self):
        self.assertEqual(run(prev_close=0.0, open_=103.0, close=102.0, high=103.5)[0], 0)


class RsiOverheatTests(unittest.TestCase):
    """R_RSI_OVERHEAT: −5 only when indicators already emitted that code."""

    def test_fires_on_code_from_technical_risks(self):
        penalty, risks = run(tech_risks=[{"code": "R_RSI_OVERHEAT", "value": 85}])
        self.assertEqual(penalty, -5)
        self.assertEqual(codes(risks), ["R_RSI_OVERHEAT"])

    def test_other_tech_codes_are_ignored(self):
        self.assertEqual(run(tech_risks=[{"code": "SOMETHING_ELSE"}])[0], 0)

    def test_none_tech_risks_is_tolerated(self):
        self.assertEqual(run(tech_risks=None)[0], 0)


class ForeignSellStreakTests(unittest.TestCase):
    def test_fires_on_flag(self):
        penalty, risks = run(f_streak5_sell=True)
        self.assertEqual(penalty, -8)
        self.assertEqual(codes(risks), ["R_FOREIGN_SELL5"])

    def test_false_and_none_do_not_fire(self):
        self.assertEqual(run(f_streak5_sell=False)[0], 0)
        self.assertEqual(run(f_streak5_sell=None)[0], 0)


class MarginHotTests(unittest.TestCase):
    """R_MARGIN_HOT: margin_use >= 0.6 (use-rate only; no growth condition)."""

    def test_fires_at_exact_boundary(self):
        penalty, risks = run(margin_use=0.6)
        self.assertEqual(penalty, -8)
        self.assertEqual(codes(risks), ["R_MARGIN_HOT"])

    def test_below_boundary_does_not_fire(self):
        self.assertEqual(run(margin_use=0.599)[0], 0)

    def test_none_does_not_fire(self):
        self.assertEqual(run(margin_use=None)[0], 0)


class CapTests(unittest.TestCase):
    def test_all_six_fire_and_cap_at_minus_40(self):
        penalty, risks = run(
            chg5_pct=30.0, chg10_pct=50.0,                       # −15 (once)
            prev_close=100.0, open_=103.0, close=104.0, high=106.0,
            volume_ratio=3.0,                                    # R_SHOOTING −10 (body 1, shadow 2)
            tech_risks=[{"code": "R_RSI_OVERHEAT"}],             # −5
            f_streak5_sell=True,                                 # −8
            margin_use=0.9,                                      # −8
        )
        # gap fade needs close < open; make it a separate assertion below
        self.assertEqual(codes(risks), [
            "R_HOT5", "R_SHOOTING", "R_RSI_OVERHEAT", "R_FOREIGN_SELL5", "R_MARGIN_HOT"])
        self.assertEqual(penalty, -40)        # raw −46, capped
        self.assertEqual(sum(r["points"] for r in risks), -46)

    def test_shooting_and_gap_fade_can_coexist(self):
        # open 103 (gap +3%), close 102 (black), high 105 → body 1, shadow 2
        penalty, risks = run(prev_close=100.0, open_=103.0, close=102.0, high=105.0, volume_ratio=3.0)
        self.assertEqual(codes(risks), ["R_SHOOTING", "R_GAP_FADE"])
        self.assertEqual(penalty, -18)

    def test_cap_is_exactly_minus_40_not_lower(self):
        penalty, _ = run(chg5_pct=30.0, prev_close=100.0, open_=103.0, close=102.0,
                         high=105.0, volume_ratio=3.0,
                         tech_risks=[{"code": "R_RSI_OVERHEAT"}],
                         f_streak5_sell=True, margin_use=0.9)
        # all six: 15+10+8+5+8+8 = 54 → −40
        self.assertEqual(penalty, -40)


if __name__ == "__main__":
    unittest.main()
