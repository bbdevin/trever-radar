"""全站分點追蹤名單同步(seed_branches.sync_tracked_branches,2026-10-03)。

釘住的契約:
  * track → manual(既有 manual 保留 added_at);mute → source='muted';名單上沒有 → 中立
    (manual／muted 列移除,auto 不動)。
  * 抓取／驗證任何失敗 → DB 一列都不變、不 raise、CLI 以 0 結束;從未同步過才退回寫死名單。
  * 只送 publishable／anon key;service_role／sb_secret_ 一律拒絕且不發請求;log 永不含金鑰。
  * 消費端(pocket tracked_keys、個股 branch_tags.tracked、rankings.json／track index 的
    manual 出處、today.json、自動入選)都把 muted 當成不在名單上。
"""
import base64
import contextlib
import io
import json
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests
from sqlalchemy import text

import radar.config as config
import radar.db as db
from radar import schema
from radar import seed_branches as sb

SENTINEL_KEY = "sb_publishable_SENTINEL_do_not_log_123"
NOW_OLD = "2026-01-01T00:00:00"


def _jwt(payload: dict) -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg(payload)}.signature"


class _FakeResp:
    def __init__(self, status=200, body=b"[]", chunks=None, raise_on_read=None):
        self.status_code = status
        self._chunks = chunks if chunks is not None else [body]
        self._raise = raise_on_read
        self.closed = False

    def iter_content(self, chunk_size=1):
        if self._raise:
            raise self._raise
        yield from self._chunks

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if self.exc:
            raise self.exc
        return self.resp

    def close(self):
        pass


def _ok(rows) -> _FakeSession:
    return _FakeSession(_FakeResp(body=json.dumps(rows, ensure_ascii=False).encode("utf-8")))


class _DB(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._old = (config.DB_URL, config.DATA_DIR)
        config.DATA_DIR = tmp
        config.DB_URL = "sqlite:///" + (tmp / "t.db").as_posix()
        db._engine = None
        db.init_db()
        env = patch.dict(os.environ, {sb.ENV_KEY: SENTINEL_KEY})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(sb.ENV_URL, None)

    def tearDown(self):
        if db._engine is not None:
            db._engine.dispose()
        db._engine = None
        config.DB_URL, config.DATA_DIR = self._old
        self._tmp.cleanup()

    def _insert_tracked(self, rows):
        with db.get_engine().begin() as conn:
            conn.execute(schema.tracked_branches.insert(), rows)

    def _tracked(self):
        with db.get_engine().connect() as conn:
            return {r[0]: (r[1], r[2], r[3]) for r in conn.execute(text(
                "SELECT branch_name, source, note, added_at FROM tracked_branches"))}

    def _sync(self, session):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = sb.sync_tracked_branches(fetch=lambda: sb.fetch_track_list(session=session))
        return result, out.getvalue()


class ApplyTests(_DB):
    def test_track_mute_and_neutral_are_mirrored(self):
        self._insert_tracked([
            {"branch_name": "甲", "source": "manual", "note": "seed", "added_at": NOW_OLD},
            {"branch_name": "乙", "source": "auto", "note": "auto", "added_at": NOW_OLD},
            {"branch_name": "丙", "source": "manual", "note": "seed", "added_at": NOW_OLD},
            {"branch_name": "丁", "source": "auto", "note": "auto", "added_at": NOW_OLD},
            {"branch_name": "戊", "source": "muted", "note": "m", "added_at": NOW_OLD},
            {"branch_name": "己", "source": "manual", "note": "seed", "added_at": NOW_OLD},
            {"branch_name": "庚", "source": "auto", "note": "auto", "added_at": NOW_OLD},
        ])
        result, log = self._sync(_ok([
            {"branch_name": "甲", "state": "track"},
            {"branch_name": "乙", "state": "track"},
            {"branch_name": "丙", "state": "mute"},
            {"branch_name": "丁", "state": "mute"},
            {"branch_name": "辛", "state": "track"},
        ]))
        self.assertEqual(result, "ok")
        t = self._tracked()
        self.assertEqual(t["甲"], ("manual", "seed", NOW_OLD), "既有 manual 不動,保留 added_at")
        self.assertEqual(t["乙"][0], "manual")
        self.assertNotEqual(t["乙"][2], NOW_OLD, "auto → manual 從現在起算")
        self.assertEqual(t["丙"][0], "muted")
        self.assertEqual(t["丁"][0], "muted")
        self.assertEqual(t["辛"][0], "manual")
        self.assertNotIn("戊", t, "名單上沒有 → 解除 muted(中立)")
        self.assertNotIn("己", t, "名單上沒有 → manual 移除(中立)")
        self.assertEqual(t["庚"][0], "auto", "auto 列交給演算法,不因名單同步而動")
        self.assertIn("track=3 mute=2", log)

    def test_sync_is_idempotent(self):
        rows = [{"branch_name": "甲", "state": "track"}, {"branch_name": "乙", "state": "mute"}]
        self._sync(_ok(rows))
        first = self._tracked()
        self._sync(_ok(rows))
        self.assertEqual(self._tracked(), first)

    def test_names_are_canonicalised_and_mute_wins_on_alias_conflict(self):
        result, _ = self._sync(_ok([
            {"branch_name": "台新-營業部", "state": "track"},
            {"branch_name": "台新", "state": "mute"},
            {"branch_name": "(牛牛牛)亞證券", "state": "track"},
        ]))
        self.assertEqual(result, "ok")
        t = self._tracked()
        self.assertEqual(t["台新"][0], "muted")
        self.assertNotIn("台新-營業部", t)
        self.assertEqual(t["犇亞證券"][0], "manual")

    def test_request_shape_is_least_privilege(self):
        session = _ok([])
        sb.fetch_track_list(session=session)
        url, kw = session.calls[0]
        self.assertEqual(url, sb.DEFAULT_SUPABASE_URL + sb.RPC_PATH)
        self.assertEqual(kw["headers"]["apikey"], SENTINEL_KEY)
        self.assertNotIn("Authorization", kw["headers"])
        self.assertFalse(kw["allow_redirects"])
        self.assertEqual(kw["timeout"], sb.FETCH_TIMEOUT)


class FailureLeavesDbUntouchedTests(_DB):
    SEEDED = [
        {"branch_name": "甲", "source": "manual", "note": "seed", "added_at": NOW_OLD},
        {"branch_name": "乙", "source": "muted", "note": "m", "added_at": NOW_OLD},
        {"branch_name": "丙", "source": "auto", "note": "auto", "added_at": NOW_OLD},
    ]

    def setUp(self):
        super().setUp()
        self._insert_tracked(self.SEEDED)
        self.before = self._tracked()

    def _assert_kept(self, session):
        result, log = self._sync(session)
        self.assertEqual(result, "kept")
        self.assertEqual(self._tracked(), self.before)
        self.assertTrue(log.startswith("WARN branch-track-sync: fetch failed"), log)
        self.assertNotIn(SENTINEL_KEY, log)
        return log

    def test_connection_error(self):
        log = self._assert_kept(_FakeSession(exc=requests.ConnectionError(
            f"boom while sending apikey={SENTINEL_KEY}")))
        self.assertIn("ConnectionError", log)

    def test_timeout(self):
        self._assert_kept(_FakeSession(exc=requests.Timeout("read timed out")))

    def test_http_error_status(self):
        for status in (401, 404, 500):
            log = self._assert_kept(_FakeSession(_FakeResp(status=status, body=b'{"hint":"x"}')))
            self.assertIn(f"HTTP {status}", log)

    def test_redirect_is_not_followed(self):
        self._assert_kept(_FakeSession(_FakeResp(status=302)))

    def test_read_error_mid_body(self):
        self._assert_kept(_FakeSession(_FakeResp(raise_on_read=requests.ConnectionError("reset"))))

    def test_invalid_json_and_shapes(self):
        for body in (b"not json", b'{"a":1}', b"\xff\xfe",
                     json.dumps([{"branch_name": "甲", "state": "maybe"}]).encode(),
                     json.dumps([{"branch_name": " 甲", "state": "track"}]).encode(),
                     json.dumps([{"branch_name": "甲\n", "state": "track"}]).encode(),
                     json.dumps([{"branch_name": "甲\u0085", "state": "track"}]).encode(),
                     json.dumps([{"branch_name": "x" * 65, "state": "track"}]).encode(),
                     json.dumps([{"branch_name": "", "state": "track"}]).encode(),
                     json.dumps([{"branch_name": 5, "state": "track"}]).encode(),
                     json.dumps([["甲", "track"]]).encode()):
            self._assert_kept(_FakeSession(_FakeResp(body=body)))

    def test_one_bad_row_rejects_the_whole_batch(self):
        body = json.dumps([{"branch_name": "新分點", "state": "track"},
                           {"branch_name": "壞\x07", "state": "track"}]).encode()
        self._assert_kept(_FakeSession(_FakeResp(body=body)))

    def test_oversized_body(self):
        chunk = b" " * 65536
        self._assert_kept(_FakeSession(_FakeResp(chunks=[chunk] * 5)))

    def test_too_many_rows(self):
        rows = [{"branch_name": f"分點{i}", "state": "track"} for i in range(sb.MAX_ROWS + 1)]
        self._assert_kept(_ok(rows))

    def test_unexpected_exception_type(self):
        def boom():
            raise RuntimeError(SENTINEL_KEY)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = sb.sync_tracked_branches(fetch=boom)
        self.assertEqual(result, "kept")
        self.assertNotIn(SENTINEL_KEY, out.getvalue())
        self.assertEqual(self._tracked(), self.before)

    def test_empty_online_list_does_not_wipe_local_list(self):
        result, log = self._sync(_ok([]))
        self.assertEqual(result, "refused")
        self.assertEqual(self._tracked(), self.before)
        self.assertIn("WARN", log)

    def test_cli_exits_zero_on_failure(self):
        from radar import cli
        with patch.object(sb, "fetch_track_list",
                          side_effect=sb.TrackListError("HTTP 503")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["seed-branches"])  # 不 raise = 程序以 0 結束
        self.assertEqual(self._tracked(), self.before)
        self.assertIn("WARN branch-track-sync", out.getvalue())


class FallbackTests(_DB):
    def test_never_synced_and_fetch_fails_uses_builtin_seed(self):
        self._insert_tracked([{"branch_name": "自動", "source": "auto", "added_at": NOW_OLD}])
        result, log = self._sync(_FakeSession(exc=requests.ConnectionError("down")))
        self.assertEqual(result, "fallback")
        t = self._tracked()
        self.assertEqual({n for n, v in t.items() if v[0] == "manual"}, set(sb.SEED_BRANCHES))
        self.assertEqual(t["自動"][0], "auto")
        self.assertIn("fallback", log)

    def test_never_synced_and_empty_list_applies_nothing(self):
        result, _ = self._sync(_ok([]))
        self.assertEqual(result, "ok")
        self.assertEqual(self._tracked(), {})


class KeyGuardTests(_DB):
    def _rejected(self, key):
        session = _ok([{"branch_name": "甲", "state": "track"}])
        with patch.dict(os.environ, {sb.ENV_KEY: key}):
            result, log = self._sync(session)
        self.assertEqual(session.calls, [], "被拒的金鑰不得送出任何請求")
        self.assertNotIn(key, log)
        self.assertIn("rejected", log)
        return result

    def test_secret_key_is_refused(self):
        self.assertEqual(self._rejected("sb_secret_abcdef0123456789"), "fallback")

    def test_service_role_jwt_is_refused(self):
        self._rejected(_jwt({"role": "service_role", "iss": "supabase"}))

    def test_unknown_key_format_is_refused(self):
        self._rejected("some-random-token")

    def test_anon_jwt_and_publishable_are_accepted(self):
        self.assertTrue(sb._is_low_privilege_key(_jwt({"role": "anon"})))
        self.assertTrue(sb._is_low_privilege_key(sb.DEFAULT_SUPABASE_PUBLISHABLE_KEY))
        self.assertFalse(sb._is_low_privilege_key(_jwt({"role": "authenticated"})))

    def test_non_https_url_is_refused(self):
        session = _ok([])
        for url in ("http://example.supabase.co", "https://user:pw@x.supabase.co",
                    "https://x.supabase.co/evil?a=1", "ftp://x"):
            with patch.dict(os.environ, {sb.ENV_URL: url}):
                result, log = self._sync(session)
            self.assertIn("url rejected", log)
        self.assertEqual(session.calls, [])

    def test_success_log_has_no_key(self):
        _, log = self._sync(_ok([{"branch_name": "甲", "state": "track"}]))
        self.assertNotIn(SENTINEL_KEY, log)


class ConsumersExcludeMutedTests(_DB):
    """pocket、個股 branch_tags、rankings.json、track index、today.json 都不把 muted 當追蹤。"""

    D = "2026-08-05"

    def _seed_export_fixture(self):
        from radar.importer import upsert_branch_trades
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "2330", "name": "台積電", "market": "twse", "type": "stock", "is_active": 1}])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "2330", "date": d, "close": 100.0, "volume": 1_000_000, "turnover": 1}
                for d in ("2026-08-04", self.D)])
            upsert_branch_trades(conn, [
                {"stock_id": "2330", "date": self.D, "branch_key": k, "branch_name": n,
                 "buy_lots": 100, "sell_lots": 0, "net_lots": 100, "pct": 1.0}
                for k, n in (("a", "追蹤甲"), ("b", "靜音乙"), ("c", "高分靜音丙"), ("d", "曾手動丁"))
            ])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "追蹤甲", "source": "manual"},
                {"branch_name": "靜音乙", "source": "muted"},
                {"branch_name": "高分靜音丙", "source": "muted"},
            ])
            conn.execute(schema.branch_rankings.insert(), [
                # 快照寫 manual,但現在名單是 muted / 已不在名單 → 不得再標 manual。
                {"branch_name": "靜音乙", "as_of": self.D, "rank_score": 60, "samples": 10,
                 "is_daytrade": 0, "source": "manual"},
                {"branch_name": "高分靜音丙", "as_of": self.D, "rank_score": 95, "samples": 10,
                 "is_daytrade": 0, "source": "candidate"},
                {"branch_name": "曾手動丁", "as_of": self.D, "rank_score": 50, "samples": 10,
                 "is_daytrade": 0, "source": "manual"},
                # 快照時還是 candidate,之後才被管理員加入 → 匯出要標 manual。
                {"branch_name": "追蹤甲", "as_of": self.D, "rank_score": 40, "samples": 10,
                 "is_daytrade": 0, "source": "candidate"},
            ])

    def test_pocket_tracked_keys(self):
        from radar.geo import normalize_branch_name
        from radar.pocket import load_tracked_keys
        self._seed_export_fixture()
        with db.get_engine().connect() as conn:
            keys = load_tracked_keys(conn)
        self.assertIn(normalize_branch_name("追蹤甲"), keys)
        self.assertNotIn(normalize_branch_name("靜音乙"), keys)
        self.assertNotIn(normalize_branch_name("高分靜音丙"), keys,
                         "muted 連 rank_score ≥ 70 那半段都排除")

    def test_exports(self):
        from radar.export.json_export import export_json
        self._seed_export_fixture()
        out = Path(self._tmp.name) / "out"
        out.mkdir()
        with contextlib.redirect_stdout(io.StringIO()):
            export_json(out)

        stock = json.loads((out / "stocks" / "2330.json").read_text(encoding="utf-8"))
        self.assertEqual(stock["branch_tags"]["tracked"], ["追蹤甲"])

        rankings = json.loads((out / "branches" / "rankings.json").read_text(encoding="utf-8"))
        src = {r["branch_name"]: r["source"] for r in rankings["rankings"]}
        self.assertEqual(src, {"追蹤甲": "manual", "靜音乙": "candidate",
                               "高分靜音丙": "candidate", "曾手動丁": "candidate"})

        index = json.loads((out / "branches" / "track" / "index.json").read_text(encoding="utf-8"))
        isrc = {e["branch_name"]: e["source"] for e in index}
        self.assertEqual(isrc.get("追蹤甲"), "manual")
        self.assertNotIn("manual", {isrc.get(n) for n in ("靜音乙", "高分靜音丙", "曾手動丁")})
        self.assertNotIn("muted", set(isrc.values()))

        today = json.loads((out / "branches" / "today.json").read_text(encoding="utf-8"))
        self.assertEqual(set(today["movements"]), {"追蹤甲"})


class AutoSelectionSkipsMutedTests(_DB):
    def test_muted_branch_is_never_auto_selected(self):
        from radar.compute import compute_branch_stats as cbs

        days = [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(30)]
        qual = days[::3][:cbs.MIN_RANK_EVENTS + 1]
        with db.get_engine().begin() as conn:
            conn.execute(schema.stocks.insert(), [
                {"id": "1101", "name": "台泥", "market": "twse", "type": "stock"}])
            conn.execute(schema.daily_prices.insert(), [
                {"stock_id": "1101", "date": d, "open": 10, "close": 10, "volume": 1000}
                for d in days])
            conn.execute(schema.branch_dim.insert(), [
                {"id": 1, "branch_key": "a", "branch_name": "一般分點"},
                {"id": 2, "branch_key": "b", "branch_name": "靜音分點"},
            ])
            conn.execute(schema.branch_trades_raw.insert(), [
                {"stock_id": "1101", "date": d, "branch_id": bid, "buy_lots": 10, "sell_lots": 0,
                 "net_lots": 10, "pct": 2.0, "source": "fixture"}
                for d in qual for bid in (1, 2)])
            conn.execute(schema.tracked_branches.insert(), [
                {"branch_name": "靜音分點", "source": "muted", "added_at": NOW_OLD}])

        # 門檻壓到 0:兩個分點都夠格自動入選,差別只在 muted。
        with patch.multiple(cbs, AUTO_IN_EVENTS_2Y=0, AUTO_IN_SCORE=0, AUTO_IN_EVENTS_90=0), \
                contextlib.redirect_stdout(io.StringIO()):
            cbs.compute_all()

        t = self._tracked()
        self.assertEqual(t["一般分點"][0], "auto")
        self.assertEqual(t["靜音分點"][0], "muted")
        with db.get_engine().connect() as conn:
            rank_src = dict(conn.execute(text(
                "SELECT branch_name, source FROM branch_rankings")).fetchall())
        self.assertEqual(rank_src["靜音分點"], "candidate")
        self.assertEqual(rank_src["一般分點"], "auto")


if __name__ == "__main__":
    unittest.main()
