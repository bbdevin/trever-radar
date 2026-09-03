import unittest
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory

from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar.cli import main
from radar.compute.branch_point_in_time_persist import (
    DEFINITIONS_VERSION,
    _price_rows_for_stock,
    compute_branch_pit_stats,
    plan_as_of_window,
    resolve_default_as_of,
)
from radar.compute.branch_point_in_time_report import _price_observation


def _market_days(start: date, count: int) -> list[str]:
    days: list[str] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


# Stock P is shaped so every event day in 19..27 has the same 20-day window
# extremes (100 low from the flat early days, 200 high from the day-18 spike),
# which makes each event percentile exactly (close - 100) / 100.
_P_CLOSE = {18: 200, 19: 130, 23: 180, 25: 180}


class BranchPointInTimePersistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_url, self.old_dir = config.DB_URL, config.DATA_DIR
        self.db_path = self.tmp_path / "persist.db"
        config.DB_URL = "sqlite:///" + self.db_path.as_posix()
        config.DATA_DIR = self.tmp_path
        db._engine = None
        db.init_db()
        self.days = _market_days(date(2026, 1, 2), 28)
        self.early_as_of = self.days[21]
        self.late_as_of = self.days[27]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "P", "name": "Pool", "market": "twse", "type": "stock"},
                {"id": "Q", "name": "Quiet", "market": "twse", "type": "stock"},
            ])
            prices = []
            for index, day in enumerate(self.days):
                prices.append({
                    "stock_id": "P", "date": day, "open": 100,
                    "close": _P_CLOSE.get(index, 100), "adj_factor": 1.0,
                })
                # Q's event-day close is missing, so its percentile must stay
                # unknown rather than being guessed at.
                prices.append({
                    "stock_id": "Q", "date": day, "open": 100,
                    "close": None if index == 20 else 100, "adj_factor": 1.0,
                })
            conn.execute(schema.daily_prices.insert(), prices)
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "POOL", "source": "manual", "added_at": self.days[0]},
                {"branch_name": "OTHER", "source": "manual", "added_at": self.days[0]},
            ])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "pool", "branch_name": "POOL"},
                {"id": 2, "branch_key": "other", "branch_name": "OTHER"},
                {"id": 3, "branch_key": "untracked", "branch_name": "UNTRACKED"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                # POOL: three non-adjacent buy episodes on P.  Only the day-19
                # one is inside the early as_of, and only it is a low buy.
                {"stock_id": "P", "date": self.days[19], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "P", "date": self.days[23], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                {"stock_id": "P", "date": self.days[25], "branch_id": 1, "net_lots": 10, "pct": 1.0, "source": "fixture"},
                # OTHER: two sell episodes on P and one buy on Q whose event-day
                # close is missing.  Sells are counted independently of buys.
                {"stock_id": "P", "date": self.days[19], "branch_id": 2, "net_lots": -5, "pct": -1.5, "source": "fixture"},
                {"stock_id": "P", "date": self.days[23], "branch_id": 2, "net_lots": -5, "pct": -1.5, "source": "fixture"},
                {"stock_id": "Q", "date": self.days[20], "branch_id": 2, "net_lots": 7, "pct": 1.0, "source": "fixture"},
                # pct is absent: an observed row, never an event.
                {"stock_id": "Q", "date": self.days[22], "branch_id": 2, "net_lots": 7, "pct": None, "source": "fixture"},
                # Not in the universe at all: must never get a row.
                {"stock_id": "P", "date": self.days[19], "branch_id": 3, "net_lots": 10, "pct": 1.0, "source": "fixture"},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self.old_url, self.old_dir
        self.tmp.cleanup()

    def _rows(self, **where):
        clause = "".join(f" AND {key} = :{key}" for key in where)
        with db.get_engine().connect() as conn:
            return [dict(row) for row in conn.execute(text(
                f"SELECT * FROM branch_pit_stats WHERE 1=1{clause} "
                "ORDER BY as_of, branch_name"
            ), where).mappings()]

    def test_one_row_per_branch_per_as_of_and_universe_is_respected(self):
        info = compute_branch_pit_stats(as_of=self.late_as_of)
        rows = self._rows(as_of=self.late_as_of)
        self.assertEqual([row["branch_name"] for row in rows], ["OTHER", "POOL"])
        self.assertEqual(info["branches_written"], 2)
        self.assertEqual({row["definitions_version"] for row in rows}, {DEFINITIONS_VERSION})
        self.assertTrue(all(row["computed_at"] for row in rows))
        by_name = {row["branch_name"]: row for row in rows}
        self.assertEqual(by_name["POOL"]["stock_count"], 1)
        self.assertEqual(by_name["POOL"]["observed_trade_rows"], 3)
        self.assertEqual(by_name["OTHER"]["stock_count"], 2)
        self.assertEqual(by_name["OTHER"]["observed_trade_rows"], 4)
        # Buy and sell are independent counts; nothing pairs them.
        self.assertEqual(by_name["OTHER"]["sell_episodes"], 2)
        self.assertEqual(by_name["OTHER"]["high_sell_count"], 1)
        self.assertEqual(by_name["OTHER"]["buy_episodes"], 1)
        self.assertEqual(by_name["OTHER"]["buy_pctile_unknown"], 1)

    def test_rerunning_the_same_as_of_replaces_instead_of_duplicating(self):
        compute_branch_pit_stats(as_of=self.late_as_of)
        first = self._rows(as_of=self.late_as_of)
        compute_branch_pit_stats(as_of=self.late_as_of)
        second = self._rows(as_of=self.late_as_of)
        self.assertEqual(len(first), len(second))
        with db.get_engine().connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM branch_pit_stats")).scalar()
        self.assertEqual(total, len(second))
        for before, after in zip(first, second):
            self.assertEqual(
                {k: v for k, v in before.items() if k != "computed_at"},
                {k: v for k, v in after.items() if k != "computed_at"},
            )

    def test_every_row_is_internally_self_describing(self):
        compute_branch_pit_stats(as_of=self.early_as_of)
        compute_branch_pit_stats(as_of=self.late_as_of)
        rows = self._rows()
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(branch=row["branch_name"], as_of=row["as_of"]):
                self.assertEqual(
                    row["buy_pctile_known"] + row["buy_pctile_unknown"], row["buy_episodes"],
                )
                self.assertEqual(
                    row["sell_pctile_known"] + row["sell_pctile_unknown"], row["sell_episodes"],
                )
                self.assertEqual(row["fwd5_matured"] + row["fwd5_unknown"], row["buy_episodes"])
                self.assertLessEqual(row["low_buy_count"], row["buy_pctile_known"])
                self.assertLessEqual(row["high_sell_count"], row["sell_pctile_known"])
                self.assertLessEqual(row["fwd5_positive_count"], row["fwd5_matured"])
                self.assertLessEqual(row["stock_count"], row["observed_trade_rows"])

    def test_truncated_window_records_the_real_first_market_day(self):
        info = compute_branch_pit_stats(as_of=self.early_as_of, window_days=60)
        self.assertTrue(info["window_truncated"])
        self.assertEqual(info["window_market_days"], 22)
        self.assertEqual(info["window_from"], self.days[0])
        row = self._rows(as_of=self.early_as_of)[0]
        self.assertEqual(row["window_from"], self.days[0])
        self.assertEqual(row["window_market_days"], 22)

    def test_non_trading_as_of_is_rejected(self):
        saturday = (date.fromisoformat(self.days[-1]) + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "market trading day"):
            compute_branch_pit_stats(as_of=saturday)
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            compute_branch_pit_stats(as_of="2026/01/02")
        with self.assertRaisesRegex(ValueError, "window-days"):
            compute_branch_pit_stats(as_of=self.late_as_of, window_days=0)

    def test_stored_counts_make_the_pooled_rate_recoverable(self):
        """The whole point of the table: a rate column could not be un-pooled.

        POOL has one known buy percentile at the early as_of and three at the
        late one, so the per-row rates are 100% and 33.3%.  Their mean is 66.7%
        but the pooled rate is 2/4 = 50%.  Only the stored numerator and
        denominator let a reader compute either one.
        """
        compute_branch_pit_stats(as_of=self.early_as_of)
        compute_branch_pit_stats(as_of=self.late_as_of)
        rows = self._rows(branch_name="POOL")
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [(row["low_buy_count"], row["buy_pctile_known"]) for row in rows],
            [(1, 1), (1, 3)],
        )
        per_row_rates = [100.0 * row["low_buy_count"] / row["buy_pctile_known"] for row in rows]
        pooled = (
            100.0 * sum(row["low_buy_count"] for row in rows)
            / sum(row["buy_pctile_known"] for row in rows)
        )
        self.assertAlmostEqual(pooled, 50.0)
        self.assertNotAlmostEqual(mean(per_row_rates), pooled, places=3)

    def _percentile_at(self, index: int) -> float | None:
        market_index = {day: position for position, day in enumerate(self.days)}
        with db.get_engine().connect() as conn:
            row_by_date = _price_rows_for_stock(
                conn, stock_id="P", date_from=self.days[0], date_to=self.days[-1],
            )
        return _price_observation(
            event_date=self.days[index],
            market_index=market_index,
            market_days=self.days,
            row_by_date=row_by_date,
        )["price_percentile_20d"]

    def _set_adj_factor(self, factor: float, through_index: int) -> None:
        with db.get_engine().begin() as conn:
            conn.execute(text(
                "UPDATE daily_prices SET adj_factor = :factor "
                "WHERE stock_id = 'P' AND date <= :through"
            ), {"factor": factor, "through": self.days[through_index]})

    def test_percentile_is_invariant_under_a_factor_shared_by_the_whole_window(self):
        # The fixture's adj_factor is 1.0 throughout, so this is the raw number.
        self.assertAlmostEqual(self._percentile_at(19), 0.3)
        # adj_factor is cumulative-backward: a corporate action occurring after
        # the window scales every close in the window by the same constant, and a
        # constant cancels in a min/max percentile.  The event day here is 19 and
        # the rescaled block runs through day 21, so the whole window shares 0.8.
        self._set_adj_factor(0.8, 21)
        self.assertAlmostEqual(self._percentile_at(19), 0.3)

    def test_a_factor_change_inside_the_window_does_move_the_percentile(self):
        self.assertAlmostEqual(self._percentile_at(19), 0.3)
        # Now the action lands on day 19 itself, so only the earlier closes are
        # rescaled.  The number moves, which is the point: on raw prices that
        # split reads as a crash inside the range.
        self._set_adj_factor(0.5, 18)
        self.assertAlmostEqual(self._percentile_at(19), 1.0)

    def test_table_is_created_on_an_existing_database_without_alter(self):
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DROP TABLE branch_pit_stats")
        db.init_db()
        with db.get_engine().connect() as conn:
            found = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='branch_pit_stats'"
            )).scalar()
        self.assertEqual(found, "branch_pit_stats")

    def test_plan_rejects_a_date_with_no_price_data(self):
        with self.assertRaisesRegex(ValueError, "market trading day"):
            plan_as_of_window(trading_days=self.days, as_of="2020-01-02", window_days=60)

    def test_cli_persists_and_is_repeatable(self):
        main(["branch-point-in-time-persist", "--as-of", self.late_as_of, "--window-days", "10"])
        main(["branch-point-in-time-persist", "--as-of", self.late_as_of, "--window-days", "10"])
        rows = self._rows(as_of=self.late_as_of, window_market_days=10)
        self.assertEqual([row["branch_name"] for row in rows], ["OTHER", "POOL"])
        self.assertEqual(rows[0]["window_from"], self.days[18])

    def test_default_as_of_is_the_latest_trading_day_with_price_data(self):
        # branch_trades stops at day 25, but the ledger's as_of must be a day
        # daily_prices knows about, so the default follows daily_prices.
        self.assertEqual(resolve_default_as_of(), self.days[27])

    def test_cli_without_as_of_uses_the_latest_trading_day(self):
        main(["branch-point-in-time-persist", "--window-days", "10"])
        rows = self._rows()
        self.assertEqual({row["as_of"] for row in rows}, {self.late_as_of})
        self.assertEqual([row["branch_name"] for row in rows], ["OTHER", "POOL"])

    def test_explicit_as_of_is_unaffected_by_the_default(self):
        main(["branch-point-in-time-persist", "--as-of", self.early_as_of, "--window-days", "10"])
        self.assertEqual({row["as_of"] for row in self._rows()}, {self.early_as_of})

    def test_default_as_of_fails_closed_when_there_is_no_trading_day(self):
        with db.get_engine().begin() as conn:
            conn.exec_driver_sql("DELETE FROM daily_prices")
        with self.assertRaisesRegex(ValueError, "no market trading day"):
            resolve_default_as_of()
        with self.assertRaises(ValueError):
            main(["branch-point-in-time-persist"])
        with db.get_engine().connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT COUNT(*) FROM branch_pit_stats")).scalar(), 0
            )


if __name__ == "__main__":
    unittest.main()
