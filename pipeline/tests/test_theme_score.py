import unittest
from radar.compute.scores import score_themes

class ThemeScoreTests(unittest.TestCase):
    def test_score_themes_basic(self):
        # We need theme_stocks, theme_prices, theme_dates, d
        theme_dates = ["2026-07-06", "2026-07-03"]
        d = "2026-07-06"
        
        theme_stocks = {
            "T1": ["2330", "2303", "2454"],  # 3 stocks
            "T2": ["3008", "2317"]           # 2 stocks (should be excluded as it has < 3 stocks)
        }
        
        # (close, turnover)
        theme_prices = {
            "2330": {
                "2026-07-06": (1050.0, 100_000_000),
                "2026-07-03": (1000.0, 50_000_000)
            },
            "2303": {
                "2026-07-06": (52.0, 40_000_000),
                "2026-07-03": (50.0, 20_000_000)
            },
            "2454": {
                "2026-07-06": (1250.0, 60_000_000),
                "2026-07-03": (1200.0, 30_000_000)
            },
            "3008": {
                "2026-07-06": (3000.0, 10_000_000),
                "2026-07-03": (2900.0, 5_000_000)
            },
            "2317": {
                "2026-07-06": (200.0, 80_000_000),
                "2026-07-03": (190.0, 40_000_000)
            }
        }
        
        scores = score_themes(theme_stocks, theme_prices, theme_dates, d)
        
        # T2 should be excluded because it has < 3 stocks
        self.assertNotIn("T2", scores)
        self.assertIn("T1", scores)
        
        # Since T1 is the only theme, the mean_chg/std_chg and mean_tr/std_tr calculations
        # will have std_chg = 0, std_tr = 0.
        # This will set z_chg = 0, z_tr = 0.
        # The raw score = 0.4 * 0 + 0.3 * up_ratio + 0.3 * 0.
        # up_ratio: all 3 stocks rose (1050>1000, 52>50, 1250>1200), so up_ratio = 1.0.
        # raw = 0.3.
        # score = (0.3 + 2.0) / 4.0 * 100 = 2.3 / 4.0 * 100 = 57.5, rounded to 58.
        self.assertIn(scores["T1"], (57, 58))

    def test_score_themes_multiple_themes(self):
        theme_dates = ["2026-07-06", "2026-07-03"]
        d = "2026-07-06"
        
        theme_stocks = {
            "T1": ["2330", "2303", "2454"],  # Up today, Turnover increased
            "T2": ["3008", "2317", "2382"]   # Down today, Turnover decreased
        }
        
        theme_prices = {
            # T1: positive returns
            "2330": {
                "2026-07-06": (1050.0, 200_000_000),  # +5%
                "2026-07-03": (1000.0, 100_000_000)
            },
            "2303": {
                "2026-07-06": (52.5, 80_000_000),     # +5%
                "2026-07-03": (50.0, 40_000_000)
            },
            "2454": {
                "2026-07-06": (1260.0, 120_000_000),   # +5%
                "2026-07-03": (1200.0, 60_000_000)
            },
            # T2: negative returns
            "3008": {
                "2026-07-06": (2850.0, 10_000_000),    # -5%
                "2026-07-03": (3000.0, 20_000_000)
            },
            "2317": {
                "2026-07-06": (190.0, 40_000_000),     # -5%
                "2026-07-03": (200.0, 80_000_000)
            },
            "2382": {
                "2026-07-06": (237.5, 20_000_000),    # -5%
                "2026-07-03": (250.0, 40_000_000)
            }
        }
        
        scores = score_themes(theme_stocks, theme_prices, theme_dates, d)
        
        self.assertIn("T1", scores)
        self.assertIn("T2", scores)
        self.assertGreater(scores["T1"], scores["T2"])

if __name__ == "__main__":
    unittest.main()
