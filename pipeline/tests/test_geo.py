"""docs/27 G1:地址抽取與分點名稱正規化(不發網路)。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar.geo import classify_broker_kind, normalize_branch_name, parse_city_district
from radar.import_geo import import_geo
from radar.schema import broker_branch_geo, company_profiles


class ParseAddressTests(unittest.TestCase):
    def test_taipei_district(self):
        self.assertEqual(parse_city_district("台北市信義區松仁路"), ("台北市", "信義區"))

    def test_tai_variant(self):
        self.assertEqual(parse_city_district("臺北市大安區"), ("台北市", "大安區"))

    def test_kaohsiung(self):
        self.assertEqual(parse_city_district("高雄市左營區"), ("高雄市", "左營區"))

    def test_hsinchu_science_park(self):
        self.assertEqual(parse_city_district("新竹科學園區力行六路8號"), ("新竹市", None))

    def test_unparseable_is_none(self):
        self.assertEqual(parse_city_district("力行六路8號"), (None, None))


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
        listed = [{"stock_id": "2330", "address": "新竹科學園區力行六路8號", "market": "twse"}]
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


if __name__ == "__main__":
    unittest.main()
