"""個股 JSON 的 `branch_tags`(籌碼日報分點標籤:地緣/隔日沖/追蹤)。

釘住的契約:
  * 鍵永遠存在;沒有就是空清單,不是缺鍵(前端缺鍵與空清單都畫「什麼都不標」)。
  * 名字只限這檔股票 payload 裡會出現的分點(branch_history ∪ 當日 branches)。
  * 隔日沖只收 is_daytrade_suspect = 1;NULL(未判定)與 0 都不輸出。
  * 地緣排除總公司/外資席位;公司縣市未知 → rule 為 null、名單為空。
  * 門檻數字從 compute_branch_stats 讀,不寫死。
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import radar.config as config
import radar.db as db
from radar import schema
from radar.compute.compute_branch_stats import DAYTRADE_MIN_OBS, DAYTRADE_RATE
from radar.export import json_export as je
from radar.export.json_export import export_json
from radar.importer import upsert_branch_trades

DATES = ("2026-08-03", "2026-08-04", "2026-08-05")
NOW = "2026-08-05T20:00:00+08:00"


def _trade(stock_id, day, key, name, net):
    return {"stock_id": stock_id, "date": day, "branch_key": key, "branch_name": name,
            "buy_lots": max(net, 0), "sell_lots": max(-net, 0), "net_lots": net, "pct": 0}


class BranchTagsExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1},
                {"id": "2317", "name": "鴻海", "market": "twse", "type": "stock", "is_active": 1},
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 100.0, "volume": 1_000_000, "turnover": 1}
                for sid in ("2330", "2317") for day in DATES
            ])
            upsert_branch_trades(conn, [
                _trade("2330", DATES[-1], "a", "凱基-新竹", 300),
                _trade("2330", DATES[-1], "b", "元大-竹科", 200),
                _trade("2330", DATES[-1], "c", "凱基", 150),             # 總公司
                _trade("2330", DATES[-1], "d", "美商高盛", -400),        # 外資
                _trade("2330", DATES[-1], "e", "富邦-台北", -100),
                _trade("2330", DATES[0], "f", "群益-竹北", 50),          # 只在較早一天出現
                _trade("2317", DATES[-1], "a", "凱基-新竹", 10),
            ])
            conn.execute(schema.company_profiles.insert(), [
                {"stock_id": "2330", "address": "新竹市力行六路8號", "city": "新竹市",
                 "district": "東區", "market": "twse", "updated_at": NOW},
            ])
            conn.execute(schema.broker_branch_geo.insert(), [
                {"name_key": "凱基-新竹", "branch_name": "凱基-新竹", "city": "新竹市",
                 "district": "北區", "kind": "branch", "updated_at": NOW},
                {"name_key": "元大-竹科", "branch_name": "元大-竹科", "city": "新竹市",
                 "district": "東區", "kind": "branch", "updated_at": NOW},
                # 地址同城,但總公司/外資席位不算地緣
                {"name_key": "凱基", "branch_name": "凱基", "city": "新竹市",
                 "district": "東區", "kind": "hq", "updated_at": NOW},
                {"name_key": "美商高盛", "branch_name": "美商高盛", "city": "新竹市",
                 "district": "東區", "kind": "foreign", "updated_at": NOW},
                {"name_key": "富邦-台北", "branch_name": "富邦-台北", "city": "台北市",
                 "district": "中正區", "kind": "branch", "updated_at": NOW},
                {"name_key": "群益-竹北", "branch_name": "群益-竹北", "city": "新竹縣",
                 "district": "竹北市", "kind": "branch", "updated_at": NOW},
            ])
            conn.execute(schema.branch_stock_stats.insert(), [
                {"branch_name": "凱基-新竹", "stock_id": "2330", "is_daytrade_suspect": True,
                 "daytrade_obs": 12, "daytrade_paybacks": 9},
                {"branch_name": "元大-竹科", "stock_id": "2330", "is_daytrade_suspect": None,
                 "daytrade_obs": 3, "daytrade_paybacks": 3},
                {"branch_name": "富邦-台北", "stock_id": "2330", "is_daytrade_suspect": False,
                 "daytrade_obs": 20, "daytrade_paybacks": 1},
                # 判定為隔日沖,但這檔股票的 payload 裡沒有這個分點 → 不輸出
                {"branch_name": "永豐-板橋", "stock_id": "2330", "is_daytrade_suspect": True,
                 "daytrade_obs": 10, "daytrade_paybacks": 8},
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "富邦-台北", "source": "manual"},
                {"branch_name": "永豐-板橋", "source": "manual"},
            ])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _export(self, sid):
        out = Path(self._tmp.name) / "out"
        out.mkdir(parents=True, exist_ok=True)
        export_json(out)
        return json.loads((out / "stocks" / f"{sid}.json").read_text(encoding="utf-8"))

    def _names(self, payload):
        names = {b["n"] for day in payload["branch_history"] for b in day["branches"]}
        return names | {b["name"] for b in payload["branches"]}

    def test_shape_and_contents(self):
        payload = self._export("2330")
        tags = payload["branch_tags"]
        self.assertEqual(set(tags), {"as_of", "geo", "daytrade", "tracked"})
        self.assertEqual(tags["as_of"], DATES[-1])
        self.assertEqual(tags["geo"], {"rule": "city", "names": ["元大-竹科", "凱基-新竹"]})
        self.assertEqual(tags["daytrade"]["min_obs"], DAYTRADE_MIN_OBS)
        self.assertEqual(tags["daytrade"]["rate"], DAYTRADE_RATE)
        self.assertEqual(tags["daytrade"]["rows"], {"凱基-新竹": [12, 9]})
        self.assertEqual(tags["tracked"], ["富邦-台北"])

    def test_names_are_a_subset_of_the_stock_payload(self):
        payload = self._export("2330")
        tags = payload["branch_tags"]
        names = self._names(payload)
        self.assertLessEqual(set(tags["geo"]["names"]), names)
        self.assertLessEqual(set(tags["daytrade"]["rows"]), names)
        self.assertLessEqual(set(tags["tracked"]), names)
        self.assertNotIn("永豐-板橋", tags["daytrade"]["rows"])
        self.assertNotIn("永豐-板橋", tags["tracked"])

    def test_null_and_false_suspects_are_not_exported(self):
        rows = self._export("2330")["branch_tags"]["daytrade"]["rows"]
        self.assertNotIn("元大-竹科", rows, "NULL 是未判定,不得輸出")
        self.assertNotIn("富邦-台北", rows, "0 不是隔日沖,不輸出")

    def test_hq_and_foreign_seats_are_never_geo(self):
        names = self._export("2330")["branch_tags"]["geo"]["names"]
        self.assertNotIn("凱基", names)
        self.assertNotIn("美商高盛", names)

    def test_unknown_company_city_gives_null_rule_and_keys_still_present(self):
        tags = self._export("2317")["branch_tags"]
        self.assertIsNone(tags["geo"]["rule"])
        self.assertEqual(tags["geo"]["names"], [])
        self.assertEqual(tags["daytrade"]["rows"], {})
        self.assertEqual(tags["tracked"], [])

    def test_dual_north_needs_same_district(self):
        geo = {"富邦-台北": {"city": "台北市", "district": "中正區", "kind": "branch"},
               "國泰-信義": {"city": "台北市", "district": "信義區", "kind": "branch"}}
        names = {"富邦-台北", "國泰-信義"}
        tags = je._branch_tags_payload(
            as_of="x", names=names,
            profile={"city": "台北市", "district": "信義區"},
            geo_by_key=geo, tracked_keys=set(), daytrade_rows={})
        self.assertEqual(tags["geo"], {"rule": "district", "names": ["國泰-信義"]})
        no_district = je._branch_tags_payload(
            as_of="x", names=names, profile={"city": "台北市", "district": None},
            geo_by_key=geo, tracked_keys=set(), daytrade_rows={})
        self.assertEqual(no_district["geo"], {"rule": None, "names": []})


if __name__ == "__main__":
    unittest.main()
