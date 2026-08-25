"""融資成本估算單元測試(docs/34 §5.2)."""
import unittest

from radar.compute.margin_cost import build_margin_cost_series, next_margin_cost


class MarginCostTests(unittest.TestCase):
    def test_zero_balance_resets(self):
        self.assertIsNone(next_margin_cost(100.0, 10, 0, 50.0))

    def test_first_buy_uses_close(self):
        self.assertEqual(next_margin_cost(None, 100, 100, 580.0), 580.0)

    def test_no_prev_no_buy(self):
        self.assertIsNone(next_margin_cost(None, 0, 50, 100.0))

    def test_weighted_average_on_buy(self):
        # prev cost 100, 50 lots remain, buy 50 @ 200, balance 100 → (100*50 + 200*50)/100 = 150
        self.assertEqual(next_margin_cost(100.0, 50, 100, 200.0), 150.0)

    def test_series_accumulates(self):
        rows = [(100, 100, 100.0), (0, 100, 110.0), (50, 150, 120.0)]
        costs = build_margin_cost_series(rows)
        self.assertEqual(costs[0], 100.0)
        self.assertEqual(costs[1], 100.0)
        self.assertAlmostEqual(costs[2], (100.0 * 100 + 120.0 * 50) / 150)


if __name__ == "__main__":
    unittest.main()
