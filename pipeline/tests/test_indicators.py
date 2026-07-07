import json
import unittest

from radar.compute.indicators import compute_series


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


if __name__ == "__main__":
    unittest.main()
