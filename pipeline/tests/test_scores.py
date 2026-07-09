import unittest

from radar.compute.scores import buy_concentration, score_branch, watch_stop_prices


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


if __name__ == "__main__":
    unittest.main()
