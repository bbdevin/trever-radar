"""盤中 worker radar.json HTTP 抓取邏輯的輕量單元測試。

不真發網路請求(monkeypatch requests.get)、不真連 Fugle/Supabase。
匯入 intraday.worker 不應觸發 fatal exit(env 檢查與 supabase client 建立已移入 main())。
"""
import json
import logging

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
    monkeypatch.setattr(worker.time, "sleep", lambda *a, **k: None)
    yield
    worker.armed_stocks.clear()


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


def test_process_trade_parses_raw_json_string_message():
    """2026-07-16 回歸:SDK 的 on("message") 回呼給的是原始 JSON 字串,不是已解析
    的 dict——舊碼直接 message.get(...) 會對字串炸 AttributeError,需先 json.loads。
    價格/成交量刻意不觸發任何 I-1/I-3/I-4 訊號分支,避免測試需要跑 asyncio 事件迴圈。
    """
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
