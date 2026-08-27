import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import radar.config as config
import radar.db as db
from radar import schema
from radar.company_groups import load_company_groups, validate_company_groups
from radar.export.json_export import export_json


class CompanyGroupMappingTests(unittest.TestCase):
    def test_validator_rejects_unknown_stock_and_accepts_null_dates(self):
        mapping = {
            "group_id": "verified", "group_name": "已驗證集團", "stock_id": "1605",
            "effective_from": None, "effective_to": None, "source": "https://example.com/source",
            "source_updated_at": None, "observed_at": "2026-08-27",
        }
        validate_company_groups([mapping], {"1605"})
        with self.assertRaisesRegex(ValueError, "unknown stock_id"):
            validate_company_groups([mapping], {"9999"})

    def test_validator_rejects_invalid_date_range(self):
        mapping = {
            "group_id": "verified", "group_name": "已驗證集團", "stock_id": "1605",
            "effective_from": "2026-09-01", "effective_to": "2026-08-31",
            "source": "https://example.com/source", "source_updated_at": None, "observed_at": "2026-08-27",
        }
        with self.assertRaisesRegex(ValueError, "invalid effective range"):
            validate_company_groups([mapping], {"1605"})

    def test_validator_rejects_invalid_duplicate_and_inconsistent_entries(self):
        mapping = {
            "group_id": "verified", "group_name": "已驗證集團", "stock_id": "1605",
            "effective_from": None, "effective_to": None, "source": "https://example.com/source",
            "source_updated_at": None, "observed_at": "2026-08-27",
        }
        with self.assertRaisesRegex(ValueError, "4-6 digit"):
            validate_company_groups([{**mapping, "stock_id": "1605000"}], {"1605000"}, allow_missing_stocks=True)
        validate_company_groups([{**mapping, "stock_id": "123456"}], {"123456"})
        with self.assertRaisesRegex(ValueError, "duplicates"):
            validate_company_groups([mapping, mapping.copy()], {"1605"})
        with self.assertRaisesRegex(ValueError, "observed_at must be a non-null"):
            validate_company_groups([{**mapping, "observed_at": None}], {"1605"})
        inconsistent = {**mapping, "stock_id": "2344", "source": "https://example.com/other"}
        with self.assertRaisesRegex(ValueError, "metadata must be consistent"):
            validate_company_groups([mapping, inconsistent], {"1605", "2344"})


class CompanyGroupExportTests(unittest.TestCase):
    DATES = ("2026-08-26", "2026-08-27")
    IDS = ("1605", "2344", "2492", "5469", "6116")

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
                {"id": sid, "name": f"公司{sid}", "market": "twse", "type": "stock", "industry": "測試業", "is_active": 1}
                for sid in self.IDS
            ])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": sid, "date": day, "close": 50 + i + j, "volume": 1000,
                 "turnover": 0 if day == self.DATES[-1] else 100}
                for i, sid in enumerate(self.IDS) for j, day in enumerate(self.DATES)
            ])
            conn.execute(schema.company_profiles.insert(), [{
                "stock_id": "1605", "address": "台北市", "city": "台北市", "district": None,
                "market": "twse", "industry_code": "01", "transfer_agent": "測試股務",
                "transfer_agent_phone": None, "transfer_agent_address": None,
                "source": "https://official.example", "source_updated_at": "2026-08-26", "updated_at": "2026-08-27T00:00:00",
            }])

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old_url, self._old_dir
        self._tmp.cleanup()

    def test_export_uses_all_mapping_members_not_radar_pool(self):
        out = Path(self._tmp.name) / "out"
        export_json(out)
        groups = json.loads((out / "groups.json").read_text(encoding="utf-8"))
        self.assertEqual(groups["version"], 1)
        self.assertEqual(groups["data_date"], "2026-08-27")
        group = groups["groups"][0]
        self.assertEqual(group["id"], "walsin")
        self.assertEqual([member["id"] for member in group["members"]], list(self.IDS))
        self.assertTrue(all(member["quote_date"] == "2026-08-27" for member in group["members"]))
        # No daily score exists, so no member can have arrived via the radar pool.
        radar = json.loads((out / "radar.json").read_text(encoding="utf-8"))
        self.assertEqual(radar["lists"]["score"], [])
        stock = json.loads((out / "stocks" / "1605.json").read_text(encoding="utf-8"))
        self.assertEqual(stock["industry"], "測試業")
        self.assertEqual(stock["company_profile"]["transfer_agent"], "測試股務")
        self.assertEqual(stock["company_groups"][0]["id"], "walsin")

    def _mappings(self):
        return json.loads(json.dumps(load_company_groups()))

    def test_as_of_before_observation_omits_group(self):
        mappings = self._mappings()
        for mapping in mappings:
            mapping["observed_at"] = "2026-08-28"
        out = Path(self._tmp.name) / "out-before-observed"
        with patch("radar.export.json_export.load_company_groups", return_value=mappings):
            export_json(out)
        groups = json.loads((out / "groups.json").read_text(encoding="utf-8"))
        self.assertEqual(groups["groups"], [])

    def test_expired_member_is_not_exported_as_current(self):
        mappings = self._mappings()
        next(mapping for mapping in mappings if mapping["stock_id"] == "6116")["effective_to"] = "2026-08-26"
        out = Path(self._tmp.name) / "out-expired"
        with patch("radar.export.json_export.load_company_groups", return_value=mappings):
            export_json(out)
        groups = json.loads((out / "groups.json").read_text(encoding="utf-8"))
        self.assertEqual([member["id"] for member in groups["groups"][0]["members"]], list(self.IDS[:-1]))
        stock = json.loads((out / "stocks" / "6116.json").read_text(encoding="utf-8"))
        self.assertEqual(stock["company_groups"], [])

    def test_partial_stock_master_omits_whole_group(self):
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.delete().where(schema.stocks.c.id == "6116"))
        out = Path(self._tmp.name) / "out-partial"
        export_json(out)
        groups = json.loads((out / "groups.json").read_text(encoding="utf-8"))
        self.assertEqual(groups["groups"], [])
        stock = json.loads((out / "stocks" / "1605.json").read_text(encoding="utf-8"))
        self.assertEqual(stock["company_groups"], [])


if __name__ == "__main__":
    unittest.main()
