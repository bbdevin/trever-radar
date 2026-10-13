"""wpos-avgcost-v1(docs/51):手算 fixture 釘住權證分點持有估算(串流版)。"""
import unittest

from radar.compute.warrant_position_est import (
    DEFINITIONS_VERSION,
    ENTRY_DAYS_MAX,
    PositionStream,
    WarrantInfo,
    _Leg,
    round_buy_days,
    screening_rows,
    summary_from_agg,
    warrant_positions,
)

AS_OF = "2026-10-08"
D1, D2, D3, D4, D5 = "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-07"
B, U, W = "凱基-台北", "2330", "030001"


def info(kind="call", last_price=2.5, maturity="2027-03-31"):
    return WarrantInfo(kind=kind, maturity_date=maturity, last_price=last_price, last_price_date=AS_OF)


def buys(leg: _Leg):
    return [(i, round(l, 6), round(c, 3)) for i, l, c in leg.buys()]


class LegTests(unittest.TestCase):
    def test_two_buys_cost_and_underlying_equivalent_average(self):
        leg = _Leg()
        leg.trade(D1, 0, 100, 2.0, 500.0)    # 20 萬,現股 500
        leg.trade(D2, 1, 100, 4.0, 600.0)    # 40 萬,現股 600
        self.assertEqual(leg.pos, 200)
        self.assertEqual(leg.cost, 600_000)
        # 以金額加權:(20萬×500 + 40萬×600) / 60萬 = 566.67,不是張數加權的 550。
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 566.6667, places=3)
        self.assertEqual(leg.last_buy_date, D2)
        self.assertEqual(buys(leg), [(0, 100, 200_000), (1, 100, 400_000)])

    def test_partial_sell_average_cost_then_unattributed_remainder(self):
        leg = _Leg()
        leg.trade(D1, 0, 100, 2.0, 500.0)
        leg.trade(D2, 1, 100, 4.0, 600.0)
        leg.trade(D3, 2, -50, 3.0, 700.0)    # 賣 50 張:均價 3.0,正好損益 0
        self.assertEqual(leg.pos, 150)
        self.assertAlmostEqual(leg.cost, 450_000)
        self.assertAlmostEqual(leg.realized, 0.0)
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 566.6667, places=3)  # 均價法:換算均價不變
        # 進場日等比例縮小(25% 賣掉 → 每天剩 75%),用縮放因子,不逐筆改。
        self.assertEqual(buys(leg), [(0, 75, 150_000), (1, 75, 300_000)])
        leg.trade(D4, 3, -200, 3.5, 700.0)   # 只剩 150 張可賣;50 張找不到對應買超
        self.assertEqual(leg.pos, 0)
        self.assertEqual(leg.cost, 0)
        self.assertAlmostEqual(leg.realized, 150 * 3.5 * 1000 - 450_000)  # +75,000
        self.assertEqual(leg.sell_attr, 200)
        self.assertEqual(leg.sell_unattr, 50)
        self.assertEqual(buys(leg), [])
        leg.trade(D5, 4, 10, 1.0, 650.0)     # 出清後重新建立,縮放因子歸 1
        self.assertEqual(buys(leg), [(4, 10, 10_000)])

    def test_same_day_rows_merge_into_one_buy_day(self):
        leg = _Leg()
        leg.trade(D1, 0, 100, 2.0, 500.0)
        leg.trade(D1, 0, 20, 2.0, 500.0)
        leg.trade(D2, 1, 80, 4.0, 600.0)
        self.assertEqual(buys(leg), [(0, 120, 240_000), (1, 80, 320_000)])

    def test_sell_before_any_buy_is_unattributed_not_short(self):
        leg = _Leg()
        leg.trade(D1, 0, -30, 2.0, 500.0)
        self.assertEqual((leg.pos, leg.cost, leg.realized), (0, 0, 0))
        self.assertEqual(leg.sell_unattr, 30)

    def test_missing_warrant_close_marks_cost_unknown(self):
        leg = _Leg()
        leg.trade(D1, 0, 100, None, 500.0)
        self.assertTrue(leg.price_missing)
        self.assertEqual(leg.pos, 0)

    def test_missing_underlying_close_only_skips_the_equivalent_average(self):
        leg = _Leg()
        leg.trade(D1, 0, 100, 2.0, None)
        leg.trade(D2, 1, 100, 4.0, 600.0)
        self.assertEqual(leg.cost, 600_000)
        self.assertEqual(leg.under_cost, 400_000)
        self.assertAlmostEqual(leg.under_num / leg.under_cost, 600.0)


class RoundBuyDaysTests(unittest.TestCase):
    def test_largest_remainder_keeps_sum_equal_to_held(self):
        # 買 3+3、賣 3 → 每天 1.5 張;四捨五入各自 2+2=4 ≠ 3。最大餘數法:1+2 或 2+1(平手取較早的日子)。
        days = [(D1, 1.5, 1500.0, 500.0), (D2, 1.5, 1500.0, 510.0)]
        out = round_buy_days(days, 3, 3000)
        self.assertEqual([x[1] for x in out], [2, 1])
        self.assertEqual(sum(x[1] for x in out), 3)
        self.assertEqual(sum(x[2] for x in out), 3000)

    def test_tiny_days_merge_into_neighbour_not_dropped(self):
        days = [(D1, 0.3, 300.0, 500.0), (D2, 0.2, 200.0, 510.0), (D3, 4.5, 4500.0, 520.0)]
        out = round_buy_days(days, 5, 5000)
        # 0.3/0.2 分不到 1 張 → 併入下一個有張數的日子;餘數 1 給餘數最大的 D3(4.5)。
        self.assertEqual(out, [[D3, 5, 5000, 520.0]])
        days = [(D1, 4.6, 4600.0, 500.0), (D2, 0.4, 400.0, 510.0)]
        out = round_buy_days(days, 5, 5000)
        self.assertEqual(out, [[D1, 5, 5000, 500.0]])   # 併入前一天

    def test_empty_and_zero(self):
        self.assertEqual(round_buy_days([], 0, 0), [])
        self.assertEqual(round_buy_days([(D1, 0.4, 400.0, None)], 0, 0), [])


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
        self.assertEqual((call["last_buy_date"], call["first_date"]), (D2, D1))
        self.assertEqual(call["buy_days"], [[D1, 100, 200_000, 500.0], [D2, 100, 400_000, 600.0]])
        self.assertNotIn("warrants", call)
        self.assertEqual(put["cost"], 300_000)
        self.assertEqual(put["unrealized"], 60_000)
        self.assertEqual(put["avg_under"], 600.0)
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

    def test_buy_days_are_in_date_order_even_when_a_later_leg_brings_an_earlier_date(self):
        """日索引依第一次遇到的順序配發;第二腿先買在更早的日子時,輸出仍要依日期排(2026-10-12 截圖抓到)。"""
        s = PositionStream(warrant_info={"030001": info(), "030002": info()}, under_close={}, as_of=AS_OF)
        s.feed(U, B, "030001", D3, 10, 1.0)   # 第一腿:只在 D3
        s.feed(U, B, "030002", D1, 20, 1.0)   # 第二腿:D1(更早)、D2
        s.feed(U, B, "030002", D2, 30, 1.0)
        s.finish()
        call = s.by_stock[U][B]["call"]
        self.assertEqual([d for d, *_ in call["buy_days"]], [D1, D2, D3])
        self.assertEqual([lots for _d, lots, *_ in call["buy_days"]], [20, 30, 10])
        self.assertEqual((call["first_date"], call["last_buy_date"]), (D1, D3))

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
        # 到期當天還算未到期(maturity_date == as_of)。
        wi["030001"].maturity_date = AS_OF
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF)
        self.assertEqual(out[(B, U)]["call"]["n_expired"], 0)

    def test_cost_unknown_leg_is_counted_but_excluded_from_every_total(self):
        trades = [
            (B, U, W, D1, 100, None), (B, U, W, D2, 100, 4.0), (B, U, W, D3, -20, 4.0),
            (B, U, "030002", D1, 50, 2.0),
        ]
        wi = {W: info(), "030002": info()}
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF)
        call = out[(B, U)]["call"]
        self.assertEqual((call["n_warrants"], call["n_cost_unknown"], call["n_held"]), (2, 1, 1))
        # 缺價的腿連買賣張數都不進總計,卡上的數字才對得起來。
        self.assertEqual((call["buy_lots"], call["sell_lots_attributed"], call["sell_lots_unattributed"]), (50, 0, 0))
        self.assertEqual((call["lots"], call["cost"]), (50, 100_000))

    def test_closed_leg_contributes_realized_only(self):
        trades = [(B, U, W, D1, 100, 2.0), (B, U, W, D2, -100, 3.0)]
        out = warrant_positions(trades, warrant_info={W: info()}, under_close={}, as_of=AS_OF)
        call = out[(B, U)]["call"]
        self.assertEqual(call["realized"], 100_000)
        self.assertEqual((call["lots"], call["n_held"]), (0, 0))
        self.assertEqual(call["buy_days"], [])
        self.assertNotIn("unrealized", call)

    def test_rows_after_as_of_unknown_and_bull_bear_warrants_are_ignored(self):
        trades = [
            (B, U, W, "2026-10-09", 100, 2.0),
            (B, U, "999999", D1, 100, 2.0),
            (B, U, "030009", D1, 100, 2.0),   # 牛證不進持有估算
        ]
        wi = {W: info(), "030009": info(kind="bull")}
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF)
        self.assertEqual(out, {})

    def test_self_issued_cost_is_tracked(self):
        trades = [(B, U, W, D1, 100, 2.0), (B, U, "030002", D1, 100, 2.0)]
        wi = {W: info(), "030002": info()}
        out = warrant_positions(trades, warrant_info=wi, under_close={}, as_of=AS_OF,
                                self_issued=lambda _b, w: w == W)
        self.assertEqual(out[(B, U)]["call"]["self_cost"], 200_000)

    def test_stream_groups_by_underlying_and_branch_and_only_keeps_outputs(self):
        """串流版:同組的腿連續餵,組換了就定稿成字串片段,換標的就合成一段 JSON;工作區清空。"""
        wi = {W: info(), "030002": info()}
        s = PositionStream(warrant_info=wi, under_close={}, as_of=AS_OF, screen_min_cost=0)
        s.feed(U, "甲", W, D1, 100, 2.0)
        s.feed(U, "甲", "030002", D1, 50, 1.0)
        s.feed(U, "乙", W, D1, 10, 2.0)
        self.assertEqual(len(s._stock_parts), 1)                              # 甲 已定稿成片段
        self.assertEqual((s._leg_key, s._leg.pos), ((U, "乙", W), 10))   # 乙 的腿還在工作區,還沒併進 agg
        s.feed("2317", "丙", W, D2, 5, 2.0)                                   # 換標的 → 2330 合成一段 JSON
        self.assertEqual(list(s.stock_json), [U])
        s.finish()
        self.assertEqual(s.by_stock[U]["甲"]["call"]["cost"], 250_000)
        self.assertEqual(s.by_stock[U]["乙"]["call"]["lots"], 10)
        self.assertEqual(s.by_stock["2317"]["丙"]["call"]["lots"], 5)
        self.assertEqual((s._aggs, s._stock_parts), ({}, []))
        self.assertEqual([(t[0], t[1], t[2]) for t in s.summaries], [("甲", U, "call"), ("乙", U, "call"), ("丙", "2317", "call")])
        # 摘要 tuple:只有 scalar,沒有 dict／list(進場日最後才從 stock_json 解)。
        self.assertFalse(any(isinstance(x, (dict, list)) for x in s.summaries[0]))
        self.assertEqual(len(s.summaries[0]), 3 + 13)

    def test_summaries_only_keep_rows_that_can_reach_the_screen(self):
        s = PositionStream(warrant_info={W: info()}, under_close={}, as_of=AS_OF, screen_min_cost=1_000_000)
        s.feed(U, "小", W, D1, 100, 2.0)        # 20 萬 < 門檻 → 不留摘要
        s.feed(U, "大", W, D1, 1000, 2.0)       # 200 萬 → 留
        s.finish()
        self.assertEqual([t[0] for t in s.summaries], ["大"])
        self.assertEqual(set(s.by_stock[U]), {"小", "大"})   # 分片仍兩家都有

    def test_entry_days_cap_keeps_largest_and_summarises_the_rest(self):
        """每天都買的腿:只存張數最大的 20 天,其餘併成 buy_days_rest,Σ 仍等於仍持有。"""
        days = [f"2026-0{1 + i // 28}-{1 + i % 28:02d}" for i in range(30)]
        trades = [(B, U, W, d, 10 + (i % 7), 1.0) for i, d in enumerate(days)]   # 10..16 張
        call = warrant_positions(trades, warrant_info={W: info()}, under_close={}, as_of="2026-12-31")[(B, U)]["call"]
        self.assertEqual(len(call["buy_days"]), ENTRY_DAYS_MAX)
        self.assertEqual([d for d, *_ in call["buy_days"]], sorted(d for d, *_ in call["buy_days"]))
        rest = call["buy_days_rest"]
        self.assertEqual(rest["n"], 10)
        self.assertEqual(sum(b[1] for b in call["buy_days"]) + rest["lots"], call["lots"])
        self.assertEqual(sum(b[2] for b in call["buy_days"]) + rest["cost"], call["cost"])
        self.assertTrue(min(b[1] for b in call["buy_days"]) >= 12)   # 留下的都是張數較大的日子
        # 張數 10/11 的日子(i%7 ∈ {0,1})是其餘:i = 0,1,7,8,…,28,29 → 最後一天是 days[29]。
        self.assertEqual((rest["first"], rest["last"]), (days[0], days[29]))

    def test_definitions_version(self):
        self.assertEqual(DEFINITIONS_VERSION, "wpos-avgcost-v1")


class ScreeningTests(unittest.TestCase):
    def _summaries(self):
        base = {"lots": 1000, "n_held": 1, "n_expired": 0, "n_no_price": 0, "self_cost": 0,
                "last_buy_date": D5, "first_date": D1, "buy_days": [[D1, 400, 4_000_000, 500.0], [D5, 600, 6_000_000, 520.0]]}
        raw = [
            ("甲-分點", "2330", "call", {**base, "cost": 10_000_000, "cost_valued": 10_000_000, "value": 7_000_000,
                                        "unrealized": -3_000_000, "unrealized_pct": -30.0, "avg_under": 560.0}),
            ("乙-分點", "2330", "call", {**base, "cost": 20_000_000, "value": 24_000_000,
                                        "unrealized": 4_000_000, "unrealized_pct": 20.0, "avg_under": 500.0}),
            ("乙-分點", "2330", "put", {**base, "cost": 6_000_000, "value": 3_000_000,
                                       "unrealized": -3_000_000, "unrealized_pct": -50.0}),
            ("丙-分點", "2317", "call", {**base, "cost": 4_000_000, "value": 1_000_000,
                                        "unrealized": -3_000_000, "unrealized_pct": -75.0}),     # < 500 萬
            ("凱基", "2330", "call", {**base, "cost": 30_000_000, "self_cost": 1_000_000,
                                     "value": 10_000_000, "unrealized": -20_000_000, "unrealized_pct": -66.7}),  # 總公司且有自家
            ("凱基-台北", "2330", "call", {**base, "cost": 30_000_000, "self_cost": 15_000_000,
                                        "value": 10_000_000, "unrealized": -20_000_000, "unrealized_pct": -66.7}),  # 自家 50%
            ("凱基-台北", "2330", "put", {**base, "cost": 9_000_000, "self_cost": 9_000_000, "unrealized_pct": -10.0}),  # 認售也排除
            ("丁-分點", "2330", "call", {**base, "cost": 8_000_000, "n_expired": 1,
                                        "buy_days_rest": {"n": 2, "lots": 5, "cost": 50_000, "first": D2, "last": D3}}),  # 全部到期,無估值
            ("戊-分點", "2330", "call", {**base, "lots": 0, "cost": 0}),
        ]
        return [summary_from_agg(*r) for r in raw]

    def test_per_kind_threshold_ordering_and_self_exclusion(self):
        days = [[D1, 400, 4_000_000, 500.0], [D5, 600, 6_000_000, 520.0]]
        rest_of_ding = {"n": 2, "lots": 5, "cost": 50_000, "first": D2, "last": D3}
        asked: list[tuple] = []

        def entry_days(branch, sid, kind):
            asked.append((branch, sid, kind))
            return days, (rest_of_ding if branch == "丁-分點" else None)

        kinds = screening_rows(
            self._summaries(), names={"2330": "台積電"}, under_last={"2330": (AS_OF, 580.0)},
            is_hq=lambda b: "-" not in b, entry_days=entry_days,
        )
        # 進場日只對留下的列查(不含被門檻／自家排除的)。
        self.assertEqual(sorted(asked), sorted([("甲-分點", "2330", "call"), ("乙-分點", "2330", "call"),
                                                ("丁-分點", "2330", "call"), ("乙-分點", "2330", "put")]))
        self.assertEqual(set(kinds), {"call", "put"})
        call, put = kinds["call"], kinds["put"]
        self.assertEqual(set(call), {"excluded_self", "down", "up"})
        # 帳面為負(最差在前,估不出值的接在最後);帳面為正另一份。
        self.assertEqual([r["branch_name"] for r in call["down"]["rows"]], ["甲-分點", "丁-分點"])
        self.assertEqual([r["branch_name"] for r in call["up"]["rows"]], ["乙-分點"])
        self.assertEqual((call["down"]["total"], call["up"]["total"], call["excluded_self"]), (2, 1, 2))
        self.assertEqual([r["branch_name"] for r in put["down"]["rows"]], ["乙-分點"])
        self.assertEqual((put["down"]["total"], put["up"], put["excluded_self"]), (1, {"rows": [], "total": 0}, 1))
        first = call["down"]["rows"][0]
        self.assertEqual(first["underlying_name"], "台積電")
        self.assertEqual((first["under_last"], first["under_last_date"]), (580.0, AS_OF))
        self.assertEqual((first["n_unvalued"], first["self_pct"], first["cost_valued"]), (0, 0, 10_000_000))
        self.assertEqual(first["buy_days"], days)
        last = call["down"]["rows"][1]
        self.assertNotIn("unrealized", last)
        self.assertEqual(last["n_unvalued"], 1)
        self.assertEqual(last["buy_days_rest"], rest_of_ding)
        self.assertNotIn("buy_days_rest", first)
        self.assertEqual(call["up"]["rows"][0]["unrealized_pct"], 20.0)
        self.assertEqual(call["up"]["rows"][0]["buy_days"], days)

    def _up_down_summaries(self):
        base = {"lots": 1000, "n_held": 1, "n_expired": 0, "n_no_price": 0, "self_cost": 0}

        def row(branch, pct, cost=10_000_000, kind="call", **over):
            agg = {**base, "cost": cost, **over}
            if pct is not None:
                agg.update(cost_valued=cost, value=round(cost * (1 + pct / 100)),
                           unrealized=round(cost * pct / 100), unrealized_pct=pct)
            return summary_from_agg(branch, "2330", kind, agg)

        return [
            row("甲", 35.0), row("乙", 80.0), row("丙", 12.5, cost=30_000_000), row("丁", 12.5, cost=60_000_000),
            row("戊", -5.0), row("己", 0.0), row("庚", None, n_expired=1),          # 0% 與估不出值 → down
            row("辛", 50.0, self_cost=6_000_000),                                    # 自家過半 → 排除(不分正負)
            row("壬", -30.0, self_cost=9_000_000),
            row("癸", 90.0, kind="put"), row("子", 40.0, kind="put"),
        ]

    def test_up_side_best_first_and_unvalued_stay_out(self):
        kinds = screening_rows(self._up_down_summaries(), names={}, under_last={}, is_hq=lambda _b: False)
        call = kinds["call"]
        # 帳面 % 由高到低,同 % 成本大的在前。
        self.assertEqual([r["branch_name"] for r in call["up"]["rows"]], ["乙", "甲", "丁", "丙"])
        self.assertTrue(all(r["unrealized_pct"] > 0 for r in call["up"]["rows"]))
        # 0% 進 down(不是「為正」),估不出值的接在 down 最後,不進 up。
        self.assertEqual([r["branch_name"] for r in call["down"]["rows"]], ["戊", "己", "庚"])
        self.assertEqual(call["excluded_self"], 2)
        self.assertEqual([r["branch_name"] for r in kinds["put"]["up"]["rows"]], ["癸", "子"])
        self.assertEqual((kinds["put"]["down"]["total"], kinds["put"]["excluded_self"]), (0, 0))

    def test_cap_is_per_side_and_totals_are_honest(self):
        asked: list[str] = []

        def entry_days(branch, _sid, _kind):
            asked.append(branch)
            return [], None

        kinds = screening_rows(self._up_down_summaries(), names={}, under_last={}, is_hq=lambda _b: False,
                               max_rows=2, entry_days=entry_days)
        call = kinds["call"]
        self.assertEqual([r["branch_name"] for r in call["up"]["rows"]], ["乙", "甲"])
        self.assertEqual([r["branch_name"] for r in call["down"]["rows"]], ["戊", "己"])
        self.assertEqual((call["up"]["total"], call["down"]["total"]), (4, 3))
        # 進場日只對兩邊留下來的列查。
        self.assertEqual(sorted(asked), sorted(["乙", "甲", "戊", "己", "癸", "子"]))

    def test_empty_screening_shape(self):
        from radar.compute.warrant_position_est import empty_screening
        empty = empty_screening()
        self.assertEqual(empty, screening_rows([], names={}, under_last={}, is_hq=lambda _b: False))
        self.assertEqual(empty["call"], {"excluded_self": 0, "down": {"rows": [], "total": 0},
                                         "up": {"rows": [], "total": 0}})

    def test_entry_days_lookup_reads_back_from_stock_json(self):
        from radar.compute.warrant_position_est import entry_days_lookup
        s = PositionStream(warrant_info={W: info()}, under_close={}, as_of=AS_OF, screen_min_cost=0)
        s.feed(U, "甲", W, D1, 100, 2.0)
        s.feed(U, "甲", W, D2, 50, 2.0)
        s.finish()
        lookup = entry_days_lookup(s.stock_json)
        self.assertEqual(lookup("甲", U, "call"), ([[D1, 100, 200_000, None], [D2, 50, 100_000, None]], None))
        self.assertEqual(lookup("甲", U, "put"), ([], None))
        self.assertEqual(lookup("不存在", "9999", "call"), ([], None))

    def test_cap_is_per_kind_and_total_is_honest(self):
        kinds = screening_rows(self._summaries(), names={}, under_last={}, is_hq=lambda _b: False, max_rows=1)
        self.assertEqual(len(kinds["call"]["down"]["rows"]), 1)
        self.assertEqual(kinds["call"]["down"]["total"], 3)   # is_hq False → 凱基 不排除;凱基-台北 50% 仍排除
        self.assertEqual(kinds["call"]["up"]["total"], 1)
        self.assertEqual(kinds["call"]["excluded_self"], 1)
        self.assertEqual(len(kinds["put"]["down"]["rows"]), 1)
        self.assertEqual(kinds["put"]["down"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
