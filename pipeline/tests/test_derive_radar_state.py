"""docs/22 state machine: Quiet→Armed→Triggered→Extended→Faded (same-day approx)."""
import unittest

from radar.export.json_export import derive_radar_state


class DeriveRadarStateTests(unittest.TestCase):
    def test_armed_quiet_with_sources(self):
        self.assertEqual(
            derive_radar_state(
                sources=["branch"],
                c_pct=1.0,
                c5_pct=3.0,
                technical=None,
                score_risks=[],
                close=100.0,
                stop_price=90.0,
                score_final=70,
            ),
            "armed",
        )

    def test_triggered_breakout(self):
        self.assertEqual(
            derive_radar_state(
                sources=["warrant"],
                c_pct=4.5,
                c5_pct=6.0,
                technical=None,
                score_risks=[],
                close=100.0,
                stop_price=90.0,
                score_final=70,
            ),
            "triggered",
        )

    def test_triggered_via_t2(self):
        self.assertEqual(
            derive_radar_state(
                sources=["branch"],
                c_pct=2.0,
                c5_pct=5.0,
                technical={"reasons": [{"code": "T2_20D_HIGH"}], "risks": []},
                score_risks=[],
                close=100.0,
                stop_price=90.0,
                score_final=70,
            ),
            "triggered",
        )

    def test_extended_chase_risk(self):
        self.assertEqual(
            derive_radar_state(
                sources=["branch", "warrant"],
                c_pct=7.5,
                c5_pct=15.0,
                technical={"reasons": [], "risks": [{"code": "R_RSI_OVERHEAT"}]},
                score_risks=[{"code": "R_RSI_OVERHEAT", "text": "過熱"}],
                close=120.0,
                stop_price=100.0,
                score_final=80,
            ),
            "extended",
        )

    def test_faded_overrides_when_stop_touched(self):
        self.assertEqual(
            derive_radar_state(
                sources=["branch"],
                c_pct=1.0,
                c5_pct=2.0,
                technical=None,
                score_risks=[],
                close=89.0,
                stop_price=90.0,
                score_final=70,
            ),
            "faded",
        )

    def test_faded_without_sources_at_stop(self):
        self.assertEqual(
            derive_radar_state(
                sources=[],
                c_pct=-2.0,
                c5_pct=-5.0,
                technical=None,
                score_risks=[],
                close=88.0,
                stop_price=90.0,
                score_final=60,
            ),
            "faded",
        )

    def test_quiet_no_state(self):
        self.assertIsNone(
            derive_radar_state(
                sources=[],
                c_pct=0.5,
                c5_pct=1.0,
                technical=None,
                score_risks=[],
                close=100.0,
                stop_price=90.0,
                score_final=None,
            )
        )


if __name__ == "__main__":
    unittest.main()
