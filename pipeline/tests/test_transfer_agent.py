"""股代(docs/37 §3.1):股票過戶機構 → 券商 → 總公司席位,以及換股代的歷史。

樣本取自 2026-10-04 實抓的 TWSE t187ap03_L / MOPS t187ap03_O「股票過戶機構」欄原文。
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

import radar.config as config
import radar.db as db
from radar import schema
from radar.geo import (
    BROKER_ALIASES,
    MERGED_BROKERS,
    hq_seat_broker,
    is_agent_seat,
    transfer_agent_broker,
)
from radar.import_geo import update_transfer_agent_history


class TransferAgentBrokerTests(unittest.TestCase):
    def test_real_spellings_map_to_one_broker(self):
        cases = {
            "元大證券股份有限公司": "元大",
            "元大證券(股)公司股務代理部": "元大",
            "元大證券股份有限公司股代部": "元大",
            "元大証券股份有限公司": "元大",
            "元大綜合證券股份有限公司": "元大",
            "元大證券股份限公司股務代理部": "元大",
            "群益金鼎證券股份有限公司": "群益金鼎",
            "群益 金鼎證券〈股〉股務代理部": "群益金鼎",
            "群益證券股份有限公司": "群益金鼎",
            "群益金鼎證券(股務代理部)": "群益金鼎",
            "台新綜合證券(股)公司股務代理部": "台新",
            "台新綜合證&#21173;股務代理部": "台新",
            "台新綜合證券  股務代理部": "台新",
            "台新綜合證券股分有限公司": "台新",
            "凱基證券股份有限公司股務代理部": "凱基",
            "凱碁證券股份有限公司": "凱基",
            "凱基證券(股)公司-股務代理部": "凱基",
            "福邦證券股份有限公司": "福邦",
            "褔邦證券股份有限公司股務代理部": "福邦",
            "永豐金證券股務代理部": "永豐金",
            "永豐金証券(股)公司股務代理部": "永豐金",
            "富邦綜合證券(股)公 司": "富邦",
            "富邦證券股務代理部": "富邦",
            "華南永昌綜合證券(股)股務代理部": "華南永昌",
            "華南永昌證券股份有限公司": "華南永昌",
            "第一金證券(股)公司股務代理部": "第一金",
            "統一證券〈股〉公司股務代理部": "統一",
            "統一綜合證券股份有限公司": "統一",
            "國票綜合證券(股)公司代理部": "國票",
            "康和證券集團股務代理部": "康和",
            "兆豐證券(股)公司股務代理本部": "兆豐",
            "兆豐證券": "兆豐",
            "亞東證券": "亞東",
            "宏遠證券股份有限公司(95.3.3起)": "宏遠",
            "國泰證券股務代理部": "國泰",
            "新光證券(股)公司股務代理部": "新光",
        }
        for text, broker in cases.items():
            with self.subTest(text=text):
                self.assertEqual(transfer_agent_broker(text), broker)

    def test_banks_and_self_service_are_not_brokers(self):
        for text in (
            "中國信託商業銀行代理部", "中國信託商業銀行 代理部", "中國信託商業銀行(股)公司代理部",
            "中國信託商業銀&#64008;代理部", "中國信託商銀代理部", "中信銀股務代理部",
            "中國信託代理部", "中國信託股務代理部", "第一銀行信託處", "玉山金控行政管理處",
            "本公司股務組", "本公司股務室", "自辦", "股務課", "宏碁股份有限公司股務室",
            "國泰建設財務組(股務)", "大西洋飲料股份有限公司", None, "",
        ):
            with self.subTest(text=text):
                self.assertIsNone(transfer_agent_broker(text))

    def test_merged_brands_resolve_to_surviving_firm_in_agent_text(self):
        self.assertEqual(transfer_agent_broker("大華證券股份有限公司"), "凱基")
        self.assertEqual(transfer_agent_broker("台証綜合證券股份有限公司"), "凱基")
        self.assertEqual(transfer_agent_broker("寶來證券股份有限公司"), "元大")
        self.assertEqual(transfer_agent_broker("元大寶來證券股份有限公司"), "元大")
        self.assertEqual(transfer_agent_broker("金鼎證券股份有限公司"), "群益金鼎")
        # 沒有把握的合併不列:原樣回傳,對不到總公司席位就不標(fail closed)
        self.assertEqual(transfer_agent_broker("日盛證券股份有限公司股務代理部"), "日盛")
        # 每個別名都指向一家「現在的」券商,不會再指向另一個別名
        for table in (BROKER_ALIASES, MERGED_BROKERS):
            for alias, firm in table.items():
                self.assertNotIn(firm, BROKER_ALIASES, f"{alias}→{firm} 不能是鏈")
                self.assertNotIn(firm, MERGED_BROKERS, f"{alias}→{firm} 不能是鏈")

    def test_html_entities_and_full_width(self):
        self.assertEqual(transfer_agent_broker("台新綜合證&#21173;股務代理部"), "台新")
        self.assertIsNone(transfer_agent_broker("中國信託商業銀&#64008;代理部"))
        self.assertEqual(transfer_agent_broker("元大證券（股）公司股務代理部"), "元大")

    def test_china_trust_securities_is_a_broker_but_the_bank_is_not(self):
        self.assertEqual(transfer_agent_broker("中國信託綜合證券股份有限公司"), "中國信託")
        self.assertEqual(transfer_agent_broker("中信證券股務代理部"), "中國信託")
        self.assertIsNone(transfer_agent_broker("中國信託商業銀行代理部"))
        self.assertTrue(is_agent_seat("中國信託", "中國信託"))

    def test_self_run_broker_tags_its_own_head_office(self):
        """券商股自己當股代(例:群益證的股代是群益金鼎)→ 標自家總公司席位,不特別排除。"""
        broker = transfer_agent_broker("群益金鼎證券股份有限公司股務代理部")
        self.assertTrue(is_agent_seat("群益金鼎", broker))
        self.assertTrue(is_agent_seat("群益金鼎證券", broker))


class AgentSeatTests(unittest.TestCase):
    def test_only_the_head_office_seat_is_tagged(self):
        self.assertTrue(is_agent_seat("凱基", "凱基"))
        self.assertTrue(is_agent_seat("凱基證券", "凱基"))
        self.assertTrue(is_agent_seat("元大證券", "元大"))
        self.assertTrue(is_agent_seat("永豐金證券", "永豐金"))
        self.assertTrue(is_agent_seat("臺新", "台新"))
        for branch in ("凱基-松山", "凱基-新竹", "凱基-自營", "元大-南京", "元大期貨", "元大期貨-自營"):
            with self.subTest(branch=branch):
                self.assertFalse(is_agent_seat(branch, "凱基") or is_agent_seat(branch, "元大"))

    def test_no_prefix_collisions(self):
        pairs = (("元大", "元富"), ("國泰", "國票"), ("富邦", "福邦"), ("元大", "元大期貨"),
                 ("群益金鼎", "群益期貨"), ("華南永昌", "華南"), ("第一金", "第一"))
        for broker, other_seat in pairs:
            with self.subTest(broker=broker, seat=other_seat):
                if other_seat in BROKER_ALIASES and BROKER_ALIASES[other_seat] == broker:
                    continue  # 「華南」「第一」是同一家券商的舊稱,本來就該對到
                self.assertFalse(is_agent_seat(other_seat, broker))
        self.assertFalse(is_agent_seat("元富", "元大"))
        self.assertFalse(is_agent_seat("國票", "國泰"))
        self.assertFalse(is_agent_seat("福邦", "富邦"))
        self.assertFalse(is_agent_seat("富邦", "福邦"))

    def test_old_brand_head_office_seat_is_not_the_surviving_firm(self):
        """合併前的「大華」總公司席位是另一家公司,不能當成凱基的總公司。"""
        self.assertEqual(hq_seat_broker("大華"), "大華")
        self.assertFalse(is_agent_seat("大華", "凱基"))
        self.assertFalse(is_agent_seat("寶來證券", "元大"))
        self.assertIsNone(hq_seat_broker("凱基-大華"))
        # 同一家的簡寫則兩邊都套
        self.assertEqual(hq_seat_broker("群益"), "群益金鼎")
        self.assertEqual(hq_seat_broker("永豐金證券"), "永豐金")

    def test_no_broker_tags_nothing(self):
        self.assertFalse(is_agent_seat("凱基", None))
        self.assertFalse(is_agent_seat("", "凱基"))

    def test_zhongtanzhen_example(self):
        """使用者範例:中探針股代=凱基 → 只有凱基總公司席位標股代。"""
        broker = transfer_agent_broker("凱基證券股份有限公司股務代理部")
        self.assertEqual(broker, "凱基")
        self.assertTrue(is_agent_seat("凱基", broker))
        self.assertFalse(is_agent_seat("凱基-台北", broker))


class TransferAgentHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _run(self, day, agents):
        with db.get_engine().begin() as conn:
            return update_transfer_agent_history(
                conn, [{"stock_id": s, "transfer_agent": a} for s, a in agents.items()], day)

    def _rows(self):
        t = schema.transfer_agent_history
        with db.get_engine().connect() as conn:
            return [tuple(r) for r in conn.execute(
                select(t.c.stock_id, t.c.first_seen, t.c.last_seen, t.c.broker, t.c.agent_text)
                .order_by(t.c.stock_id, t.c.first_seen))]

    def test_source_defaults_to_weekly_opendata(self):
        self._run("2026-09-07", {"6217": "凱基證券股份有限公司"})
        with db.get_engine().connect() as conn:
            self.assertEqual(conn.execute(
                select(schema.transfer_agent_history.c.source)).scalar(), "opendata_weekly")

    def test_first_run_seeds_and_same_broker_only_extends(self):
        self.assertEqual(self._run("2026-09-07", {"6217": "凱基證券股份有限公司"}), [])
        # 同一家券商換個寫法 → 不算換股代
        self.assertEqual(self._run("2026-09-14", {"6217": "凱基證券(股)公司股務代理部"}), [])
        self.assertEqual(self._rows(), [
            ("6217", "2026-09-07", "2026-09-14", "凱基", "凱基證券(股)公司股務代理部"),
        ])

    def test_change_opens_a_new_period_and_is_reported(self):
        self._run("2026-09-07", {"6217": "凱基證券股份有限公司", "2330": "中國信託商業銀行代理部"})
        changes = self._run("2026-09-14", {"6217": "元大證券股務代理部",
                                           "2330": "中國信託商業銀行代理部"})
        self.assertEqual(changes, [{"stock_id": "6217", "from": "凱基", "to": "元大"}])
        self.assertEqual(self._rows(), [
            ("2330", "2026-09-07", "2026-09-14", None, "中國信託商業銀行代理部"),
            ("6217", "2026-09-07", "2026-09-07", "凱基", "凱基證券股份有限公司"),
            ("6217", "2026-09-14", "2026-09-14", "元大", "元大證券股務代理部"),
        ])
        # 元大這段再被觀察一次 → 是真的換了;之後換回凱基是新的一段,不改寫舊段
        self.assertEqual(self._run("2026-09-21", {"6217": "元大證券股務代理部"}), [])
        self.assertEqual(self._run("2026-09-28", {"6217": "凱基證券股份有限公司"}),
                         [{"stock_id": "6217", "from": "元大", "to": "凱基"}])
        self.assertEqual([(r[1], r[3]) for r in self._rows() if r[0] == "6217"],
                         [("2026-09-07", "凱基"), ("2026-09-14", "元大"), ("2026-09-28", "凱基")])

    def test_one_off_flip_flop_is_folded_back(self):
        """A→B→A 且 B 只出現在一次匯入:B 那段刪掉,A 延長,記成 reverted,不會有相鄰同券商。"""
        self._run("2026-09-07", {"6217": "凱基證券股份有限公司"})
        self._run("2026-09-14", {"6217": "凱基證券股份有限公司"})
        self._run("2026-09-21", {"6217": "元大證券股務代理部"})
        changes = self._run("2026-09-28", {"6217": "凱基證券(股)公司股務代理部"})
        self.assertEqual(changes, [{"stock_id": "6217", "from": "元大", "to": "凱基",
                                    "reverted": True}])
        self.assertEqual(self._rows(), [
            ("6217", "2026-09-07", "2026-09-28", "凱基", "凱基證券(股)公司股務代理部"),
        ])
        # 再跑一次照常延長,不再有變動
        self.assertEqual(self._run("2026-10-05", {"6217": "凱基證券股份有限公司"}), [])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        brokers = [r[3] for r in rows]
        self.assertTrue(all(a != b for a, b in zip(brokers, brokers[1:])))

    def test_export_collapses_adjacent_same_broker_periods(self):
        from radar.export.json_export import _agent_payload
        agent = _agent_payload({"凱基", "元大證券"}, None, [
            ("2026-09-07", "凱基"), ("2026-09-14", "凱基"), ("2026-09-21", "元大"),
        ])
        self.assertEqual(agent["periods"], [
            {"from": "2026-09-07", "to": "2026-09-21", "broker": "凱基", "names": ["凱基"]},
            {"from": "2026-09-21", "to": None, "broker": "元大", "names": ["元大證券"]},
        ])

    def test_same_day_rerun_overwrites_instead_of_zero_length_period(self):
        self._run("2026-09-07", {"6217": "凱基證券股份有限公司"})
        self._run("2026-09-07", {"6217": "元大證券股務代理部"})
        self.assertEqual(self._rows(), [
            ("6217", "2026-09-07", "2026-09-07", "元大", "元大證券股務代理部"),
        ])

    def test_missing_company_keeps_its_history(self):
        self._run("2026-09-07", {"6217": "凱基證券股份有限公司"})
        self._run("2026-09-14", {"2330": "中國信託商業銀行代理部"})
        self.assertIn(("6217", "2026-09-07", "2026-09-07", "凱基", "凱基證券股份有限公司"),
                      self._rows())


if __name__ == "__main__":
    unittest.main()
