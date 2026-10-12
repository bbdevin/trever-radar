"""wpos-avgcost-v1(docs/51):手算 fixture 釘住權證分點持有估算。"""
import unittest

from radar.compute.warrant_position_est import (
    DEFINITIONS_VERSION,
    Leg,
    WarrantInfo,
    screening_rows,
    warrant_positions,
)

AS_OF = "2026-10-08"
D1, D2, D3, D4, D5 = "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-07"
B, U, W = "凱基-台北", "2330", "030001"


def info(kind="call", last_price=2.5, maturity="2027-03-31"):
    return WarrantInfo(kind=kind, maturity_date=maturity, last_price=last_price, last_price_date=AS_OF)


class LegTests(unittest.TestCase):
    def test_two_buys_cost_and_underlying_equivalent_average(self):
        leg = Leg()
        leg.trade(D1, 100, 2.0, 500.0)    # 20 萬,現股 500
        leg.trade(D2, 100, 4.0, 600.0)    # 40 萬,現股 600
        self.assertEqual(leg.pos, 200)
        self.assertEqual(leg.cost, 600_000)
        # 以金額加權:(20萬×500 + 40萬×600) / 60萬 = 566.67,不是張數加權的 550。
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 566.6667, places=3)
        self.assertEqual(leg.last_buy_date, D2)

    def test_partial_sell_average_cost_then_unattributed_remainder(self):
        leg = Leg()
        leg.trade(D1, 100, 2.0, 500.0)
        leg.trade(D2, 100, 4.0, 600.0)
        leg.trade(D3, -50, 3.0, 700.0)    # 賣 50 張:均價 3.0,正好損益 0
        self.assertEqual(leg.pos, 150)
        self.assertAlmostEqual(leg.cost, 450_000)
        self.assertAlmostEqual(leg.realized, 0.0)
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 566.6667, places=3)  # 均價法:換算均價不變
        leg.trade(D4, -200, 3.5, 700.0)   # 只剩 150 張可賣;50 張找不到對應買超
        self.assertEqual(leg.pos, 0)
        self.assertEqual(leg.cost, 0)
        self.assertAlmostEqual(leg.realized, 150 * 3.5 * 1000 - 450_000)  # +75,000
        self.assertEqual(leg.sell_attr, 200)
        self.assertEqual(leg.sell_unattr, 50)

    def test_buy_days_shrink_proportionally_after_partial_sell(self):
        """進場日拆解:平均成本法沒有先進先出,賣超把每個買超日的剩餘等比例縮小。"""
        leg = Leg()
        leg.trade(D1, 100, 2.0, 500.0)
        leg.trade(D1, 20, 2.0, 500.0)     # 同日第二列併入同一天
        leg.trade(D2, 80, 4.0, 600.0)
        self.assertEqual([(b[0], b[1], b[2], b[3]) for b in leg.buys],
                         [(D1, 120, 240_000, 500.0), (D2, 80, 320_000, 600.0)])
        leg.trade(D3, -50, 3.0, 700.0)    # 賣 50/200 = 25% → 每天都剩 75%
        self.assertEqual([(b[0], b[1], round(b[2])) for b in leg.buys], [(D1, 90, 180_000), (D2, 60, 240_000)])
        self.assertAlmostEqual(sum(b[1] for b in leg.buys), leg.pos)
        self.assertAlmostEqual(sum(b[2] for b in leg.buys), leg.cost)
        leg.trade(D4, -150, 3.0, 700.0)   # 全部出清 → 進場日清空
        self.assertEqual(leg.buys, [])
        leg.trade(D5, 10, 1.0, 650.0)     # 重新建立
        self.assertEqual(leg.buys, [[D5, 10, 10_000, 650.0]])

    def test_sell_before_any_buy_is_unattributed_not_short(self):
        leg = Leg()
        leg.trade(D1, -30, 2.0, 500.0)
        self.assertEqual((leg.pos, leg.cost, leg.realized), (0, 0, 0))
        self.assertEqual(leg.sell_unattr, 30)

    def test_missing_warrant_close_marks_cost_unknown(self):
        leg = Leg()
        leg.trade(D1, 100, None, 500.0)
        self.assertTrue(leg.price_missing)
        self.assertEqual(leg.pos, 0)

    def test_missing_underlying_close_only_skips_the_equivalent_average(self):
        leg = Leg()
        leg.trade(D1, 100, 2.0, None)
        leg.trade(D2, 100, 4.0, 600.0)
        self.assertEqual(leg.cost, 600_000)
        self.assertEqual(leg.under_cost, 400_000)
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 600.0)


class PositionsTests(unittest.TestCase):
    def test_call_and_put_are_separate_and_valued(self):
        trades = [
            (B, U, W, D1, 100, 2.0),
            (B, U, W, D2, 100, 4.0),
            (B, U, "030002", D2, 300, 1.0),   # 認售 30 萬
        ]
        wi = {W: info(), "030002": info(kind="put", last_price=1.2)}
        uc = {(U, D1): 500.0, (U, D2): 600.0}
        out = warrant_positions(trades, warrant_info=wi, under_close=uc, as_of=AS_OF)
        call = out[(B, U)]["call"]
        put = out[(B, U)]["put"]
        self.assertEqual(call["lots"], 200)
        self.assertEqual(call["cost"], 600_000)
        self.assertEqual(call["value"], 500_000)            # 200 × 2.5 × 1000
        self.assertEqual(call["unrealized"], -100_000)
        self.assertEqual(call["unrealized_pct"], -16.7)
        self.assertEqual(call["avg_under"], 566.67)
        self.assertEqual((call["n_warrants"], call["n_held"], call["n_expired"], call["n_no_price"]), (1, 1, 0, 0))
        self.assertEqual(call["last_buy_date"], D2)
        self.assertEqual(call["warrants"][0]["avg_cost"], 3.0)
        self.assertEqual(put["cost"], 300_000)
        self.assertEqual(put["unrealized"], 60_000)
        self.assertEqual(put["avg_under"], 600.0)
        self.assertEqual(call["buy_days"], [[D1, 100, 200_000, 500.0], [D2, 100, 400_000, 600.0]])
        self.assertEqual(put["buy_days"], [[D2, 300, 300_000, 600.0]])

    def test_buy_days_merge_across_warrants_and_follow_partial_sells(self):
        trades = [
            (B, U, "030001", D1, 100, 2.0),
            (B, U, "030002", D1, 100, 1.0),   # 同日另一檔認購 → 同一天合併
            (B, U, "030001", D2, 100, 4.0),
            (B, U, "030001", D3, -100, 3.0),  # 030001 賣掉一半 → D1/D2 的 030001 各剩 50
            (B, U, "030003", D4, 10, 1.0),    # 標的收盤未知的日子
        ]
        wi = {w: info() for w in ("030001", "030002", "030003")}
        uc = {(U, D1): 500.0, (U, D2): 600.0, (U, D3): 650.0}
        call = warrant_positions(trades, warrant_info=wi, under_close=uc, as_of=AS_OF)[(B, U)]["call"]
        self.assertEqual(call["buy_days"], [
            [D1, 150, 200_000, 500.0],     # 030001 剩 50 張 10 萬 + 030002 100 張 10 萬
            [D2, 50, 200_000, 600.0],
            [D4, 10, 10_000, None],
        ])
        self.assertEqual(sum(b[1] for b in call["buy_days"]), call["lots"])
        self.assertEqual(sum(b[2] for b in call["buy_days"]), call["cost"])

    def test_expired_and_no_price_are_held_but_not_valued(self):
        trades = [
            (B, U, "030001", D1, 100, 2.0),   # 已到期
            (B, U, "030003", D1, 100, 1.0),   # 無最後價
            (B, U, "030004", D1, 100, 1.0),   # 有估值:最後價 1.5
        ]
        wi = {
            "030001": info(maturity="2026-10-07"),
            "030003": info(last_price=None),
            "030004": info(last_price=1.5),
        }
        out = warrant_positions(trades, warrant_info=wi, under_close={(U, D1): 500.0}, as_of=AS_OF)
        call = out[(B, U)]["call"]
        self.assertEqual(call["lots"], 300)
        self.assertEqual(call["cost"], 400_000)
        self.assertEqual(call["cost_valued"], 100_000)
        self.assertEqual(call["value"], 150_000)
        self.assertEqual(call["unrealized"], 50_000)
        self.assertEqual(call["unrealized_pct"], 50.0)
        self.assertEqual((call["n_held"], call["n_expired"], call["n_no_price"]), (3, 1, 1))
        statuses = {r["warrant_id"]: r["status"] for r in call["warrants"]}
        self.assertEqual(statuses, {"030001": "expired", "030003": "no_price", "030004": "valued"})
        # 到期當天還算未到期(maturity_date == as_of)。
        wi["030001"].maturity_date = AS_OF
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF)
        self.assertEqual(out[(B, U)]["call"]["n_expired"], 0)

    def test_cost_unknown_leg_is_counted_but_excluded_from_everything_else(self):
        trades = [(B, U, W, D1, 100, None), (B, U, W, D2, 100, 4.0)]
        out = warrant_positions(trades, warrant_info={W: info()}, under_close={}, as_of=AS_OF)
        call = out[(B, U)]["call"]
        self.assertEqual(call["n_cost_unknown"], 1)
        self.assertEqual((call["lots"], call["cost"], call["n_held"]), (0, 0, 0))
        self.assertNotIn("unrealized", call)

    def test_closed_leg_contributes_realized_only(self):
        trades = [(B, U, W, D1, 100, 2.0), (B, U, W, D2, -100, 3.0)]
        out = warrant_positions(trades, warrant_info={W: info()}, under_close={}, as_of=AS_OF)
        call = out[(B, U)]["call"]
        self.assertEqual(call["realized"], 100_000)
        self.assertEqual((call["lots"], call["n_held"]), (0, 0))
        self.assertNotIn("unrealized", call)
        self.assertEqual(call["warrants"][0]["status"], "closed")

    def test_rows_after_as_of_and_unknown_warrants_are_ignored(self):
        trades = [(B, U, W, "2026-10-09", 100, 2.0), (B, U, "999999", D1, 100, 2.0)]
        out = warrant_positions(trades, warrant_info={W: info()}, under_close={}, as_of=AS_OF)
        self.assertEqual(out, {})

    def test_self_issued_cost_is_tracked(self):
        trades = [(B, U, W, D1, 100, 2.0), (B, U, "030002", D1, 100, 2.0)]
        wi = {W: info(), "030002": info()}
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF,
                                self_issued=lambda _b, w: w == W)
        call = out[(B, U)]["call"]
        self.assertEqual(call["self_cost"], 200_000)
        self.assertEqual({r["warrant_id"]: r.get("self", False) for r in call["warrants"]},
                         {W: True, "030002": False})

    def test_definitions_version(self):
        self.assertEqual(DEFINITIONS_VERSION, "wpos-avgcost-v1")


class ScreeningTests(unittest.TestCase):
    def _positions(self):
        base = {"lots": 1000, "n_held": 1, "n_expired": 0, "n_no_price": 0, "self_cost": 0,
                "last_buy_date": D5, "first_date": D1, "buy_days": [[D1, 400, 4_000_000, 500.0], [D5, 600, 6_000_000, 520.0]]}
        return {
            ("甲-分點", "2330"): {"call": {**base, "cost": 10_000_000, "value": 7_000_000,
                                          "unrealized": -3_000_000, "unrealized_pct": -30.0, "avg_under": 560.0}},
            ("乙-分點", "2330"): {"call": {**base, "cost": 20_000_000, "value": 24_000_000,
                                          "unrealized": 4_000_000, "unrealized_pct": 20.0, "avg_under": 500.0},
                                 "put": {**base, "cost": 6_000_000, "value": 3_000_000,
                                         "unrealized": -3_000_000, "unrealized_pct": -50.0}},
            ("丙-分點", "2317"): {"call": {**base, "cost": 4_000_000, "value": 1_000_000,
                                          "unrealized": -3_000_000, "unrealized_pct": -75.0}},     # < 500 萬
            ("凱基", "2330"): {"call": {**base, "cost": 30_000_000, "self_cost": 1_000_000,
                                       "value": 10_000_000, "unrealized": -20_000_000, "unrealized_pct": -66.7}},  # 總公司且有自家
            ("凱基-台北", "2330"): {"call": {**base, "cost": 30_000_000, "self_cost": 15_000_000,
                                          "value": 10_000_000, "unrealized": -20_000_000, "unrealized_pct": -66.7}},  # 自家 50%
            ("丁-分點", "2330"): {"call": {**base, "cost": 8_000_000, "n_expired": 1}},             # 全部到期,無估值
            ("戊-分點", "2330"): {"call": {**base, "lots": 0, "cost": 0}},
        }

    def test_threshold_ordering_and_self_exclusion(self):
        rows, meta = screening_rows(
            self._positions(), names={"2330": "台積電"}, under_last={"2330": (AS_OF, 580.0)},
            is_hq=lambda b: "-" not in b,
        )
        self.assertEqual([(r["branch_name"], r["kind"]) for r in rows],
                         [("乙-分點", "put"), ("甲-分點", "call"), ("乙-分點", "call"), ("丁-分點", "call")])
        self.assertEqual(meta, {"rows_total": 4, "excluded_self": 2, "min_cost": 5_000_000})
        first = rows[1]
        self.assertEqual(first["underlying_name"], "台積電")
        self.assertEqual((first["under_last"], first["under_last_date"]), (580.0, AS_OF))
        self.assertEqual(first["n_unvalued"], 0)
        self.assertEqual(first["self_pct"], 0)
        self.assertEqual(first["buy_days"], [[D1, 400, 4_000_000, 500.0], [D5, 600, 6_000_000, 520.0]])
        self.assertNotIn("unrealized", rows[3])
        self.assertEqual(rows[3]["n_unvalued"], 1)

    def test_max_rows(self):
        rows, meta = screening_rows(self._positions(), names={}, under_last={}, is_hq=lambda _b: False, max_rows=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(meta["rows_total"], 5)   # is_hq False → 凱基 不排除;凱基-台北 50% 仍排除


if __name__ == "__main__":
    unittest.main()
