# -*- coding: utf-8 -*-
"""db.upsert() / db.insert_many() 語意(docs/44 D-P0.5 改成 driver executemany 後鎖住)。

- 只更新 row dict 裡有的欄;沒帶的欄保留舊值
- 衝突列只改提供的欄
- 同一批 row 的 key set 不同也要能寫,且依原順序(後面同 PK 的列勝出)
- 回傳寫入列數;Boolean 綁定轉 0/1;Python 端 scalar default 照舊補上
- WAL 連線 synchronous=NORMAL
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, Table, Text,
                        create_engine)
from sqlalchemy.exc import IntegrityError

import radar.config as config
import radar.db as db

meta = MetaData()
T = Table(
    "t", meta,
    Column("k1", Text, primary_key=True),
    Column("k2", Integer, primary_key=True),
    Column("a", Float),
    Column("b", Text),
    Column("flag", Boolean),
    Column("n", Integer, nullable=False, default=7),
)


class UpsertSemanticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.engine = create_engine("sqlite:///" + str(Path(self.tmp.name) / "t.db"))
        meta.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def rows(self):
        with self.engine.connect() as c:
            return [tuple(r) for r in c.exec_driver_sql(
                "SELECT k1, k2, a, b, flag, n FROM t ORDER BY k1, k2")]

    def test_empty_returns_zero(self):
        with self.engine.begin() as c:
            self.assertEqual(db.upsert(c, T, []), 0)

    def test_insert_and_return_count_across_chunks(self):
        data = [{"k1": "x", "k2": i, "a": i / 2, "b": str(i)} for i in range(25)]
        with self.engine.begin() as c:
            self.assertEqual(db.upsert(c, T, data, chunk=4), 25)
        got = self.rows()
        self.assertEqual(len(got), 25)
        self.assertEqual(got[3], ("x", 3, 1.5, "3", None, 7))  # default n=7 filled

    def test_conflict_updates_only_provided_columns(self):
        with self.engine.begin() as c:
            db.upsert(c, T, [{"k1": "x", "k2": 1, "a": 1.0, "b": "old", "flag": True, "n": 3}])
            n = db.upsert(c, T, [{"k1": "x", "k2": 1, "a": 2.0}])
        self.assertEqual(n, 1)
        # b/flag/n keep their values; n is NOT reset to its default on update
        self.assertEqual(self.rows(), [("x", 1, 2.0, "old", 1, 3)])

    def test_pk_only_rows_do_nothing_on_conflict(self):
        with self.engine.begin() as c:
            db.upsert(c, T, [{"k1": "x", "k2": 1, "b": "keep"}])
            self.assertEqual(db.upsert(c, T, [{"k1": "x", "k2": 1}, {"k1": "y", "k2": 1}]), 2)
        self.assertEqual(self.rows(), [("x", 1, None, "keep", None, 7),
                                       ("y", 1, None, None, None, 7)])

    def test_heterogeneous_key_sets_in_one_call(self):
        with self.engine.begin() as c:
            db.upsert(c, T, [{"k1": "x", "k2": 1, "a": 1.0, "b": "b0"}])
            n = db.upsert(c, T, [
                {"k1": "x", "k2": 1, "b": "b1"},               # only b
                {"k2": 1, "k1": "x", "a": 5.0},                 # only a (other key order)
                {"k1": "y", "k2": 2, "a": 9.0, "b": "new", "flag": False},
                {"k1": "x", "k2": 1, "b": "b2"},               # later row wins
                {"b": "z", "k2": 3, "k1": "z"},                 # same set as row 1, reordered
            ])
        self.assertEqual(n, 5)
        self.assertEqual(self.rows(), [
            ("x", 1, 5.0, "b2", None, 7),
            ("y", 2, 9.0, "new", 0, 7),
            ("z", 3, None, "z", None, 7),
        ])

    def test_duplicate_pk_within_batch_last_wins(self):
        with self.engine.begin() as c:
            db.upsert(c, T, [{"k1": "x", "k2": 1, "a": 1.0}, {"k1": "x", "k2": 1, "a": 2.0}])
        self.assertEqual(self.rows(), [("x", 1, 2.0, None, None, 7)])

    def test_unknown_column_raises(self):
        with self.engine.begin() as c, self.assertRaises(ValueError):
            db.upsert(c, T, [{"k1": "x", "k2": 1, "nope": 1}])

    def test_insert_many_plain_insert(self):
        with self.engine.begin() as c:
            self.assertEqual(db.insert_many(c, T, [{"k1": "x", "k2": 1, "flag": True}]), 1)
        self.assertEqual(self.rows(), [("x", 1, None, None, 1, 7)])
        with self.assertRaises(IntegrityError), self.engine.begin() as c:
            db.insert_many(c, T, [{"k1": "x", "k2": 1}])

    def test_rollback_with_caller_transaction(self):
        with self.assertRaises(RuntimeError), self.engine.begin() as c:
            db.upsert(c, T, [{"k1": "x", "k2": 1}])
            raise RuntimeError
        self.assertEqual(self.rows(), [])


class WalSynchronousTest(unittest.TestCase):
    def test_wal_connections_use_synchronous_normal(self):
        with TemporaryDirectory() as tmp:
            old = (config.DB_URL, config.DATA_DIR, db._engine)
            config.DB_URL = "sqlite:///" + (Path(tmp) / "radar.db").as_posix()
            config.DATA_DIR = Path(tmp)
            db._engine = None
            try:
                db.init_db()
                db.get_engine().dispose()          # fresh connections see the WAL file
                with db.get_engine().connect() as c:
                    self.assertEqual(c.exec_driver_sql("PRAGMA journal_mode").scalar(), "wal")
                    self.assertEqual(c.exec_driver_sql("PRAGMA synchronous").scalar(), 1)
                    self.assertEqual(c.exec_driver_sql("PRAGMA cache_size").scalar(), -65536)
                    self.assertEqual(c.exec_driver_sql("PRAGMA temp_store").scalar(), 0)
            finally:
                if db._engine is not None:
                    db._engine.dispose()
                config.DB_URL, config.DATA_DIR, db._engine = old


if __name__ == "__main__":
    unittest.main()
