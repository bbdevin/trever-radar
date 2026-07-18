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


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """每個測試前清空模組全域狀態,並讓 time.sleep 變 no-op(避免退避真的睡)。"""
    worker.armed_stocks.clear()
    worker.sent_signals.clear()
    monkeypatch.setattr(worker.time, "sleep", lambda *a, **k: None)
    yield
    worker.armed_stocks.clear()
    worker.sent_signals.clear()


def test_fetch_200_populates_armed_list(monkeypatch):
    """情境一:200 正常回應 → 正確載入 Armed 名單與 watch_price/adv20。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(200, _radar_payload()))

    worker.load_armed_list()

    assert set(worker.armed_stocks.keys()) == {"2330", "2454"}
    assert worker.armed_stocks["2330"]["watch_price"] == 1050
    assert worker.armed_stocks["2330"]["adv20"] == 50000
    assert worker.armed_stocks["2330"]["name"] == "台積電"


def test_fetch_403_first_time_fatal_with_access_hint(monkeypatch, caplog):
    """情境二:403 且首次抓取 → fatal exit,且訊息指引檢查 Access token。"""
    monkeypatch.setattr(worker.requests, "get",
                        lambda *a, **k: _DummyResp(403))

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SystemExit):
            worker.load_armed_list()

    log_text = caplog.text
    # 403 分支的警告訊息應指引 Cloudflare Access service token
    assert "403" in log_text
    assert "CF_ACCESS_CLIENT_ID" in log_text
    # 首次即失敗 → 名單維持空
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
    assert "沿用上一次成功抓取的 Armed 名單" in caplog.text


def test_cf_access_headers_attached_when_env_set(monkeypatch):
    """設定 CF_ACCESS_* 時,請求 headers 應自動夾帶 Access service token。"""
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_ID", "cid.example")
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_SECRET", "csecret")

    headers = worker._build_radar_headers()
    assert headers["CF-Access-Client-Id"] == "cid.example"
    assert headers["CF-Access-Client-Secret"] == "csecret"
    assert "User-Agent" in headers


def test_no_cf_access_headers_when_env_missing(monkeypatch):
    """未設 CF_ACCESS_* 時,不應夾帶 Access header(公開抓取)。"""
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_ID", None)
    monkeypatch.setattr(worker, "CF_ACCESS_CLIENT_SECRET", None)

    headers = worker._build_radar_headers()
    assert "CF-Access-Client-Id" not in headers
    assert "CF-Access-Client-Secret" not in headers


def test_process_trade_parses_raw_json_string_message(monkeypatch):
    """2026-07-16 回歸:SDK 的 on("message") 回呼給的是原始 JSON 字串,不是已解析
    的 dict——舊碼直接 message.get(...) 會對字串炸 AttributeError,需先 json.loads。
    """
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
    mock_supabase = MagicMock()
    monkeypatch.setattr(worker, "supabase", mock_supabase)
    worker.armed_stocks["2330"] = {
        "name": "台積電", "watch_price": 99999, "adv20": 0,
        "last_price": 0, "volume": 0, "trades_5m": [],
    }
    # price*qty*1000 = 500*20*1000 = 1000萬 >= 500萬門檻 → 應觸發 I-1
    message = json.dumps({
        "event": "data",
        "data": {"symbol": "2330", "price": 500.0, "volume": 20},
    })

    worker.process_trade(message)

    assert "2330_I-1" in worker.sent_signals, "push_signal 應該真正執行完(寫入 sent_signals)"
    mock_supabase.table.assert_called_with("intraday_signals")


def _signal_state(**overrides):
    base = {"name": "測試股", "watch_price": 0, "adv20": 0,
            "last_price": 0, "volume": 0, "trades_5m": []}
    base.update(overrides)
    return base


# evaluate_signals() 是純函式,不需要 asyncio/Supabase,直接測規則本身(docs/24 §2.2)。

def test_i1_large_single_trade():
    state = _signal_state()
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=500.0, qty=20, now=now)
    assert ("I-1", "單筆大單 1000萬") in signals


def test_i1_not_triggered_below_threshold():
    state = _signal_state()
    now = datetime(2026, 7, 20, 9, 30)
    signals = worker.evaluate_signals(state, price=500.0, qty=1, now=now)
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
