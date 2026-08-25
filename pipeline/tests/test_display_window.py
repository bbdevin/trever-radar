"""display_window bounds (docs/34 A4)."""
import unittest
from datetime import date

from radar.compute.display_window import display_window_bounds, window_label


class DisplayWindowTests(unittest.TestCase):
    def test_mid_year_shows_ytd(self):
        f, t = display_window_bounds(date(2026, 8, 25))
        self.assertEqual(f, "2026-01-01")
        self.assertEqual(t, "2026-08-25")
        self.assertEqual(window_label(f, t, date(2026, 8, 25)), "當年度")

    def test_early_year_shows_six_months(self):
        f, t = display_window_bounds(date(2027, 1, 15))
        self.assertEqual(t, "2027-01-15")
        self.assertTrue(f.startswith("2026-"))
        self.assertEqual(window_label(f, t, date(2027, 1, 15)), "跨年度·近 6 月")


if __name__ == "__main__":
    unittest.main()
