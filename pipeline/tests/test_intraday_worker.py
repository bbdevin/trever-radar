"""盤中 worker radar.json HTTP 抓取邏輯的輕量單元測試。

不真發網路請求(monkeypatch requests.get)、不真連 Fugle/Supabase。
匯入 intraday.worker 不應觸發 fatal exit(env 檢查與 supabase client 建立已移入 main())。
"""
import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
import requests

import intraday.worker as worker


def _radar_payload():
    return {
        "lists": {"armed": ["2330", "2454"]},
        "stocks": [
            {"id": "2330", "name": "台積電", "close": 1000,
             "tech": {"watch_price": 1050, "adv20": 50000}},
            {"id": "2454", "name": "聯發科", "close": 900,
             "tech": {"watch_price": 950, "adv20": 30000}},
            {"id": "9999", "name": "不在名單", "close": 10},
        ],
    }


class _DummyResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} error")


APPROVED_UID = "11111111-1111-1111-1111-111111111111"
PENDING_UID = "22222222-2222-2222-2222-222222222222"
REJECTED_UID = "33333333-3333-3333-3333-333333333333"


class _FakeQuery:
    """模擬 supabase-py 的 table().select().eq()/in_().execute() 鏈。

    apply_filters=False 模擬伺服端過濾失效(回傳全部列),用來驗證 worker 端二次過濾。
    """

    def __init__(self, fake, name):
        self._fake = fake
        self._name = name
        self._filters = []

    def select(self, cols):
        self._fake.calls.append((self._name, "select", cols))
        return self

    def eq(self, col, val):
        self._fake.calls.append((self._name, "eq", col, val))
        self._filters.append(lambda r: r.get(col) == val)
        return self

    def in_(self, col, vals):
        vals = list(vals)
        self._fake.calls.append((self._name, "in_", col, vals))
        self._filters.append(lambda r: r.get(col) in vals)
        return self

    def execute(self):
        err = self._fake.errors.get(self._name)
        if err:
            raise err
        rows = list(self._fake.tables.get(self._name, []))
        if self._fake.apply_filters:
            for f in self._filters:
                rows = [r for r in rows if f(r)]
        return MagicMock(data=rows)


class _FakeSupabase:
    def __init__(self, profiles=None, watchlist=None, errors=None, apply_filters=True):
        self.tables = {"app_profiles": profiles or [], "watchlist": watchlist or []}
        self.errors = errors or {}
        self.apply_filters = apply_filters
        self.calls = []

    def table(self, name):
        self.calls.append((name, "table"))
        return _FakeQuery(self, name)


def _profiles():
    return [
        {"user_id": APPROVED_UID, "status": "approved"},
        {"user_id": PENDING_UID, "status": "pending"},
        {"user_id": REJECTED_UID, "status": "rejected"},
    ]


def _approved_watchlist(*stock_ids):
    """單一已核准使用者的自選列。"""
    return _FakeSupabase(
        profiles=_profiles(),
        watchlist=[{"user_id": APPROVED_UID, "stock_id": s} for s in stock_ids],
    )


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """每個測試前清空模組全域狀態,並讓 time.sleep 變 no-op(避免退避真的睡)。"""
    worker.armed_stocks.clear()
    worker.sent_signals.clear()
    worker._subscribed_symbols.clear()
    worker.feed_stats.reset()
    monkeypatch.setattr(worker, "supabase", None)
    monkeypatch.setattr(worker.time, "sleep", lambda *a, **k: None)
    yield
    worker.armed_stocks.clear()
    worker.sent_signals.clear()
    worker._subscribed_symbols.clear()
    worker.feed_stats.reset()


def test_fetch_200_populates_armed_list(monkeypatch):
    """情境一:200 正常回應 → 正確載入 Armed 名單與 watch_price/adv20。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, _radar_payload()))

    worker.load_armed_list()

    assert set(worker.armed_stocks.keys()) == {"2330", "2454"}
    assert worker.armed_stocks["2330"]["watch_price"] == 1050
    assert worker.armed_stocks["2330"]["adv20"] == 50000
    assert worker.armed_stocks["2330"]["name"] == "台積電"
    assert worker.armed_stocks["2330"]["pool"] == "armed"


def test_watchlist_merged_into_monitor_pool(monkeypatch):
    """自選併入監控池:Armed 優先,自選後接;同檔標 both。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, _radar_payload()))
    monkeypatch.setattr(worker, "supabase", _approved_watchlist("2330", "2303"))

    worker.load_armed_list()

    assert set(worker.armed_stocks.keys()) == {"2330", "2454", "2303"}
    assert worker.armed_stocks["2330"]["pool"] == "both"
    assert worker.armed_stocks["2454"]["pool"] == "armed"
    assert worker.armed_stocks["2303"]["pool"] == "watchlist"
    assert worker.armed_stocks["2303"]["name"] == "2303"  # 不在 radar stocks → 用代號


def test_monitor_pool_caps_at_fugle_free_ws_limit(monkeypatch):
    """Fugle 基本用戶 WS 訂閱上限 5:超過則裁切,未發動優先於自選。"""
    monkeypatch.setattr(worker, "MAX_MONITOR", 5)
    payload = {
        "lists": {"armed": ["1001", "1002", "1003"]},
        "stocks": [
            {"id": f"100{i}", "name": f"A{i}", "close": 10, "tech": {"watch_price": 11, "adv20": 100}}
            for i in range(1, 4)
        ] + [
            {"id": f"200{i}", "name": f"W{i}", "close": 10, "tech": {"watch_price": 11, "adv20": 100}}
            for i in range(1, 5)
        ],
    }
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, payload))
    monkeypatch.setattr(
        worker, "supabase", _approved_watchlist(*[f"200{i}" for i in range(1, 5)])
    )

    worker.load_armed_list()

    assert len(worker.armed_stocks) == 5
    assert set(worker.armed_stocks.keys()) == {"1001", "1002", "1003", "2001", "2002"}
    assert "2003" not in worker.armed_stocks


def _mixed_status_watchlist(**kw):
    return _FakeSupabase(
        profiles=_profiles(),
        watchlist=[
            {"user_id": APPROVED_UID, "stock_id": "2330"},
            {"user_id": APPROVED_UID, "stock_id": "2303"},
            {"user_id": PENDING_UID, "stock_id": "1101"},
            {"user_id": REJECTED_UID, "stock_id": "2603"},
            {"user_id": REJECTED_UID, "stock_id": "2330"},  # 與核准者重複也只算一次
            {"user_id": "44444444-4444-4444-4444-444444444444", "stock_id": "3008"},  # 無 profile
        ],
        **kw,
    )


def test_watchlist_only_includes_approved_users():
    """service_role 繞過 RLS:只納入 app_profiles.status='approved' 的自選;pending/rejected/無 profile 排除。"""
    fake = _mixed_status_watchlist()
    worker.supabase = fake  # autouse fixture 會還原

    ids = worker.fetch_watchlist_ids()

    assert ids == ["2330", "2303"]
    # 伺服端過濾條件確實下達
    assert ("app_profiles", "eq", "status", "approved") in fake.calls
    assert ("watchlist", "in_", "user_id", [APPROVED_UID]) in fake.calls


def test_watchlist_client_side_filter_when_server_filters_ignored():
    """伺服端過濾失效(回傳全部列)時,worker 端二次過濾仍只留已核准者。"""
    worker.supabase = _mixed_status_watchlist(apply_filters=False)

    assert worker.fetch_watchlist_ids() == ["2330", "2303"]


def test_watchlist_fail_closed_when_app_profiles_read_fails(caplog):
    """app_profiles 讀取失敗 → 回傳空列表且不查 watchlist(絕不退回讀全部列)。"""
    fake = _mixed_status_watchlist(errors={"app_profiles": RuntimeError("boom")})
    worker.supabase = fake

    with caplog.at_level(logging.ERROR):
        ids = worker.fetch_watchlist_ids()

    assert ids == []
    assert not any(c[0] == "watchlist" for c in fake.calls)
    assert "app_profiles" in caplog.text


def test_watchlist_empty_when_no_approved_users():
    fake = _FakeSupabase(
        profiles=[{"user_id": PENDING_UID, "status": "pending"}],
        watchlist=[{"user_id": PENDING_UID, "stock_id": "1101"}],
    )
    worker.supabase = fake

    assert worker.fetch_watchlist_ids() == []
    assert not any(c[0] == "watchlist" for c in fake.calls)


def test_app_profiles_failure_keeps_armed_pool(monkeypatch):
    """app_profiles 失敗只停用自選池,Armed 監控照常載入。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, _radar_payload()))
    monkeypatch.setattr(
        worker, "supabase",
        _mixed_status_watchlist(errors={"app_profiles": RuntimeError("boom")}),
    )

    worker.load_armed_list()

    assert set(worker.armed_stocks.keys()) == {"2330", "2454"}
    assert all(v["pool"] == "armed" for v in worker.armed_stocks.values())


def test_fetch_403_first_time_fatal_with_access_hint(monkeypatch, caplog):
    """情境二:403 且首次抓取 → fatal exit,且訊息指引檢查 Access token。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(403))

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SystemExit):
            worker.load_armed_list()

    log_text = caplog.text
    assert "403" in log_text
    assert "RADAR_SERVICE_KEY" in log_text
    assert worker.armed_stocks == {}


def test_repeated_failure_keeps_previous_list(monkeypatch, caplog):
    """情境三:先成功、後連續失敗 → 沿用上一次成功抓到的名單,不 fatal。"""
    # 第一次:成功載入
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, _radar_payload()))
    worker.load_armed_list()
    assert set(worker.armed_stocks.keys()) == {"2330", "2454"}

    # 第二次:連線錯誤,重試三次仍失敗
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("network down")

    monkeypatch.setattr(worker.requests, "get", _boom)

    with caplog.at_level(logging.WARNING):
        worker.load_armed_list()  # 不應拋出 SystemExit

    # 名單被保留(沿用上次成功結果)
    assert set(worker.armed_stocks.keys()) == {"2330", "2454"}
    assert "沿用上一次成功抓取的監控名單" in caplog.text


def test_cf_access_headers_attached_when_env_set(monkeypatch):
    """設定 CF_ACCESS_* 時,請求 headers 應自動夾帶 Access service token(過渡期)。"""
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_ID", "cid.example")
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(worker, "RADAR_SERVICE_KEY", None)

    headers = worker._build_radar_headers()
    assert headers["CF-Access-Client-Id"] == "cid.example"
    assert headers["CF-Access-Client-Secret"] == "csecret"
    assert "User-Agent" in headers
    assert "X-Radar-Service-Key" not in headers


def test_radar_service_key_header_attached_when_env_set(monkeypatch):
    """設定 RADAR_SERVICE_KEY 時,請求應夾帶 X-Radar-Service-Key。"""
    monkeypatch.setattr(worker, "RADAR_SERVICE_KEY", "radar-secret")
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_ID", None)
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_SECRET", None)

    headers = worker._build_radar_headers()
    assert headers["X-Radar-Service-Key"] == "radar-secret"
    assert "CF-Access-Client-Id" not in headers


def test_no_cf_access_headers_when_env_missing(monkeypatch):
    """未設 CF_ACCESS_* / RADAR_SERVICE_KEY 時,不應夾帶門鎖 header。"""
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_ID", None)
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_SECRET", None)
    monkeypatch.setattr(worker, "RADAR_SERVICE_KEY", None)

    headers = worker._build_radar_headers()
    assert "CF-Access-Client-Id" not in headers
    assert "CF-Access-Client-Secret" not in headers
    assert "X-Radar-Service-Key" not in headers


def test_process_trade_parses_raw_json_string_message(monkeypatch):
    """2026-07-16 回歸:SDK 的 on("message") 回呼給的是原始 JSON 字串,不是已解析
    的 dict——舊碼直接 message.get(...) 會對字串炸 AttributeError,需先 json.loads。
    """
    monkeypatch.setattr(worker, "in_continuous_trading", lambda _now: True)
    monkeypatch.setattr(worker, "push_signal", lambda *a, **k: None)
    worker.armed_stocks["2330"] = {
        "name": "台積電", "watch_price": 99999, "adv20": 0,
        "last_price": 0, "volume": 0, "trades_5m": [],
    }
    message = json.dumps({
        "event": "data",
        "data": {"symbol": "2330", "price": 500.0, "volume": 1},
    })

    worker.process_trade(message)

    state = worker.armed_stocks["2330"]
    assert state["last_price"] == 500.0
    assert state["volume"] == 1


def test_process_trade_delivers_signal_without_a_running_event_loop(monkeypatch):
    """2026-07-17 回歸(生產環境實測炸滿 log,連續數百筆「Error processing trade:
    no running event loop」):Fugle SDK 的 on("message") callback 是從背景執行緒
    呼叫 process_trade(),不是 asyncio 事件迴圈那條執行緒。舊碼 push_signal 是
    async def、呼叫端用 asyncio.create_task() 排程,在沒有事件迴圈的執行緒下
    asyncio.create_task() 本身就會 RuntimeError('no running event loop')、
    coroutine 主體(真正寫入 Supabase 那段)完全沒機會執行,被最外層 except 吞掉。

    這裡刻意不 monkeypatch push_signal 本身(那樣測不出差異——若 push_signal 仍是
    async def,單純呼叫 push_signal(...) 只會建立 coroutine 物件、不會真的執行,
    是 asyncio.create_task() 才會觸發那個 RuntimeError,監看 push_signal 有沒有
    被「呼叫」測不出這個差異)。改監看 push_signal 真正執行到底時會動到的東西:
    supabase client 是否真的被呼叫、sent_signals 是否真的被寫入——舊碼在這裡兩者
    皆不會發生,新碼(同步呼叫)兩者都會發生。
    """
    monkeypatch.setattr(worker, "in_continuous_trading", lambda _now: True)
    mock_supabase = MagicMock()
    monkeypatch.setattr(worker, "supabase", mock_supabase)
    worker.armed_stocks["2330"] = {
        "name": "台積電", "watch_price": 99999, "adv20": 0,
        "last_price": 0, "volume": 0, "trades_5m": [],
    }
    # price*size*1000 = 500*20*1000 = 1000萬 >= 500萬門檻 → 應觸發 I-1
    # (Fugle trades:size=本筆成交量,volume=當日累計量)
    message = json.dumps({
        "event": "data",
        "data": {"symbol": "2330", "price": 500.0, "size": 20, "volume": 20},
    })

    worker.process_trade(message)

    assert "2330_I-1" in worker.sent_signals, "push_signal 應該真正執行完(寫入 sent_signals)"
    mock_supabase.table.assert_called_with("intraday_signals")


def _signal_state(**overrides):
    base = {"name": "測試股", "watch_price": 0, "adv20": 0, "turnover": 0,
            "last_price": 0, "volume": 0, "trades_5m": []}
    base.update(overrides)
    return base


# evaluate_signals() 是純函式,不需要 asyncio/Supabase,直接測規則本身(docs/24 §2.2)。

def test_i1_large_single_trade():
    state = _signal_state(turnover=2_000_000_000)  # 日均 20 億 → 門檻封頂 500 萬
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=500.0, qty=20, now=now)
    # 500*20*1000 = 1000萬 = 1千萬
    assert any(s[0] == "I-1" and "1千萬" in s[1] for s in signals)


def test_i1_midcap_lower_threshold():
    # 日均 1 億 → 門檻 40 萬,但下限抬到 80 萬;單筆 100 萬應觸發
    state = _signal_state(turnover=100_000_000)
    now = datetime(2026, 7, 20, 9, 30)
    thr = worker.i1_amount_threshold(state, 50.0)
    assert thr == worker.I1_MIN_AMOUNT
    signals = worker.evaluate_signals(state, price=50.0, qty=20, now=now)  # 100 萬
    assert any(s[0] == "I-1" for s in signals)


def test_i1_ignores_premarket_auction():
    state = _signal_state(turnover=2_000_000_000)
    now = datetime(2026, 7, 20, 8, 50)  # 試搓
    signals = worker.evaluate_signals(state, price=500.0, qty=20, now=now)
    assert signals == []


def test_format_twd_amount_units():
    assert worker.format_twd_amount(5_000_000) == "5百萬"
    assert worker.format_twd_amount(10_000_000) == "1千萬"
    assert worker.format_twd_amount(100_000_000) == "1億"
    assert worker.format_twd_amount(150_000_000) == "1.5億"


def test_is_etf_id_covers_letter_suffix():
    assert worker.is_etf_id("0050")
    assert worker.is_etf_id("00878")
    assert worker.is_etf_id("00679B")
    assert not worker.is_etf_id("2330")
    assert not worker.is_etf_id("03001")  # 權證 03xxxx


def test_etf_ids_excluded_from_monitor_pool(monkeypatch):
    payload = {
        "lists": {"armed": ["0050", "2330"]},
        "stocks": [
            {"id": "0050", "name": "元大台灣50", "close": 100, "tech": {"watch_price": 101, "adv20": 1}},
            {"id": "2330", "name": "台積電", "close": 1000, "tech": {"watch_price": 1050, "adv20": 50000}},
            {"id": "00878", "name": "國泰永續高股息", "close": 20, "tech": {"watch_price": 21, "adv20": 1}},
        ],
    }
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, payload))
    monkeypatch.setattr(worker, "supabase", _approved_watchlist("00878", "2454"))

    worker.load_armed_list()

    assert "0050" not in worker.armed_stocks
    assert "00878" not in worker.armed_stocks
    assert "2330" in worker.armed_stocks


def test_entry_reads_scores_watch_price_and_turnover():
    entry = worker._entry_from_stock(
        "2603",
        {
            "id": "2603",
            "name": "長榮",
            "close": 180,
            "turnover": 800_000_000,
            "volume_lots": 4000,
            "volume_ratio": 2.0,
            "scores": {"watch_price": 185, "final": 70},
        },
        "armed",
    )
    assert entry["watch_price"] == 185
    assert entry["turnover"] == 800_000_000
    assert entry["adv20"] == 2000.0  # 4000 / 2


def test_i1_not_triggered_below_threshold():
    state = _signal_state(turnover=2_000_000_000)  # 門檻 500 萬
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=500.0, qty=1, now=now)  # 50 萬
    assert not any(s[0] == "I-1" for s in signals)


def test_i2_volume_surge_vs_prorated_adv20():
    # 開盤 60 分鐘(09:00-10:00),adv20=27000 → 預期量 27000*60/270=6000,2倍=12000
    state = _signal_state(adv20=27000, volume=12000)
    now = datetime(2026, 7, 20, 10, 0)
    signals = worker.evaluate_signals(state, price=100.0, qty=0, now=now)
    assert any(s[0] == "I-2" for s in signals)


def test_i2_not_triggered_before_min_elapsed():
    # 開盤才 2 分鐘,即使量能比例很高也不判 I-2(基期不穩)
    state = _signal_state(adv20=27000, volume=5000)
    now = datetime(2026, 7, 20, 9, 2)
    signals = worker.evaluate_signals(state, price=100.0, qty=0, now=now)
    assert not any(s[0] == "I-2" for s in signals)


def test_i2_not_triggered_without_adv20():
    state = _signal_state(adv20=0, volume=999999)
    now = datetime(2026, 7, 20, 10, 0)
    signals = worker.evaluate_signals(state, price=100.0, qty=0, now=now)
    assert not any(s[0] == "I-2" for s in signals)


def test_i3_five_minute_pullup():
    now = datetime(2026, 7, 20, 10, 0)
    state = _signal_state(trades_5m=[(now - timedelta(minutes=1), 100.0)])
    signals = worker.evaluate_signals(state, price=102.0, qty=0, now=now)
    assert any(s[0] == "I-3" for s in signals)


def test_i3_not_triggered_below_two_percent():
    now = datetime(2026, 7, 20, 10, 0)
    state = _signal_state(trades_5m=[(now - timedelta(minutes=1), 100.0)])
    signals = worker.evaluate_signals(state, price=101.0, qty=0, now=now)
    assert not any(s[0] == "I-3" for s in signals)


def test_i4_breakout_watch_price():
    state = _signal_state(watch_price=100.0)
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=100.5, qty=0, now=now)
    assert any(s[0] == "I-4" for s in signals)


def test_i4_not_triggered_below_watch_price():
    state = _signal_state(watch_price=100.0)
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=99.0, qty=0, now=now)
    assert not any(s[0] == "I-4" for s in signals)


# ---------------------------------------------------------------------------
# 連線韌性(2026-10-04):斷線重連、退避告警、stall 看門狗、試撮把關、liveness 遙測
# ---------------------------------------------------------------------------

class _FakeWsClient:
    """模擬 fugle_marketdata 的 WebSocketStockClient(on/connect/subscribe/disconnect)。"""

    def __init__(self, fail=None):
        self.handlers = {}
        self.subscribed = []
        self.fail = fail
        self.connect_calls = 0
        self.disconnect_calls = 0

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def emit(self, event, *args):
        for fn in self.handlers.get(event, []):
            fn(*args)

    def connect(self):
        self.connect_calls += 1
        if self.fail:
            raise self.fail

    def subscribe(self, params):
        assert params["channel"] == "trades"
        self.subscribed.append(params["symbol"])

    def disconnect(self):
        self.disconnect_calls += 1


class _Clock:
    def __init__(self, mono=1000.0, wall=datetime(2026, 10, 5, 10, 0)):
        self.mono = mono
        self.wall = wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def _make_feed(clock, clients, *, fail=lambda n: False, notifier=None, heartbeat=None):
    """clients 會收到每個新建的 fake client;fail(n) 為真的第 n 次(1 起算)連線失敗。"""
    state = {"n": 0}

    def factory():
        state["n"] += 1
        fail_exc = ConnectionError("refused") if fail(state["n"]) else None
        c = _FakeWsClient(fail=fail_exc)
        clients.append(c)
        return c

    return worker.FeedSupervisor(
        factory,
        mono=lambda: clock.mono,
        wall=lambda: clock.wall,
        rng=lambda: 0.0,
        sleep=lambda *_: None,
        notifier=notifier or MagicMock(),
        heartbeat=heartbeat,
        stats=worker.feed_stats,
        alert_after=300,
        stall_seconds=180,
        connect_timeout=5,
    )


def _monitor(*sids):
    for sid in sids:
        worker.armed_stocks[sid] = _signal_state(name=sid, pool="armed")


def test_disconnect_triggers_reconnect_and_resubscribe():
    _monitor("2330", "2454")
    clock, clients = _Clock(), []
    feed = _make_feed(clock, clients)

    feed.tick()
    assert feed.connected and len(clients) == 1
    assert sorted(clients[0].subscribed) == ["2330", "2454"]
    clock.advance(61)
    feed.tick()  # 連線穩定
    assert feed.down_since is None

    # 正式 log 的情境:SDK 先發 error(Connection to remote host was lost)再發 disconnect
    clients[0].emit("error", ConnectionError("Connection to remote host was lost."))
    clients[0].emit("disconnect", None, None)
    assert not feed.connected

    feed.tick()  # 穩定連線後斷線:第一次重試立即進行
    assert feed.connected and len(clients) == 2
    assert sorted(clients[1].subscribed) == ["2330", "2454"]
    assert feed.reconnects == 1
    assert worker._subscribed_symbols == {"2330", "2454"}
    assert clients[0].disconnect_calls >= 1  # 舊連線一定被關

    # 舊 client 的遲到 callback 不得把新連線標成斷線
    clients[0].emit("disconnect", 1006, "late")
    assert feed.connected


def test_error_only_closes_old_client_before_reconnecting():
    """websocket-client 在 SDK callback 拋例外時只發 on_error、不關連線:
    必須主動關舊連線,否則兩條連線並存(重複訂閱)且非 daemon 執行緒讓程序收不了工。"""
    _monitor("2330")
    clock, clients = _Clock(), []
    feed = _make_feed(clock, clients)
    feed.tick()
    clock.advance(61)
    feed.tick()

    clients[0].emit("error", ValueError("exception from callback"))
    feed.tick()

    assert len(clients) == 2 and feed.connected
    assert clients[0].disconnect_calls == 1
    assert clients[1].subscribed == ["2330"]
    feed.shutdown()
    assert clients[1].disconnect_calls == 1


def test_subscribe_failure_after_connect_goes_back_to_reconnect():
    """connect() 成功但訂閱送不出去:不得停在 connected=True 且零訂閱(整天失明)。"""
    _monitor("2330")
    clock, clients = _Clock(), []

    class _SubFail(_FakeWsClient):
        def subscribe(self, params):
            raise ConnectionError("socket is already closed")

    def factory():
        c = _SubFail() if not clients else _FakeWsClient()
        clients.append(c)
        return c

    feed = worker.FeedSupervisor(
        factory, mono=lambda: clock.mono, wall=lambda: clock.wall, rng=lambda: 0.0,
        sleep=lambda *_: None, notifier=MagicMock(),
    )
    feed.tick()
    assert not feed.connected
    assert feed.heartbeat_status() == "reconnecting"
    assert worker._subscribed_symbols == set()
    assert clients[0].disconnect_calls >= 1

    clock.advance(feed.next_attempt_at - clock.mono)
    feed.tick()
    assert feed.connected and clients[1].subscribed == ["2330"]


def test_disconnect_right_after_connect_returns_counts_as_failure():
    """斷線事件在 connect() 回傳前後到達(尚未 connected)也不能被吞掉。"""
    _monitor("2330")
    clock, clients = _Clock(), []

    class _DropOnConnect(_FakeWsClient):
        def connect(self):
            super().connect()
            self.emit("disconnect", 1006, "dropped during auth")

    def factory():
        c = _DropOnConnect() if not clients else _FakeWsClient()
        clients.append(c)
        return c

    feed = worker.FeedSupervisor(
        factory, mono=lambda: clock.mono, wall=lambda: clock.wall, rng=lambda: 0.0,
        sleep=lambda *_: None, notifier=MagicMock(),
    )
    feed.tick()
    assert not feed.connected and feed.failures == 1
    assert clients[0].subscribed == []
    clock.advance(feed.next_attempt_at - clock.mono)
    feed.tick()
    assert feed.connected and len(clients) == 2


def test_flapping_connection_backs_off_and_alerts_once():
    """連上就被踢:不得每秒重連一次;中斷持續累計並只告警一次。"""
    _monitor("2330")
    clock, clients = _Clock(), []
    notifier = MagicMock()
    feed = _make_feed(clock, clients, notifier=notifier)
    for _ in range(600):
        feed.tick()
        if feed.connected:
            clients[-1].emit("disconnect", 1006, "kicked")
        clock.advance(1)
    assert len(clients) < 30          # 舊行為:600 次
    high = [c for c in notifier.call_args_list if c.args[2] == "high"]
    assert len(high) == 1
    assert feed.heartbeat_status() == "offline"


def test_repeated_failures_backoff_and_single_alert_then_recovery():
    _monitor("2330")
    clock, clients = _Clock(), []
    notifier = MagicMock()
    heartbeat = MagicMock()
    # 第 1 次連線成功,第 2–13 次失敗,之後成功
    feed = _make_feed(clock, clients, fail=lambda n: 2 <= n <= 13,
                      notifier=notifier, heartbeat=heartbeat)

    feed.tick()
    assert feed.connected
    clock.advance(61)
    feed.tick()
    clients[0].emit("disconnect", 1006, "lost")

    delays = []
    for _ in range(10):
        feed.tick()  # 嘗試一次(失敗)並排定下一次
        delays.append(feed.next_attempt_at - clock.mono)
        clock.advance(feed.next_attempt_at - clock.mono)
    assert len(clients) == 11
    assert delays[:7] == [2, 4, 8, 16, 32, 60, 60]  # rng=0 → 無 jitter,上限 60
    assert not feed.connected

    # 第 10 次失敗時已斷 302s(> 300s):只告警一次(high),heartbeat 標 offline
    high = [c for c in notifier.call_args_list if c.args[2] == "high"]
    assert len(high) == 1
    assert feed.heartbeat_status() == "offline"
    heartbeat.assert_any_call("offline")
    for _ in range(2):  # 仍失敗,不重複告警
        feed.tick()
        clock.advance(60)
    assert not feed.connected
    assert len([c for c in notifier.call_args_list if c.args[2] == "high"]) == 1

    # 之後連線成功 → 穩定 60s 後才算恢復,通知一次
    while not feed.connected:
        clock.advance(60)
        feed.tick()
    assert [c for c in notifier.call_args_list if c.args[2] == "default"] == []
    clock.advance(61)
    feed.tick()
    recovery = [c for c in notifier.call_args_list if c.args[2] == "default"]
    assert len(recovery) == 1
    assert feed.heartbeat_status() == "online"
    clock.advance(61)
    feed.tick()
    assert notifier.call_count == 2


def test_jitter_never_exceeds_cap():
    feed = worker.FeedSupervisor(lambda: _FakeWsClient(), rng=lambda: 0.999)
    assert 2 <= feed.backoff_delay(1) <= 2.5
    assert feed.backoff_delay(20) == 60


def test_stall_forces_reconnect_during_continuous_trading(caplog):
    _monitor("2330")
    clock, clients = _Clock(wall=datetime(2026, 10, 5, 10, 0)), []
    feed = _make_feed(clock, clients)
    feed.tick()
    assert len(clients) == 1

    clock.advance(170)
    feed.tick()
    assert len(clients) == 1  # 未滿 180s 不動作

    with caplog.at_level(logging.WARNING):
        clock.advance(20)
        feed.tick()
    assert clients[0].disconnect_calls == 1
    assert len(clients) == 2 and feed.connected
    assert feed.reconnects == 1
    assert "stall" in caplog.text

    # 重連後仍無成交(如休市):門檻倍增(360s),避免整天每 3 分鐘重連
    clock.advance(200)
    feed.tick()
    assert len(clients) == 2
    clock.advance(200)
    feed.tick()
    assert len(clients) == 3

    # 收到任何 Fugle 訊息(這裡是 heartbeat,不是成交)→ 門檻回到 180s 且不會誤判
    clock.advance(1)
    clients[-1].emit("message", json.dumps({"event": "heartbeat", "data": {"time": 0}}))
    clock.advance(170)
    feed.tick()
    assert len(clients) == 3
    assert feed.stall_strikes == 0


def test_no_stall_reconnect_outside_continuous_trading():
    _monitor("2330")
    clock, clients = _Clock(wall=datetime(2026, 10, 5, 8, 50)), []
    feed = _make_feed(clock, clients)
    feed.tick()
    clock.advance(9 * 60)  # 08:59,試撮期間沒有成交不算 stall
    feed.tick()
    assert len(clients) == 1
    clock.advance(120)  # 09:01:00,連續競價才剛開始 1 分鐘(stall 從 09:00 起算)
    feed.tick()
    assert len(clients) == 1


class _FixedDatetime(datetime):
    fixed = datetime(2026, 10, 5, 10, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def _trade_msg(sid="2330", price=500.0, size=20, volume=1000, **extra):
    data = {"symbol": sid, "price": price, "size": size, "volume": volume}
    data.update(extra)
    return json.dumps({"event": "data", "data": data, "channel": "trades"})


def _tw_micros(dt):
    return int(dt.replace(tzinfo=worker.TW_TZ).timestamp() * 1_000_000)


@pytest.fixture
def _trade_env(monkeypatch):
    pushed = []
    monkeypatch.setattr(worker, "datetime", _FixedDatetime)
    monkeypatch.setattr(worker, "push_signal", lambda *a, **k: pushed.append(a))
    worker.armed_stocks["2330"] = _signal_state(
        name="台積電", turnover=2_000_000_000, watch_price=100.0, adv20=1000, pool="armed"
    )
    return pushed


@pytest.mark.parametrize(
    "wall, extra",
    [
        (datetime(2026, 10, 5, 10, 0), {"isTrial": True}),                 # 盤中試撮旗標
        (datetime(2026, 10, 5, 8, 53), {}),                                  # 開盤前試撮時段
        (datetime(2026, 10, 5, 13, 31), {}),                                 # 收盤後
        (datetime(2026, 10, 5, 10, 0), {"time": _tw_micros(datetime(2026, 10, 5, 8, 53))}),  # 容器 TZ 錯
    ],
)
def test_trial_and_out_of_session_trades_produce_no_signal(_trade_env, wall, extra):
    _FixedDatetime.fixed = wall
    worker.process_trade(_trade_msg(**extra))

    state = worker.armed_stocks["2330"]
    assert _trade_env == []
    assert state["trades_5m"] == []      # 不以試撮價種 5 分鐘窗
    assert state["volume"] == 0
    assert state["last_price"] == 0
    assert worker.feed_stats.trades == 1  # 但 liveness 仍計入(資料流活著)


def test_continuous_trade_uses_size_and_cumulative_volume(_trade_env):
    _FixedDatetime.fixed = datetime(2026, 10, 5, 10, 0)
    worker.process_trade(_trade_msg(time=_tw_micros(datetime(2026, 10, 5, 10, 0)), volume=1000))

    state = worker.armed_stocks["2330"]
    assert state["volume"] == 1000           # 累計量取代,不是相加
    assert state["last_price"] == 500.0
    types = [a[2] for a in _trade_env]
    assert "I-1" in types                    # 500*20(size)*1000 = 1000萬 ≥ 500萬
    worker.process_trade(_trade_msg(size=1, volume=1001))
    assert state["volume"] == 1001


@pytest.mark.parametrize(
    "wall, flag",
    [(datetime(2026, 10, 5, 9, 0, 0), "isOpen"), (datetime(2026, 10, 5, 13, 30, 3), "isClose")],
)
def test_auction_prints_update_state_but_never_signal(_trade_env, wall, flag):
    """開/收盤集合競價撮合是一次總量:不得觸發 I-1「數十億大單」/I-2 並吃掉當日訊號額度。"""
    _FixedDatetime.fixed = wall
    t = _tw_micros(wall.replace(second=0))
    worker.process_trade(_trade_msg(price=1000, size=3000, volume=30000, time=t, **{flag: True}))

    state = worker.armed_stocks["2330"]
    assert _trade_env == []
    assert state["volume"] == 30000
    assert state["last_price"] == 1000
    assert worker.sent_signals == set()


def test_run_session_survives_tick_exception(caplog):
    _monitor("2330")
    clock, clients = _Clock(wall=datetime(2026, 10, 5, 8, 0)), []
    feed = _make_feed(clock, clients)
    calls = {"n": 0}
    real_tick = feed.tick

    def flaky_tick():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        real_tick()

    feed.tick = flaky_tick
    with caplog.at_level(logging.ERROR):
        n = _run_session(feed, clock, until_close_after=5)
    assert n == 6 and calls["n"] == 5
    assert "feed tick failed" in caplog.text


def test_liveness_line_format():
    line = worker.format_liveness(12, 3, datetime(2026, 10, 5, 10, 5, 7), 2)
    assert line == "liveness trades_5m=12 symbols_with_trades=3 last_trade_at=10:05:07 reconnects=2"
    assert "last_trade_at=- " in worker.format_liveness(0, 0, None, 0)


def _run_session(feed, clock, until_close_after, reload_fn=None):
    import asyncio

    calls = {"n": 0}

    def now_fn():
        calls["n"] += 1
        return datetime(2026, 10, 5, 13, 35) if calls["n"] > until_close_after else clock.wall

    async def sleep_fn(_):
        clock.advance(100)

    asyncio.run(worker.run_session(
        feed, now_fn=now_fn, mono_fn=lambda: clock.mono, sleep_fn=sleep_fn,
        reload_fn=reload_fn or (lambda: None),
    ))
    return calls["n"]


def test_run_session_emits_liveness_and_shuts_down_at_1335(caplog):
    _monitor("2330")
    clock, clients = _Clock(wall=datetime(2026, 10, 5, 8, 0)), []  # 盤前:不觸發 stall
    feed = _make_feed(clock, clients)
    reload_fn = MagicMock()
    worker.feed_stats.record("2330", clock.mono, datetime(2026, 10, 5, 10, 0, 1))

    with caplog.at_level(logging.INFO):
        _run_session(feed, clock, until_close_after=8, reload_fn=reload_fn)

    assert "liveness trades_5m=1 symbols_with_trades=1 last_trade_at=10:00:01 reconnects=0" in caplog.text
    assert "Market closed. Shutting down worker." in caplog.text
    assert reload_fn.called
    assert feed.closing and not feed.connected
    assert clients[-1].disconnect_calls == 1


def test_run_session_keeps_running_while_disconnected():
    """連線一直失敗也不提早退出,持續重試直到 13:35。"""
    _monitor("2330")
    clock, clients = _Clock(), []
    feed = _make_feed(clock, clients, fail=lambda n: True)

    n = _run_session(feed, clock, until_close_after=20)

    assert n == 21
    assert len(clients) >= 5
    assert not feed.connected
