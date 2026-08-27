"""Contracts for the homepage composite-score list (docs/04 §10)."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.export.json_export import export_json


class ScoreListContractTests(unittest.TestCase):
    """The composite list is a threshold, not a fixed-length market scan."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": sid, "name": sid, "market": "twse", "type": "stock", "is_active": 1}
                for sid in (
                    "high", "branch_high", "turnover_high", "turnover_low",
                    "branch_low", "branch_missing", "threshold", "below",
                )
            ])
            turnover = {
                "high": 100_000_000,
                "branch_high": 150_000_000,
                "turnover_high": 300_000_000,
                "turnover_low": 200_000_000,
                "branch_low": 900_000_000,
                "branch_missing": 1_000_000_000,
                "threshold": 100_000_000,
                "below": 100_000_000,
            }
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 100, "volume": 1000, "turnover": turnover[sid]}
                for sid in turnover
                for day in ("2026-08-03", "2026-08-04")
            ])
            conn.execute(schema.daily_scores.insert(), [
                {"stock_id": "high", "date": "2026-08-04", "final": 80, "branch_score": 1, "reasons": "[]", "risks": "[]"},
                {"stock_id": "branch_high", "date": "2026-08-04", "final": 70, "branch_score": 60, "reasons": "[]", "risks": "[]"},
                {"stock_id": "turnover_high", "date": "2026-08-04", "final": 70, "branch_score": 25, "reasons": "[]", "risks": "[]"},
                {"stock_id": "turnover_low", "date": "2026-08-04", "final": 70, "branch_score": 25, "reasons": "[]", "risks": "[]"},
                {"stock_id": "branch_low", "date": "2026-08-04", "final": 70, "branch_score": 10, "reasons": "[]", "risks": "[]"},
                {"stock_id": "branch_missing", "date": "2026-08-04", "final": 70, "branch_score": None, "reasons": "[]", "risks": "[]"},
                {"stock_id": "threshold", "date": "2026-08-04", "final": 65, "branch_score": 99, "reasons": "[]", "risks": "[]"},
                {"stock_id": "below", "date": "2026-08-04", "final": 64.99, "branch_score": 100, "reasons": "[]", "risks": "[]"},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def test_score_list_is_strict_final_threshold_without_minimum_fill(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(radar["lists"]["score"], [
            "high", "branch_high", "turnover_high", "turnover_low",
            "branch_low", "branch_missing", "threshold",
        ])
        self.assertLess(len(radar["lists"]["score"]), 15)
