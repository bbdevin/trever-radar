"""docs/27 G2:地緣/關鍵/題材 tag 純函式(不進綜合分)。"""
import unittest

from radar.pocket import (
    broker_family,
    geo_trigger,
    hot_theme_names,
    hot_theme_trigger,
    in_geo_circle,
    key_buy_trigger,
    pocket_qualifies,
    pocket_score,
    tag_stock,
    PocketContext,
)


def _dates(n=20):
    return [f"2026-07-{i + 1:02d}" for i in range(n)]


def _geo(city, district, kind="branch", broker_id="B1"):
    return {"city": city, "district": district, "kind": kind, "broker_id": broker_id}


class CircleTests(unittest.TestCase):
    def test_non_dual_same_city(self):
        self.assertTrue(in_geo_circle("高雄市", "左營區", "高雄市", "鳳山區"))

    def test_dual_north_same_district(self):
        self.assertTrue(in_geo_circle("台北市", "信義區", "台北市", "信義區"))

    def test_dual_north_other_district(self):
        self.assertFalse(in_geo_circle("台北市", "信義區", "台北市", "大安區"))

    def test_dual_north_missing_district_failsafe(self):
        self.assertIsNone(in_geo_circle("台北市", None, "台北市", "信義區"))

    def test_missing_city_failsafe(self):
        self.assertIsNone(in_geo_circle(None, None, "高雄市", "左營區"))


class GeoTriggerTests(unittest.TestCase):
    def setUp(self):
        self.win = _dates(20)
        self.geo = {
            "玉山-左營": _geo("高雄市", "左營區", broker_id="9A00"),
            "華南永昌-鳳山": _geo("高雄市", "鳳山區", broker_id="9200"),
            "永豐金-高雄": _geo("高雄市", "新興區", broker_id="9A9A"),
            "凱基": _geo("台北市", "信義區", kind="hq", broker_id="9200"),
            "美林": _geo("台北市", "信義區", kind="foreign", broker_id="F"),
        }
        # 每日成交 100_000 股 → 20 日 2_000_000 股;0.5% = 10 張
        self.vols = {d: 100_000 for d in self.win}

    def _trades(self):
        rows = []
        for d in self.win:
            rows.append({"date": d, "branch_name": "玉山-左營", "net_lots": 20})
            rows.append({"date": d, "branch_name": "華南永昌-鳳山", "net_lots": 20})
            rows.append({"date": d, "branch_name": "永豐金-高雄", "net_lots": 20})
        return rows

    def test_three_brokers_triggers_buy(self):
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=self._trades(), geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNotNone(tag)
        self.assertEqual(tag["code"], "G1_GEO_BUY")
        self.assertEqual(tag["family"], "GEO")
        self.assertEqual(tag["brokers"], 3)
        self.assertEqual(tag["strength"], "strong")
        self.assertIn("統計推測", tag["text"])

    def test_hq_and_foreign_excluded(self):
        trades = []
        for d in self.win:
            trades.append({"date": d, "branch_name": "凱基", "net_lots": 800})
            trades.append({"date": d, "branch_name": "美林", "net_lots": 800})
            trades.append({"date": d, "branch_name": "玉山-左營", "net_lots": 20})
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=trades, geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNone(tag)  # 只剩 1 家地緣券商

    def test_unmatched_branch_not_geo(self):
        trades = []
        for d in self.win:
            trades.append({"date": d, "branch_name": "神秘-高雄", "net_lots": 500})
            trades.append({"date": d, "branch_name": "玉山-左營", "net_lots": 20})
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=trades, geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNone(tag)

    def test_one_broker_two_branches_not_enough(self):
        geo = {
            "玉山-左營": _geo("高雄市", "左營區", broker_id="9A00"),
            "玉山-鳳山": _geo("高雄市", "鳳山區", broker_id="9A00"),
        }
        trades = []
        for d in self.win:
            trades.append({"date": d, "branch_name": "玉山-左營", "net_lots": 200})
            trades.append({"date": d, "branch_name": "玉山-鳳山", "net_lots": 200})
        tag = geo_trigger(
            company_city="高雄市", company_district=None,
            trades=trades, geo_by_key=geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNone(tag)

    def test_no_streak(self):
        trades = []
        # 兩家券商出現,但沒有任何分點連 3 日
        a, b = "玉山-左營", "華南永昌-鳳山"
        for i, d in enumerate(self.win):
            if i % 2 == 0:
                trades.append({"date": d, "branch_name": a, "net_lots": 100})
            else:
                trades.append({"date": d, "branch_name": b, "net_lots": 100})
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=trades, geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNone(tag)

    def test_share_too_small(self):
        trades = []
        for i, d in enumerate(self.win):
            net = 1  # 20 日 × 3 家 = 60 張;60*1000/2e6 = 3% wait that's 3%...
            # period vol 2e6 股; need < 0.5% → geo_abs*1000 < 10000 → geo_abs < 10
            # 3 brokers × 20 days × 0 lots almost: use 0 most days, 1 lot few days but need streak
            n = 1 if i < 3 else 0
            trades.append({"date": d, "branch_name": "玉山-左營", "net_lots": n})
            trades.append({"date": d, "branch_name": "華南永昌-鳳山", "net_lots": n})
            trades.append({"date": d, "branch_name": "永豐金-高雄", "net_lots": n})
        # geo_net = 9 張; 9000/2e6 = 0.45% < 0.5%; top15 share = 100% >= 25% → WOULD pass via top15
        # bump volume so top15 share still 100%... that's the OR. Need both small.
        # Add a huge non-geo buy so top15 share is tiny
        for d in self.win:
            trades.append({"date": d, "branch_name": "神秘-台北", "net_lots": 10_000})
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=trades, geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNone(tag)

    def test_sell_mirror(self):
        trades = []
        for d in self.win:
            trades.append({"date": d, "branch_name": "玉山-左營", "net_lots": -20})
            trades.append({"date": d, "branch_name": "華南永昌-鳳山", "net_lots": -20})
            trades.append({"date": d, "branch_name": "永豐金-高雄", "net_lots": -20})
        tag = geo_trigger(
            company_city="高雄市", company_district="左營區",
            trades=trades, geo_by_key=self.geo,
            window_dates=self.win, volumes=self.vols, side="sell",
        )
        self.assertIsNotNone(tag)
        self.assertEqual(tag["code"], "G2_GEO_SELL")
        self.assertIn("賣超", tag["text"])

    def test_dual_north_uses_district(self):
        geo = {
            "富邦-信義": _geo("台北市", "信義區", broker_id="1"),
            "凱基-信義": _geo("台北市", "信義區", broker_id="2"),
            "元大-大安": _geo("台北市", "大安區", broker_id="3"),
        }
        trades = []
        for d in self.win:
            trades.append({"date": d, "branch_name": "富邦-信義", "net_lots": 50})
            trades.append({"date": d, "branch_name": "凱基-信義", "net_lots": 50})
            trades.append({"date": d, "branch_name": "元大-大安", "net_lots": 50})
        tag = geo_trigger(
            company_city="台北市", company_district="信義區",
            trades=trades, geo_by_key=geo,
            window_dates=self.win, volumes=self.vols, side="buy",
        )
        self.assertIsNotNone(tag)
        self.assertEqual(tag["brokers"], 2)  # 大安不算
        self.assertEqual(tag["strength"], "weak")


class KeyThemePocketTests(unittest.TestCase):
    def test_key_buy_lots(self):
        win = _dates(5)
        trades = [{"date": win[-1], "branch_name": "富邦-新店", "net_lots": 500}]
        vols = {d: 1_000_000 for d in win}  # 500張/5000千股 = 10% anyway
        tag = key_buy_trigger(
            trades=trades, key_keys={"富邦-新店"},
            window_dates=win, volumes=vols,
        )
        self.assertEqual(tag["code"], "K1_KEY_BUY")
        self.assertIn("富邦-新店", tag["text"])

    def test_key_buy_share_without_500(self):
        win = _dates(5)
        # 40 張 × 1000 / 100_000 股(5日合計 500_000) = 8% wait 40000/500000=8%
        # want 0.3%: 40*1000/ vol_sum >= 0.003 → vol_sum <= 40e3/0.003 ≈ 13.3e6
        trades = [{"date": win[0], "branch_name": "凱基-信義", "net_lots": 40}]
        vols = {d: 100_000 for d in win}  # 500_000 股; 40000/500000 = 8%
        tag = key_buy_trigger(
            trades=trades, key_keys={"凱基-信義"},
            window_dates=win, volumes=vols,
        )
        self.assertIsNotNone(tag)

    def test_key_ignores_non_key(self):
        win = _dates(5)
        trades = [{"date": win[-1], "branch_name": "隨便-分點", "net_lots": 900}]
        tag = key_buy_trigger(
            trades=trades, key_keys={"富邦-新店"},
            window_dates=win, volumes={d: 1000 for d in win},
        )
        self.assertIsNone(tag)

    def test_hot_theme_top10(self):
        themes = [
            {"name": f"T{i}", "vs20": 2.0 - i * 0.05, "turnover": 1e9}
            for i in range(12)
        ]
        names = hot_theme_names(themes)
        self.assertEqual(len(names), 10)
        self.assertEqual(names[0], "T0")
        self.assertNotIn("T10", names)  # 第 11 名 vs20=1.5 仍 ≥1.15 但排外
        tag = hot_theme_trigger(["T0", "其他"], names)
        self.assertEqual(tag["family"], "THEME")
        self.assertIsNone(hot_theme_trigger(["T10"], names))

    def test_hot_theme_vs20_floor(self):
        themes = [{"name": "冷", "vs20": 1.10, "turnover": 9e9}]
        self.assertEqual(hot_theme_names(themes), [])

    def test_pocket_score_decoupled(self):
        self.assertEqual(pocket_score(set()), 0)
        self.assertEqual(pocket_score({"GEO"}), 30)
        self.assertEqual(pocket_score({"GEO", "KEY"}), 60)
        self.assertEqual(pocket_score({"GEO", "KEY", "THEME"}), 75)
        self.assertEqual(pocket_score({"ARMED"}), 10)
        self.assertEqual(pocket_score({"CONC"}), 10)
        self.assertEqual(pocket_score({"ARMED", "CONC"}), 10)  # 至多一次
        self.assertFalse(pocket_qualifies({"GEO"}))
        self.assertTrue(pocket_qualifies({"GEO", "KEY"}))

    def test_tag_stock_does_not_touch_scores(self):
        win20 = _dates(20)
        win5 = win20[-5:]
        ctx = PocketContext(
            companies={"2476": {"city": "高雄市", "district": "大寮區"}},
            geo_by_key={
                "玉山-左營": _geo("高雄市", "左營區", broker_id="a"),
                "華南永昌-鳳山": _geo("高雄市", "鳳山區", broker_id="b"),
                "永豐金-高雄": _geo("高雄市", "新興區", broker_id="c"),
            },
            key_keys={"富邦-新店"},
            trades={"2476": (
                [{"date": d, "branch_name": "玉山-左營", "net_lots": 20} for d in win20]
                + [{"date": d, "branch_name": "華南永昌-鳳山", "net_lots": 20} for d in win20]
                + [{"date": d, "branch_name": "永豐金-高雄", "net_lots": 20} for d in win20]
                + [{"date": win5[-1], "branch_name": "富邦-新店", "net_lots": 500}]
            )},
            volumes={"2476": {d: 100_000 for d in win20}},
        )
        stock = {
            "id": "2476",
            "scores": {"final": 71, "branch": 40},
            "themes": ["矽晶圓"],
            "state": "armed",
        }
        tag_stock(
            "2476", stock, ctx, win20, win5,
            hot_names=["矽晶圓"], conc_ids=set(),
        )
        self.assertEqual(stock["scores"]["final"], 71)
        fams = set(stock["pocket_families"])
        self.assertGreaterEqual(fams, {"GEO", "KEY", "THEME", "ARMED"})
        self.assertEqual(stock["pocket_score"], 30 + 30 + 15 + 10)
        codes = {t["code"] for t in stock["pocket_tags"]}
        self.assertIn("G1_GEO_BUY", codes)
        self.assertIn("K1_KEY_BUY", codes)
        self.assertIn("H1_HOT_THEME", codes)

    def test_broker_family_prefix(self):
        self.assertEqual(broker_family("玉山-左營"), "玉山")
        self.assertEqual(broker_family("玉山-鳳山", "OTHER"), "玉山")


if __name__ == "__main__":
    unittest.main()
