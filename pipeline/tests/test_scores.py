import unittest

from radar.compute.scores import score_branch


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


if __name__ == "__main__":
    unittest.main()
