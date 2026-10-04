import os
import json
import time
import random
import asyncio
import logging
import threading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
from fugle_marketdata import WebSocketClient, RestClient
import requests

# --- Configuration & Setup ---
load_dotenv()
FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# radar.json 改為 HTTP 抓取(雲端解耦:worker 只需自身 + .env 即可獨立部署,
# 不再依賴 repo 內的 web/public/data/radar.json 實體檔)。
RADAR_JSON_URL = os.getenv("RADAR_JSON_URL", "https://radar.techtrever.com/data/radar.json")
# WP-B7:Worker 驗 X-Radar-Service-Key(取代 Access 作為 /data 門鎖)。
# Access 尚未關閉前,仍可同時帶 CF_ACCESS_* 穿透 Access;關閉後只靠 RADAR_SERVICE_KEY。
RADAR_SERVICE_KEY = os.getenv("RADAR_SERVICE_KEY")
CF_ACCESS_CLIENT_ID = os.getenv("CF_ACCESS_CLIENT_ID")
CF_ACCESS_CLIENT_SECRET = os.getenv("CF_ACCESS_CLIENT_SECRET")

HTTP_TIMEOUT = 10          # 秒
HTTP_RETRIES = 3           # 抓取失敗退避重試次數
HTTP_USER_AGENT = "trever-radar-intraday-worker/1.0 (+https://trever-radar.pages.dev)"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# supabase client 於 main() 初始化(import 本模組時不建立連線,確保可被測試安全匯入)
supabase: Client = None

# --- State Management ---
# pool: "armed" | "watchlist" | "both"
armed_stocks = {}  # { '2330': { name, watch_price, adv20, last_price, volume, trades_5m, pool } }
sent_signals = set()  # To avoid spamming the same signal for the same stock
_subscribed_symbols: set[str] = set()  # 已向 Fugle 訂閱的代號（重整監控池時增量訂閱）

# 台股連續競價 09:00–13:30;08:30–09:00 為開盤集合競價(試搓),不計盤中訊號
TRADING_START_MINUTES = 9 * 60
TRADING_END_MINUTES = 13 * 60 + 30
TRADING_SESSION_MINUTES = TRADING_END_MINUTES - TRADING_START_MINUTES  # 270
I2_MIN_ELAPSED_MINUTES = 5  # 開盤前幾分鐘量能基期還不穩,不判 I-2 避免開盤就誤觸

# I-1 大單:依日均成交額分級(docs/24 §2.2);固定 500 萬對中小型過嚴
I1_MIN_AMOUNT = 800_000       # 下限 80 萬
I1_MAX_AMOUNT = 5_000_000     # 上限 500 萬(大型股)
I1_TURNOVER_PCT = 0.004       # 約日均成交額 0.4%
I1_FALLBACK_AMOUNT = 2_000_000  # 無日均額資料時用 200 萬(較舊固定 500 萬友善)

# Fugle「基本用戶」免費方案:台股 WS 訂閱數上限 5(1 channel × N 檔 = N 訂閱)。
# 見 https://developer.fugle.tw/docs/pricing/ — 超過會訂閱失敗/被拒,寧缺勿濫。
# 可用環境變數 FUGLE_WS_MAX_SUBSCRIBE 覆寫(付費方案再調高)。
MAX_MONITOR = max(1, int(os.getenv("FUGLE_WS_MAX_SUBSCRIBE", "5")))
POOL_LABEL = {"armed": "未發動", "watchlist": "自選", "both": "雙池"}

# --- 連線韌性(2026-10-04:正式 log 25 個交易日有 6 天盤中斷線後整天失明)---
RECONNECT_BACKOFF_BASE = 2.0      # 秒;第一次重試 2s,之後倍增
RECONNECT_BACKOFF_CAP = 60.0      # 秒;退避上限
CONNECT_TIMEOUT = 15.0            # 秒;SDK connect() 會無限等驗證,超過即視為失敗
# 斷線持續多久才告警(ERROR log + heartbeat offline + 選配 ntfy high),恢復時再通知一次
RECONNECT_ALERT_SECONDS = float(os.getenv("INTRADAY_RECONNECT_ALERT_SECONDS", "300"))
# 連續競價中,所有訂閱代號超過此秒數沒有任何成交訊息 → 強制重連
STALL_SECONDS = float(os.getenv("INTRADAY_STALL_SECONDS", "180"))
STALL_MAX_DOUBLINGS = 4           # 連續 stall(重連後仍無成交,如休市日)門檻倍增上限:3→48 分
LIVENESS_LOG_SECONDS = 300        # 每 5 分鐘一行 liveness 遙測
# 選配:intraday/.env 設 NTFY=<topic> 即推 ntfy(與 vps/.env 同一主題);未設只寫 log + heartbeat
NTFY_TOPIC = os.getenv("NTFY")

# 交易所時間一律 UTC+8(台灣無日光節約);用成交訊息自帶時間判時段,不依賴容器 TZ
TW_TZ = timezone(timedelta(hours=8))


def is_etf_id(sid: str) -> bool:
    """台股 ETF 代號為 00 開頭(0050/0056/00878/00679B…);對齊 classify.py,個股監控不納入。"""
    s = str(sid).strip().upper()
    return s.startswith("00")


def in_continuous_trading(now: datetime) -> bool:
    """是否在連續競價時段(09:00–13:30)。試搓 / 盤後回傳 False。"""
    mins = now.hour * 60 + now.minute
    return TRADING_START_MINUTES <= mins <= TRADING_END_MINUTES


def i1_amount_threshold(state: dict, price: float) -> float:
    """依日均成交額分級的 I-1 單筆金額門檻(TWD)。"""
    turnover = float(state.get("turnover") or 0)
    if turnover <= 0:
        adv = float(state.get("adv20") or 0)
        px = float(price or state.get("last_price") or 0)
        if adv > 0 and px > 0:
            # adv20 為張;金額 ≈ 張 × 1000 股 × 現價
            turnover = adv * px * 1000
    if turnover <= 0:
        return float(I1_FALLBACK_AMOUNT)
    return max(I1_MIN_AMOUNT, min(I1_MAX_AMOUNT, turnover * I1_TURNOVER_PCT))


def format_twd_amount(amount: float) -> str:
    """適讀金額:億 / 千萬 / 百萬 / 萬。"""
    if amount >= 100_000_000:
        v = amount / 100_000_000
        return f"{v:.0f}億" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".") + "億"
    if amount >= 10_000_000:
        v = amount / 10_000_000
        return f"{v:.0f}千萬" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".") + "千萬"
    if amount >= 1_000_000:
        v = amount / 1_000_000
        return f"{v:.0f}百萬" if v >= 10 else f"{v:.1f}".rstrip("0").rstrip(".") + "百萬"
    if amount >= 10_000:
        return f"{amount / 10_000:.0f}萬"
    return f"{amount:.0f}元"


def evaluate_signals(state: dict, price: float, qty: int, now: datetime) -> list[tuple[str, str]]:
    """純函式(docs/24 §2.2 規則):依這筆成交後的狀態,回傳應觸發的 (signal_type, desc)
    列表。不做任何 I/O、不碰 asyncio/Supabase,方便單元測試——process_trade 只負責
    更新 state 與呼叫這支函式,推播交給呼叫端。

    試搓(09:00 前)不產生任何訊號。
    """
    if not in_continuous_trading(now):
        return []

    signals = []
    amount = price * qty * 1000  # 成交金額(TWD)

    # I-1 大單:依日均成交額分級(中小型下限 80 萬,大型上限 500 萬)
    thr = i1_amount_threshold(state, price)
    if amount >= thr:
        signals.append(("I-1", f"單筆大單 {format_twd_amount(amount)}(門檻{format_twd_amount(thr)})"))

    # I-2 爆量:累積量 vs 依開盤至今經過時間等比例換算的 ADV20 基準,達 2 倍
    # (docs/24 §2.2 原設計要「同時刻量能基準曲線」,pipeline 尚未輸出這份曲線——
    #  這裡用單一 adv20 日均量依開盤經過分鐘數等比例折算近似,先求有訊號可用,
    #  之後 pipeline 補時刻曲線再替換成精確版)
    elapsed_min = now.hour * 60 + now.minute - TRADING_START_MINUTES
    if state.get("adv20", 0) > 0 and elapsed_min >= I2_MIN_ELAPSED_MINUTES:
        expected_by_now = state["adv20"] * min(elapsed_min, TRADING_SESSION_MINUTES) / TRADING_SESSION_MINUTES
        if expected_by_now > 0 and state["volume"] / expected_by_now >= 2.0:
            signals.append(("I-2", f"量能達今日預期 {state['volume']/expected_by_now:.1f} 倍"))

    # I-3 急拉:5 分鐘漲幅 >= 2%
    if state["trades_5m"]:
        min_price = min(p for _, p in state["trades_5m"])
        if min_price > 0 and (price - min_price) / min_price >= 0.02:
            signals.append(("I-3", "5分鐘急拉 >=2%"))

    # I-4 發動:突破觀察價
    if state["watch_price"] > 0 and price >= state["watch_price"]:
        signals.append(("I-4", f"突破觀察價 {state['watch_price']}"))

    return signals


def _build_radar_headers():
    """組出抓 radar.json 用的 headers。

    必帶 X-Radar-Service-Key(WP-B7 Worker 門鎖)。Access 過渡期可同時夾帶 CF_ACCESS_*。
    """
    headers = {"User-Agent": HTTP_USER_AGENT}
    if RADAR_SERVICE_KEY:
        headers["X-Radar-Service-Key"] = RADAR_SERVICE_KEY
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = CF_ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = CF_ACCESS_CLIENT_SECRET
    return headers


def fetch_radar_data():
    """以 HTTP 向正式站抓取 radar.json,失敗退避重試 HTTP_RETRIES 次。

    成功回傳解析後的 dict;全數失敗回傳 None(由呼叫端決定沿用上次名單或 fatal)。
    """
    headers = _build_radar_headers()
    last_err = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            resp = requests.get(RADAR_JSON_URL, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"{resp.status_code} from {RADAR_JSON_URL} — 請於 .env 設定正確的 "
                    "RADAR_SERVICE_KEY(與 wrangler secret 同一把);"
                    "若 Cloudflare Access 尚未關閉,另需 CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET"
                )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_err = e
            logger.warning(f"Fetch radar.json attempt {attempt}/{HTTP_RETRIES} failed: {e}")
            if attempt < HTTP_RETRIES:
                time.sleep(2 ** attempt)  # 退避:2s, 4s
    logger.error(f"Failed to fetch radar.json after {HTTP_RETRIES} attempts: {last_err}")
    return None


def fetch_approved_user_ids() -> set[str] | None:
    """讀取 app_profiles.status = 'approved' 的 user_id。

    service_role 繞過 RLS,核准過濾必須在這裡明確做。讀取失敗回傳 None(呼叫端須 fail closed)。
    """
    try:
        res = (
            supabase.table("app_profiles")
            .select("user_id,status")
            .eq("status", "approved")
            .execute()
        )
    except Exception as e:
        logger.error("Failed to fetch approved app_profiles; watchlist pool disabled: %s", e)
        return None
    approved: set[str] = set()
    for row in res.data or []:
        row = row or {}
        # 再驗一次 status:伺服端過濾為主,這裡防查詢條件被改壞時回傳非核准列
        if row.get("status") == "approved" and row.get("user_id"):
            approved.add(str(row["user_id"]))
    return approved


def fetch_watchlist_ids() -> list[str]:
    """以 service_role 讀取「已核准使用者」的自選代號(私人測試版通常一人或少數)。

    只納入 app_profiles.status = 'approved' 的 user_id:pending/rejected 帳號的自選列
    不得影響盤中監控池(會消耗 Fugle 訂閱額度並觸發推播)。
    app_profiles 讀取失敗 → fail closed 回傳空列表(絕不退回讀全部列);
    任一失敗都不中斷 Armed 監控。
    """
    if supabase is None:
        return []
    approved = fetch_approved_user_ids()
    if not approved:
        if approved is not None:
            logger.info("No approved users; watchlist pool empty.")
        return []
    try:
        res = (
            supabase.table("watchlist")
            .select("stock_id,user_id")
            .in_("user_id", sorted(approved))
            .execute()
        )
        out: list[str] = []
        seen: set[str] = set()
        for row in res.data or []:
            row = row or {}
            # 再驗一次 user_id:伺服端 in_ 過濾為主,這裡防禦性二次確認
            if str(row.get("user_id") or "") not in approved:
                continue
            sid = row.get("stock_id")
            if sid and sid not in seen:
                seen.add(sid)
                out.append(str(sid))
        return out
    except Exception as e:
        logger.error("Failed to fetch watchlist ids: %s", e)
        return []


def _entry_from_stock(sid: str, stock: dict | None, pool: str) -> dict:
    s = stock or {}
    scores = s.get("scores") or {}
    # radar.json 用 technical/scores;舊測試夾具可能用 tech
    tech = s.get("tech") or s.get("technical") or {}
    watch_price = (
        scores.get("watch_price")
        or tech.get("watch_price")
        or s.get("watch_price")
        or s.get("close")
        or 0
    )
    adv20 = tech.get("adv20") or s.get("adv20") or 0
    if not adv20:
        # 由今日量 / 量比回推 20 日均量(張)
        vr = s.get("volume_ratio")
        vl = s.get("volume_lots")
        if vr and vl and float(vr) > 0:
            adv20 = float(vl) / float(vr)
    turnover = s.get("turnover") or 0
    return {
        "name": s.get("name") or sid,
        "watch_price": watch_price,
        "adv20": adv20,
        "turnover": turnover,
        "last_price": 0,
        "volume": 0,
        "trades_5m": [],
        "pool": pool,
    }


def load_armed_list():
    """從遠端 radar.json 讀取今日 Armed,並合併 Supabase 自選進監控池。

    抓取失敗時:
      - 若記憶體已有上一次成功抓到的名單 → 沿用該名單繼續跑(不清空)。
      - 若首次抓取即失敗(尚無任何名單）→ fatal exit,訊息指引檢查 URL / Access token。
    """
    radar_data = fetch_radar_data()
    if radar_data is None:
        if armed_stocks:
            logger.warning("沿用上一次成功抓取的監控名單(本次抓取失敗,共 %d 檔）。", len(armed_stocks))
            return
        logger.error(
            "首次抓取 radar.json 即失敗,無法取得監控名單。"
            f" 請確認 RADAR_JSON_URL ({RADAR_JSON_URL}) 可連線,"
            " 以及 .env 的 RADAR_SERVICE_KEY 與 wrangler secret 一致;"
            " 若 Access 尚未關閉,另檢查 CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET。"
        )
        raise SystemExit(1)

    raw_armed = [str(x) for x in radar_data.get("lists", {}).get("armed", [])]
    raw_watch = fetch_watchlist_ids()
    etf_skipped = [s for s in raw_armed + raw_watch if is_etf_id(s)]
    if etf_skipped:
        logger.info("略過 ETF 不納入監控: %s", ",".join(sorted(set(etf_skipped))))

    armed_ids = [s for s in raw_armed if not is_etf_id(s)]
    stocks = {s["id"]: s for s in radar_data.get("stocks", []) if s.get("id")}
    watch_ids = [s for s in raw_watch if not is_etf_id(s)]
    armed_set = set(armed_ids)
    watch_set = set(watch_ids)

    # 未發動優先,再接自選;聯集截斷 MAX_MONITOR
    ordered: list[str] = []
    for sid in armed_ids:
        if sid not in ordered:
            ordered.append(sid)
    for sid in watch_ids:
        if sid not in ordered:
            ordered.append(sid)
    truncated = ordered[MAX_MONITOR:]
    ordered = ordered[:MAX_MONITOR]
    if truncated:
        logger.warning(
            "監控池超過上限 %d,略過 %d 檔(自選末段優先被裁)。",
            MAX_MONITOR,
            len(truncated),
        )

    new_armed: dict = {}
    for sid in ordered:
        in_a = sid in armed_set
        in_w = sid in watch_set
        if in_a and in_w:
            pool = "both"
        elif in_a:
            pool = "armed"
        else:
            pool = "watchlist"
        # 保留盤中已累積的量/價(重整名單時不歸零,避免 I-2 失真)
        prev = armed_stocks.get(sid)
        entry = _entry_from_stock(sid, stocks.get(sid), pool)
        if prev:
            entry["last_price"] = prev.get("last_price", 0)
            entry["volume"] = prev.get("volume", 0)
            entry["trades_5m"] = prev.get("trades_5m", [])
        new_armed[sid] = entry

    armed_stocks.clear()
    armed_stocks.update(new_armed)
    n_a = sum(1 for v in new_armed.values() if v["pool"] in ("armed", "both"))
    n_w = sum(1 for v in new_armed.values() if v["pool"] in ("watchlist", "both"))
    logger.info(
        "Loaded %d monitor stocks (armed≈%d, watchlist≈%d, cap=%d).",
        len(armed_stocks),
        n_a,
        n_w,
        MAX_MONITOR,
    )


def push_signal(stock_id: str, stock_name: str, signal_type: str, signal_desc: str, price: float, volume: int, pool: str = "armed"):
    """將訊號寫入 Supabase。

    2026-07-17 回歸:這支原本是 async def,呼叫端用 asyncio.create_task() 排程。
    但 process_trade() 是 Fugle SDK 內部背景執行緒呼叫的同步 callback(connect()/
    subscribe() 是同步方法,見下方 main() 的說明),該執行緒沒有 asyncio 事件迴圈,
    asyncio.create_task() 在那裡一律 RuntimeError('no running event loop')——線上
    連續數百筆全部被 process_trade() 最外層 except 吞掉,訊號 100% 送不出去(worker
    heartbeat 正常是因為心跳跑在主執行緒的事件迴圈,不受影響)。supabase-py 本身是
    同步 client、函式體內從未 await 任何東西,改普通同步函式、由 process_trade()
    直接呼叫即可,不需要事件迴圈。
    """
    signal_key = f"{stock_id}_{signal_type}"
    if signal_key in sent_signals:
        # Avoid spamming the same signal within the session
        return

    pool_tag = POOL_LABEL.get(pool, pool)
    full_desc = f"{signal_desc} · 來源:{pool_tag}"
    logger.info(f"🚨 [SIGNAL {signal_type}] {stock_name} ({stock_id}) - {full_desc} @ {price}")
    try:
        data = {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "signal_type": signal_type,
            "signal_desc": full_desc,
            "price": price,
            "volume": volume
        }
        supabase.table("intraday_signals").insert(data).execute()
        sent_signals.add(signal_key)
    except Exception as e:
        logger.error(f"Failed to push signal to Supabase: {e}")

def upsert_heartbeat(status: str) -> None:
    """寫入 heartbeat;若尚未跑 additive SQL(無 monitor_* 欄)則降級只寫舊欄位。"""
    base = {
        "id": 1,
        "status": status,
        "last_active_at": datetime.now(timezone.utc).isoformat(),
    }
    full = {
        **base,
        "monitor_used": len(armed_stocks),
        "monitor_cap": MAX_MONITOR,
    }
    try:
        supabase.table("worker_heartbeat").upsert(full).execute()
    except Exception as e:
        msg = str(e)
        if "monitor_cap" in msg or "monitor_used" in msg or "PGRST204" in msg:
            logger.warning(
                "heartbeat 無 monitor_* 欄位,降級寫入(請執行 docs/sql/20260821145158_add_worker_heartbeat_monitor_cap.sql): %s",
                e,
            )
            supabase.table("worker_heartbeat").upsert(base).execute()
        else:
            raise


def notify_ntfy(message: str, title: str, priority: str = "high") -> None:
    """選配 ntfy 推播(intraday/.env 設 NTFY 才送);失敗只記 log,不影響監控。

    標題含中文:用 query 參數而非 HTTP header(requests 以 latin-1 編 header 會炸)。
    """
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            params={"title": title, "priority": priority},
            data=message.encode("utf-8"),
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        logger.warning("ntfy push failed: %s", e)


class FeedStats:
    """逐筆成交 liveness 計數(SDK 背景執行緒寫、主迴圈讀,需上鎖)。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.trades = 0
            self.symbols: set[str] = set()
            self.last_trade_wall: datetime | None = None
            self.last_trade_mono: float | None = None

    def record(self, sid: str, mono: float, wall: datetime) -> None:
        with self._lock:
            self.trades += 1
            self.symbols.add(sid)
            self.last_trade_wall = wall
            self.last_trade_mono = mono

    def take_window(self) -> tuple[int, int, datetime | None]:
        """回傳本窗 (成交筆數, 有成交代號數, 最後成交時間) 並歸零窗內計數(最後成交時間保留)。"""
        with self._lock:
            out = (self.trades, len(self.symbols), self.last_trade_wall)
            self.trades = 0
            self.symbols = set()
            return out


feed_stats = FeedStats()


def format_liveness(trades: int, symbols: int, last_trade_at: datetime | None, reconnects: int) -> str:
    last = last_trade_at.strftime("%H:%M:%S") if last_trade_at else "-"
    return (
        f"liveness trades_5m={trades} symbols_with_trades={symbols} "
        f"last_trade_at={last} reconnects={reconnects}"
    )


def _abort_connect(client, reason: str) -> None:
    """解開 SDK connect() 的忙等迴圈:它只看 auth_status,連線失敗(on_open 沒發生)
    時會永遠卡住。這裡把狀態設成 UNAUTHENTICATED + error,讓 connect() 自己 raise。"""
    try:
        if getattr(client, "auth_status", None) != _AUTHENTICATED:
            client.error = ConnectionError(reason)
            client.auth_status = _UNAUTHENTICATED
    except Exception:
        pass


# fugle_marketdata.websocket.client.AuthenticationState 的值(避免依賴 SDK 內部模組路徑)
_AUTHENTICATED = 2
_UNAUTHENTICATED = 3


class FeedSupervisor:
    """管理 Fugle WebSocket 連線:斷線偵測、指數退避重連、重訂閱、stall 看門狗、告警。

    SDK callback 跑在背景執行緒;tick() 由主迴圈(經 asyncio.to_thread)定期呼叫。
    每次連線換一個新 client 與 generation 編號,舊 client 的遲到 callback 一律忽略。
    """

    def __init__(
        self,
        client_factory,
        *,
        on_message=None,
        stats: FeedStats | None = None,
        notifier=notify_ntfy,
        heartbeat=None,
        mono=time.monotonic,
        wall=datetime.now,
        rng=random.random,
        sleep=time.sleep,
        backoff_base: float = RECONNECT_BACKOFF_BASE,
        backoff_cap: float = RECONNECT_BACKOFF_CAP,
        alert_after: float = RECONNECT_ALERT_SECONDS,
        stall_seconds: float = STALL_SECONDS,
        connect_timeout: float = CONNECT_TIMEOUT,
        subscribe_delay: float = 0.1,
    ):
        self._factory = client_factory
        self._on_message = on_message or process_trade
        self._stats = stats or feed_stats
        self._notify = notifier
        self._heartbeat = heartbeat
        self._mono = mono
        self._wall = wall
        self._rng = rng
        self._sleep = sleep
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.alert_after = alert_after
        self.stall_seconds = stall_seconds
        self.connect_timeout = connect_timeout
        self.subscribe_delay = subscribe_delay

        self._lock = threading.Lock()
        self.client = None
        self.generation = 0
        self.connected = False
        self.closing = False
        self.ever_connected = False
        self.connected_mono: float | None = None
        self.down_since: float | None = None   # 首次連線前視為 down(從建構時算)
        self.down_reason = "initial connect"
        self.failures = 0
        self.next_attempt_at = 0.0
        self.reconnects = 0
        self.alerted = False
        self.stall_strikes = 0
        self._session_mono: float | None = None  # 首次觀察到連續競價的時刻(stall 起算下限)

    # ---------- SDK callbacks(背景執行緒)----------
    def _handle_message(self, gen: int, msg) -> None:
        if gen != self.generation:
            return
        self._on_message(msg)

    def _handle_down(self, gen: int, reason: str) -> None:
        with self._lock:
            if gen != self.generation or self.closing:
                return
            client = self.client
            if not self.connected:
                # 連線/驗證中就出錯:解開 SDK connect() 的忙等
                _abort_connect(client, reason)
                return
            self.connected = False
            self.down_since = self._mono()
            self.down_reason = reason
            self.failures = 0
            self.next_attempt_at = self.down_since  # 第一次立即重試,之後才退避
        logger.error("Fugle WebSocket down (%s); reconnecting…", reason)

    def _bind(self, client, gen: int) -> None:
        client.on("message", lambda msg: self._handle_message(gen, msg))
        client.on("disconnect", lambda code=None, msg=None, *a: self._handle_down(gen, f"disconnect code={code} msg={msg}"))
        # 必須掛 error listener:pyee 對無人接的 'error' 事件會 raise(正式 log 的
        # "error from callback <…__on_error…>" 即此),連線失敗時 SDK 隨後會再發 disconnect
        client.on("error", lambda err=None, *a: self._handle_down(gen, f"error {err}"))

    # ---------- 連線 ----------
    def backoff_delay(self, failures: int) -> float:
        """第 n 次連續失敗後的等待秒數:2,4,8,…,60(上限),加 0–25% jitter 後仍不超過上限。"""
        raw = min(self.backoff_cap, self.backoff_base * (2 ** max(0, failures - 1)))
        return min(self.backoff_cap, raw * (1 + 0.25 * self._rng()))

    def _connect_once(self) -> int:
        """建立新連線並訂閱全部監控代號;回傳訂閱檔數。失敗 raise。"""
        with self._lock:
            self.generation += 1
            gen = self.generation
            client = self._factory()
            self.client = client
        self._bind(client, gen)
        timer = threading.Timer(self.connect_timeout, _abort_connect, args=(client, "connect timeout"))
        timer.daemon = True
        timer.start()
        try:
            client.connect()  # SDK 同步方法:阻塞到驗證成功或失敗
        except Exception as e:
            # SDK 失敗路徑常以 AttributeError('NoneType'…cancel)結尾,真因在 client.error
            # (須在 disconnect() 前讀,disconnect 會把 error 清掉)
            cause = getattr(client, "error", None)
            try:
                client.disconnect()
            except Exception:
                pass
            raise ConnectionError(str(cause or e)) from e
        finally:
            timer.cancel()
        with self._lock:
            if gen != self.generation:
                raise ConnectionError("superseded")
            self.connected = True
            self.connected_mono = self._mono()
        _subscribed_symbols.clear()
        return self.subscribe_new()

    def subscribe_new(self) -> int:
        """訂閱監控池中尚未訂閱的代號(重整名單時增量;重連時已清空故全訂)。"""
        n = 0
        client = self.client
        if client is None or not self.connected:
            return 0
        for sid in list(armed_stocks.keys()):
            if sid in _subscribed_symbols:
                continue
            logger.info("Subscribing %s...", sid)
            client.subscribe({"channel": "trades", "symbol": sid})
            _subscribed_symbols.add(sid)
            n += 1
            if self.subscribe_delay:
                self._sleep(self.subscribe_delay)  # 避免觸發 Fugle WS rate limit
        return n

    def _attempt(self, now_mono: float) -> None:
        is_reconnect = self.ever_connected
        try:
            n = self._connect_once()
        except Exception as e:
            self.failures += 1
            delay = self.backoff_delay(self.failures)
            self.next_attempt_at = now_mono + delay
            logger.warning(
                "Fugle WebSocket connect failed (attempt %d): %s; retry in %.1fs",
                self.failures, e, delay,
            )
            return
        down_for = now_mono - self.down_since if self.down_since is not None else 0.0
        self.ever_connected = True
        self.failures = 0
        self.down_since = None
        if is_reconnect:
            self.reconnects += 1
            logger.info(
                "Fugle WebSocket reconnected after %.0fs (reason: %s); resubscribed %d symbols; reconnects=%d",
                down_for, self.down_reason, n, self.reconnects,
            )
        else:
            logger.info("Fugle WebSocket connected; subscribed %d symbols.", n)
        if self.alerted:
            self.alerted = False
            msg = f"盤中監控 Fugle 連線已恢復(中斷 {down_for:.0f}s,重訂 {n} 檔)"
            logger.info(msg)
            self._notify(msg, "盤中監控 · 恢復", "default")
            self._push_heartbeat()

    def _push_heartbeat(self) -> None:
        if self._heartbeat is None:
            return
        try:
            self._heartbeat(self.heartbeat_status())
        except Exception as e:
            logger.error("Heartbeat failed: %s", e)

    def force_reconnect(self, reason: str) -> None:
        with self._lock:
            if not self.connected:
                return
            self.connected = False
            self.down_since = self._mono()
            self.down_reason = reason
            self.failures = 0
            self.next_attempt_at = self.down_since
            self.generation += 1  # 舊 client 的 close callback 之後一律忽略
            client = self.client
        logger.warning("Forcing Fugle WebSocket reconnect: %s", reason)
        try:
            client.disconnect()
        except Exception as e:
            logger.warning("disconnect during forced reconnect failed: %s", e)

    def stall_threshold(self) -> float:
        return self.stall_seconds * (2 ** min(self.stall_strikes, STALL_MAX_DOUBLINGS))

    def _check_stall(self, now_wall: datetime, now_mono: float) -> None:
        if not in_continuous_trading(now_wall):
            return
        if not _subscribed_symbols:
            return
        last_trade = self._stats.last_trade_mono
        if last_trade is not None and self.connected_mono is not None and last_trade > self.connected_mono:
            self.stall_strikes = 0  # 這條連線有收到成交 → 門檻回到基準
        ref = max(x for x in (last_trade, self.connected_mono, self._session_mono) if x is not None)
        idle = now_mono - ref
        threshold = self.stall_threshold()
        if idle > threshold:
            self.stall_strikes += 1
            self.force_reconnect(
                f"stall: no trade message for {idle:.0f}s (> {threshold:.0f}s) on {len(_subscribed_symbols)} symbols"
            )

    def tick(self) -> None:
        """主迴圈每秒呼叫:健康連線查 stall;斷線時依退避排程重連;斷太久告警一次。"""
        if self.closing:
            return
        now_mono = self._mono()
        now_wall = self._wall()
        if self._session_mono is None and in_continuous_trading(now_wall):
            self._session_mono = now_mono
        if self.down_since is None and not self.ever_connected:
            self.down_since = now_mono
        if self.connected:
            self._check_stall(now_wall, now_mono)
            if self.connected:
                return
        if now_mono >= self.next_attempt_at:
            self._attempt(now_mono)
        if (
            not self.connected
            and not self.alerted
            and self.down_since is not None
            and now_mono - self.down_since >= self.alert_after
        ):
            self.alerted = True
            down_for = now_mono - self.down_since
            msg = (
                f"盤中監控 Fugle WebSocket 已中斷 {down_for:.0f}s、重連 {self.failures} 次仍失敗"
                f"(原因:{self.down_reason});盤中訊號暫停,持續重試至 13:35"
            )
            logger.error(msg)
            self._notify(msg, "盤中監控 · 失敗", "high")
            self._push_heartbeat()

    def heartbeat_status(self) -> str:
        """worker_heartbeat.status:前端只把 'offline' 視為離線,其餘看 last_active_at 新鮮度。"""
        if self.connected:
            return "online"
        return "offline" if self.alerted else "reconnecting"

    def shutdown(self) -> None:
        with self._lock:
            self.closing = True
            self.connected = False
            client = self.client
        if client is not None:
            try:
                client.disconnect()  # SDK 同步方法
            except Exception as e:
                logger.warning("disconnect on shutdown failed: %s", e)


_feed: FeedSupervisor | None = None  # main() 建立;update_heartbeat 讀連線狀態


async def update_heartbeat():
    """定期更新 Worker 存活狀態 + 監控額度(used/cap)。斷線中寫 reconnecting/offline。"""
    while True:
        try:
            upsert_heartbeat(_feed.heartbeat_status() if _feed is not None else "online")
            logger.debug("Heartbeat updated.")
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
        await asyncio.sleep(30)


def _trade_time(data: dict) -> datetime | None:
    """Fugle trades.time 為 epoch 微秒;轉成台灣本地 naive datetime 以便與時段比較。"""
    t = data.get("time")
    if not isinstance(t, (int, float)) or t <= 0:
        return None
    try:
        return datetime.fromtimestamp(t / 1_000_000, TW_TZ).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def process_trade(message):
    """處理逐筆成交並判定訊號"""
    try:
        # Fugle WebSocket Trade format (v1.0):
        # https://developer.fugle.tw/docs/data/websocket-api/market-data-channels/trades
        # size=成交單量(本筆,張)、volume=成交總量(累計,張)、time=微秒、isTrial=試撮
        # SDK 的 on("message") 給的是原始字串,不是已解析的 dict,需自行 json.loads
        if isinstance(message, str):
            message = json.loads(message)
        event = message.get("event")
        if event == "error":
            logger.warning("Fugle WS error message: %s", message.get("data"))
            return
        if event != "data": return

        data = message.get("data") or {}
        sid = data.get("symbol")
        if sid not in armed_stocks: return

        now = datetime.now()
        # liveness:試撮也算(證明資料流活著),訊號與狀態另行把關
        feed_stats.record(sid, time.monotonic(), now)

        # 試撮(08:30–09:00 / 13:25–13:30)、時段外成交:完全不碰狀態、不推訊號。
        # 同時以牆鐘與成交自帶時間把關,容器 TZ 設錯也不會在試撮出訊號。
        trade_dt = _trade_time(data)
        if data.get("isTrial") or not in_continuous_trading(now):
            return
        if trade_dt is not None and not in_continuous_trading(trade_dt):
            return

        price = data.get("price") or 0
        qty = data.get("size") or 0          # 本筆成交量(張)
        cum = data.get("volume")             # 當日累計成交量(張)

        state = armed_stocks[sid]
        state["last_price"] = price
        if isinstance(cum, (int, float)):
            # 以交易所累計量為準(舊碼把累計量當本筆量相加,I-1/I-2 嚴重高估)
            state["volume"] = max(state["volume"], cum)
        else:
            state["volume"] += qty

        # 紀錄最近 5 分鐘的價格用於急拉計算
        state["trades_5m"].append((now, price))
        # 清理 5 分鐘前的紀錄
        state["trades_5m"] = [(t, p) for t, p in state["trades_5m"] if now - t <= timedelta(minutes=5)]

        for signal_type, desc in evaluate_signals(state, price, qty, now):
            push_signal(
                sid,
                state["name"],
                signal_type,
                desc,
                price,
                state["volume"],
                pool=state.get("pool", "armed"),
            )

    except Exception as e:
        logger.error(f"Error processing trade: {e}", exc_info=True)


async def main():
    global supabase
    logger.info("Starting Intraday Radar Worker...")

    # 缺任一關鍵金鑰 → fatal exit(僅 .env 提供,絕不硬編)
    if not FUGLE_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Missing FUGLE_API_KEY, SUPABASE_URL, or SUPABASE_KEY in .env — 請確認 .env 已正確設定")
        raise SystemExit(1)

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    if past_close(datetime.now()):
        # 13:35 之後啟動(煙測/誤觸)不連線,直接標離線退出
        logger.info("Already past market close. Shutting down worker.")
        upsert_heartbeat("offline")
        return

    load_armed_list()
    if not armed_stocks:
        logger.warning("No stocks to monitor (armed+watchlist empty). Exiting.")
        return

    global _feed
    # SDK 的 connect()/subscribe() 是同步方法(內部自行處理連線執行緒),不是 coroutine;
    # 每次(重)連都建立新 client,避免沿用已關閉 WebSocketApp 的內部狀態
    _feed = FeedSupervisor(
        lambda: WebSocketClient(api_key=FUGLE_API_KEY).stock,
        heartbeat=upsert_heartbeat,
    )

    # Start Heartbeat background task
    asyncio.create_task(update_heartbeat())

    logger.info("Connecting to Fugle WebSocket...")
    await run_session(_feed)
    upsert_heartbeat("offline")


def past_close(now: datetime) -> bool:
    # 13:35 起收工;14:00 之後啟動(煙測/誤觸)也應立刻退出
    return now.hour > 13 or (now.hour == 13 and now.minute >= 35)


async def run_session(
    feed: FeedSupervisor,
    *,
    now_fn=datetime.now,
    mono_fn=time.monotonic,
    sleep_fn=asyncio.sleep,
    reload_fn=None,
    tick_interval: float = 1.0,
) -> None:
    """主迴圈:直到 13:35 前持續 tick(連線/重連/stall)、每 5 分重整名單與 liveness 遙測。
    斷線絕不提早結束程序;13:35 收工時關閉連線。"""
    reload_fn = reload_fn or load_armed_list
    last_reload = mono_fn()
    last_liveness = mono_fn()
    try:
        while True:
            if past_close(now_fn()):
                logger.info("Market closed. Shutting down worker.")
                break
            # tick 內 SDK connect() 會阻塞(忙等驗證),丟到執行緒避免卡住 heartbeat
            await asyncio.to_thread(feed.tick)
            mono = mono_fn()
            if mono - last_reload >= 300:
                try:
                    reload_fn()
                    await asyncio.to_thread(feed.subscribe_new)
                except SystemExit:
                    logger.warning("監控名單重整失敗(fatal),沿用現有訂閱繼續。")
                except Exception as e:
                    logger.error("監控名單重整失敗: %s", e)
                last_reload = mono
            if mono - last_liveness >= LIVENESS_LOG_SECONDS:
                trades, k, last_at = feed_stats.take_window()
                logger.info(format_liveness(trades, k, last_at, feed.reconnects))
                last_liveness = mono
            await sleep_fn(tick_interval)
    finally:
        feed.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
