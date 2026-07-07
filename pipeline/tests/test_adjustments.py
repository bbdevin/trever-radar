import unittest

from radar.adjustments import factors_for_dates


class AdjustmentFactorTests(unittest.TestCase):
    def test_event_applies_only_before_ex_date(self):
        dates = ["2026-06-11", "2026-06-12", "2026-06-13"]
        events = [{"date": "2026-06-12", "before_price": 100.0, "after_price": 95.0}]

        factors = factors_for_dates(dates, events)

        self.assertEqual(factors["2026-06-13"], 1.0)
        self.assertEqual(factors["2026-06-12"], 1.0)
        self.assertEqual(factors["2026-06-11"], 0.95)

    def test_multiple_events_compound_backward(self):
        dates = ["2026-01-01", "2026-02-01", "2026-03-01"]
        events = [
            {"date": "2026-02-01", "before_price": 100.0, "after_price": 90.0},
            {"date": "2026-03-01", "before_price": 50.0, "after_price": 45.0},
        ]

        factors = factors_for_dates(dates, events)

        self.assertEqual(factors["2026-03-01"], 1.0)
        self.assertEqual(factors["2026-02-01"], 0.9)
        self.assertEqual(factors["2026-01-01"], 0.81)


if __name__ == "__main__":
    unittest.main()
