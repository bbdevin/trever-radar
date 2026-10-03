"""docs/27 G1:地址抽取與分點名稱正規化(不發網路)。"""
import unittest
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar.geo import classify_broker_kind, normalize_branch_name, parse_city_district
from radar.import_geo import import_geo
from radar.schema import broker_branch_geo, company_profiles
from radar.providers import opendata


class ParseAddressTests(unittest.TestCase):
    def test_taipei_district(self):
        self.assertEqual(parse_city_district("台北市信義區松仁路"), ("台北市", "信義區"))

    def test_tai_variant(self):
        self.assertEqual(parse_city_district("臺北市大安區"), ("台北市", "大安區"))

    def test_kaohsiung(self):
        self.assertEqual(parse_city_district("高雄市左營區"), ("高雄市", "左營區"))

    def test_hsinchu_science_park(self):
        self.assertEqual(parse_city_district("新竹科學園區力行六路8號"), ("新竹市", None))

    def test_park_with_explicit_other_county_uses_written_county(self):
        cases = {
            "新竹科學園區新竹縣寶山鄉創新一路18號1樓": ("新竹縣", "寶山鄉"),
            "新竹科學園區苗栗縣銅鑼鄉九湖村銅科二路8號": ("苗栗縣", "銅鑼鄉"),
            "350新竹科學工業園區苗栗縣竹南鎮科北二路8號": ("苗栗縣", "竹南鎮"),
            "中部科學園區雲林縣虎尾鎮科虎一路8號": ("雲林縣", "虎尾鎮"),
            "744094南部科學園區台南市新市區南科六路1號": ("台南市", "新市區"),
        }
        for addr, want in cases.items():
            with self.subTest(addr=addr):
                self.assertEqual(parse_city_district(addr), want)

    def test_house_number_after_city_is_not_postal(self):
        self.assertEqual(parse_city_district("台北市104號"), ("台北市", None))

    def test_unparseable_is_none(self):
        self.assertEqual(parse_city_district("力行六路8號"), (None, None))

    def _check(self, cases):
        for addr, expected in cases:
            with self.subTest(addr=addr):
                self.assertEqual(parse_city_district(addr), expected)

    def test_postal_prefix(self):
        self._check([
            ("71001台南市永康區中正路301號", ("台南市", "永康區")),
            ("(104)台北市中山區松江路111號12樓", ("台北市", "中山區")),
            ("320 桃園市中壢區中正路1號", ("桃園市", "中壢區")),
            ("(806011)高雄市前鎮區成功二路1號", ("高雄市", "前鎮區")),
            ("（235）新北市中和區建一路166號", ("新北市", "中和區")),
        ])

    def test_variant_shi_char(self):
        self._check([
            ("(235)新北巿中和區建一路166號3樓", ("新北市", "中和區")),  # 4967 十銓
            ("高雄巿前金區中正四路170號", ("高雄市", "前金區")),
            ("新北巿新店區中正路190號8樓", ("新北市", "新店區")),
        ])

    def test_county_seat_without_county(self):
        self._check([
            ("彰化市中山路3段359號", ("彰化縣", "彰化市")),
            ("南投市中興路1號", ("南投縣", "南投市")),
            ("苗栗市中正路1號", ("苗栗縣", "苗栗市")),
            ("屏東市自由路1號", ("屏東縣", "屏東市")),
            ("宜蘭市中山路1號", ("宜蘭縣", "宜蘭市")),
            ("臺東市中華路1號", ("台東縣", "台東市")),
            ("花蓮市中正路1號", ("花蓮縣", "花蓮市")),
            ("斗六市雲林路1號", ("雲林縣", "斗六市")),
            ("太保市祥和一路1號", ("嘉義縣", "太保市")),
            ("朴子市開元路1號", ("嘉義縣", "朴子市")),
            ("竹北市光明六路1號", ("新竹縣", "竹北市")),
            ("頭份市中華路1號", ("苗栗縣", "頭份市")),
            ("員林市中山路1號", ("彰化縣", "員林市")),
        ])

    def test_provincial_cities_not_remapped(self):
        self._check([
            ("新竹市東區光復路1號", ("新竹市", "東區")),
            ("嘉義市西區中山路1號", ("嘉義市", "西區")),
            ("基隆市仁愛區仁一路1號", ("基隆市", "仁愛區")),
        ])

    def test_old_counties(self):
        self._check([
            ("台北縣板橋市文化路一段1號", ("新北市", "板橋區")),
            ("台中縣沙鹿鎮中山路1號", ("台中市", "沙鹿區")),
            ("台南縣麻豆鎮興中路1號", ("台南市", "麻豆區")),
            ("高雄縣岡山鎮岡山路1號", ("高雄市", "岡山區")),
            ("桃園縣中壢市中正路1號", ("桃園市", "中壢區")),
            ("台中縣烏日鄉中山路1號", ("台中市", "烏日區")),
            ("臺南縣新市鄉中山路1號", ("台南市", "新市區")),
        ])

    def test_abbreviations_and_country_prefix(self):
        self._check([
            ("北市南京東路二段1號", ("台北市", None)),
            ("南市東區中華東路1號", ("台南市", "東區")),
            ("新北市板橋區文化路1號", ("新北市", "板橋區")),
            ("臺灣雲林縣斗六市雲林路1號", ("雲林縣", "斗六市")),
            ("台灣台北市大安區敦化南路1號", ("台北市", "大安區")),
            ("中華民國台灣台北市內湖區新明路138號7樓", ("台北市", "內湖區")),
        ])

    def test_postal_after_city(self):
        self._check([
            ("台北市104中山區長安東路一段23號5樓之6", ("台北市", "中山區")),
            ("台北市114民權東路六段160號11樓", ("台北市", "內湖區")),
        ])

    def test_dual_north_postal_fills_district(self):
        self._check([
            ("104台北市松江路162號11樓", ("台北市", "中山區")),
            ("(220)新北市文化路一段1號", ("新北市", "板橋區")),
            ("台北市延平南路八十一號", ("台北市", None)),
            # 郵遞區號屬台北但地址是新北:不補區
            ("104新北市文化路一段1號", ("新北市", None)),
            # 文字已有區,以文字為準
            ("104台北市大安區敦化南路1號", ("台北市", "大安區")),
        ])

    def test_foreign_and_placeholders_stay_none(self):
        self._check([
            ("Floor 4, Willow House, Cricket Square, Grand Cayman", (None, None)),
            ("100 Pine Street, San Francisco", (None, None)),
            ("免設營業廳", (None, None)),
            ("同上", (None, None)),
            ("無", (None, None)),
            ("板橋區民生路一段一號", (None, None)),
        ])


class NameTests(unittest.TestCase):
    def test_strips_spaces_and_tai(self):
        self.assertEqual(normalize_branch_name("合庫- 台中"), "合庫-台中")
        self.assertEqual(normalize_branch_name("合庫-臺中"), "合庫-台中")

    def test_hq_without_hyphen(self):
        self.assertEqual(classify_broker_kind("元大"), "hq")

    def test_foreign(self):
        self.assertEqual(classify_broker_kind("美林"), "foreign")
        self.assertEqual(classify_broker_kind("摩根士丹利-台北"), "foreign")

    def test_branch(self):
        self.assertEqual(classify_broker_kind("玉山-左營"), "branch")

    def test_explicit_hq(self):
        self.assertEqual(classify_broker_kind("玉山-左營", is_hq=True), "hq")


class OfficialCompanyProviderTests(unittest.TestCase):
    def test_listed_company_maps_official_fields_and_roc_date(self):
        rows = [{
            "公司代號": "1605", "住址": " 台北市中山區 ", "產業別": "01",
            "股票過戶機構": "華南永昌", "過戶電話": "02-1234", "過戶地址": "台北市信義區",
            "出表日期": "1150826",
        }]
        with patch("radar.providers.opendata.get_json", return_value=rows):
            result = opendata.fetch_listed_companies()
        self.assertEqual(result, [{
            "stock_id": "1605", "address": "台北市中山區", "industry_code": "01",
            "transfer_agent": "華南永昌", "transfer_agent_phone": "02-1234",
            "transfer_agent_address": "台北市信義區", "market": "twse",
            "source": opendata.TWSE_COMPANY, "source_updated_at": "2026-08-26",
        }])

    def test_otc_company_reads_chinese_address_from_mops_csv(self):
        # TPEx OpenAPI 的 Address 是英文通訊地址;上櫃改讀 MOPS CSV 的中文「住址」
        text = (
            "﻿出表日期,公司代號,公司名稱,住址,產業別,股票過戶機構,過戶電話,過戶地址,英文通訊地址\n"
            '1151003,1240,茂生農經,台北市和平西路一段三十號二樓, 33 ,,  ,,"2F.,No.30,Sec. 1,Heping W.Rd.,Taipei"\n'
            ",,空代號列,,,,,,\n"
        )
        with patch("radar.providers.opendata.get_text", return_value=text) as get_text:
            result = opendata.fetch_otc_companies()
        self.assertEqual(get_text.call_args.args[0], opendata.TPEX_COMPANY)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["stock_id"], "1240")
        self.assertEqual(result[0]["address"], "台北市和平西路一段三十號二樓")
        self.assertEqual(result[0]["market"], "tpex")
        self.assertEqual(result[0]["industry_code"], "33")
        self.assertIsNone(result[0]["transfer_agent"])
        self.assertIsNone(result[0]["transfer_agent_phone"])
        self.assertIsNone(result[0]["transfer_agent_address"])
        self.assertEqual(result[0]["source_updated_at"], "2026-10-03")

    def test_otc_company_rejects_payload_without_chinese_address(self):
        with patch("radar.providers.opendata.get_text", return_value="SecuritiesCompanyCode,Address\n1240,x\n"):
            with self.assertRaises(RuntimeError):
                opendata.fetch_otc_companies()


class ImportGeoTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old_url, self._old_dir = config.DB_URL, config.DATA_DIR
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def test_import_writes_profiles_and_exclude_set(self):
        listed = [{"stock_id": "2330", "address": "新竹科學園區力行六路8號", "market": "twse",
                   "industry_code": "24", "transfer_agent": "測試股務", "transfer_agent_phone": "02-123",
                   "transfer_agent_address": "台北市", "source": "https://official.example/twse",
                   "source_updated_at": "2026-08-26"}]
        otc = [{"stock_id": "3105", "address": "高雄市左營區", "market": "tpex"}]
        hqs = [{"broker_id": "9200", "branch_name": "凱基", "address": "台北市"}]
        branches = [
            {"broker_id": "9A00", "branch_name": "玉山- 左營", "address": "高雄市左營區"},
            {"broker_id": "9200", "branch_name": "凱基", "address": "台北市"},
        ]
        with patch("radar.providers.opendata.fetch_listed_companies", return_value=listed), \
             patch("radar.providers.opendata.fetch_otc_companies", return_value=otc), \
             patch("radar.providers.opendata.fetch_broker_hq", return_value=hqs), \
             patch("radar.providers.opendata.fetch_broker_branches", return_value=branches):
            info = import_geo()
        self.assertEqual(info["companies"], 2)
        self.assertEqual(info["city_ok"], 2)

        eng = db.get_engine()
        with eng.connect() as conn:
            c2330 = conn.execute(
                company_profiles.select().where(company_profiles.c.stock_id == "2330")
            ).mappings().one()
            self.assertEqual(c2330["city"], "新竹市")
            self.assertIsNone(c2330["district"])
            self.assertEqual(c2330["industry_code"], "24")
            self.assertEqual(c2330["transfer_agent"], "測試股務")
            self.assertEqual(c2330["source_updated_at"], "2026-08-26")
            c3105 = conn.execute(
                company_profiles.select().where(company_profiles.c.stock_id == "3105")
            ).mappings().one()
            self.assertEqual((c3105["city"], c3105["district"]), ("高雄市", "左營區"))

            yushan = conn.execute(
                broker_branch_geo.select().where(broker_branch_geo.c.name_key == "玉山-左營")
            ).mappings().one()
            self.assertEqual(yushan["kind"], "branch")
            self.assertEqual(yushan["city"], "高雄市")

            kgi = conn.execute(
                broker_branch_geo.select().where(broker_branch_geo.c.name_key == "凱基")
            ).mappings().one()
            self.assertEqual(kgi["kind"], "hq")


class CompanyProfileMigrationTests(unittest.TestCase):
    def test_existing_sqlite_profile_table_gets_additive_columns(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "legacy.db"
            raw = sqlite3.connect(db_path)
            raw.execute("""CREATE TABLE company_profiles (
                stock_id TEXT PRIMARY KEY, address TEXT, city TEXT, district TEXT,
                market TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            raw.execute(
                "INSERT INTO company_profiles VALUES (?, ?, ?, ?, ?, ?)",
                ("1605", "既有地址", "台北市", None, "twse", "2026-08-01T00:00:00"),
            )
            raw.commit()
            raw.close()
            old_url, old_dir = config.DB_URL, config.DATA_DIR
            try:
                config.DATA_DIR = Path(tmp)
                config.DB_URL = "sqlite:///" + db_path.as_posix()
                db._engine = None
                db.init_db()
                with db.get_engine().connect() as conn:
                    cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(company_profiles)")}
                    existing = conn.exec_driver_sql(
                        "SELECT stock_id, address, city, market, updated_at FROM company_profiles"
                    ).one()
                self.assertTrue({
                    "industry_code", "transfer_agent", "transfer_agent_phone",
                    "transfer_agent_address", "source", "source_updated_at",
                }.issubset(cols))
                self.assertEqual(existing, ("1605", "既有地址", "台北市", "twse", "2026-08-01T00:00:00"))
            finally:
                if db._engine is not None:
                    db._engine.dispose()
                db._engine = None
                config.DB_URL, config.DATA_DIR = old_url, old_dir


if __name__ == "__main__":
    unittest.main()
