import os
import json
import time
import asyncio
import logging
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


def fetch_watchlist_ids() -> list[str]:
    """以 service_role 讀取所有使用者的自選代號(私人測試版通常一人或少數)。

    失敗回傳空列表,不中斷 Armed 監控。
    """
    if supabase is None:
        return []
    try:
        res = supabase.table("watchlist").select("stock_id").execute()
        out: list[str] = []
        seen: set[str] = set()
        for row in res.data or []:
            sid = (row or {}).get("stock_id")
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


async def update_heartbeat():
    """定期更新 Worker 存活狀態 + 監控額度(used/cap)。"""
    while True:
        try:
            upsert_heartbeat("online")
            logger.debug("Heartbeat updated.")
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
        await asyncio.sleep(30)

def process_trade(message):
    """處理逐筆成交並判定訊號"""
    try:
        # Fugle WebSocket Trade format (v1.0):
        # https://developer.fugle.tw/docs/marketdata/websocket/streaming/trades
        # SDK 的 on("message") 給的是原始字串,不是已解析的 dict,需自行 json.loads
        if isinstance(message, str):
            message = json.loads(message)
        event = message.get("event")
        if event != "data": return

        data = message.get("data", {})
        sid = data.get("symbol")
        if sid not in armed_stocks: return

        price = data.get("price", 0)
        qty = data.get("volume", 0)

        state = armed_stocks[sid]
        now = datetime.now()

        # 試搓(08:30–09:00)與盤後:只刷新現價,不累積量、不推訊號
        if not in_continuous_trading(now):
            state["last_price"] = price
            return

        state["last_price"] = price
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

    load_armed_list()
    if not armed_stocks:
        logger.warning("No stocks to monitor (armed+watchlist empty). Exiting.")
        return

    # Start Heartbeat background task
    asyncio.create_task(update_heartbeat())

    logger.info("Connecting to Fugle WebSocket...")
    client = WebSocketClient(api_key=FUGLE_API_KEY)
    stock = client.stock

    stock.on('message', lambda msg: process_trade(msg))

    # SDK 的 connect()/subscribe() 是同步方法(內部自行處理連線執行緒),不是 coroutine——
    # 官方範例也是直接呼叫、不加 await;await 一個非 coroutine 的回傳值(None)會直接 TypeError。
    stock.connect()

    async def subscribe_all():
        for sid in list(armed_stocks.keys()):
            if sid in _subscribed_symbols:
                continue
            logger.info("Subscribing %s...", sid)
            stock.subscribe({
                "channel": "trades",
                "symbol": sid,
            })
            _subscribed_symbols.add(sid)
            # 避免觸發 Fugle WS rate limit
            await asyncio.sleep(0.1)

    await subscribe_all()
    logger.info("All subscriptions complete. Monitoring...")

    def past_close(now: datetime) -> bool:
        # 13:35 起收工;14:00 之後啟動(煙測/誤觸)也應立刻退出
        return now.hour > 13 or (now.hour == 13 and now.minute >= 35)

    if past_close(datetime.now()):
        logger.info("Already past market close. Shutting down worker.")
        stock.disconnect()
        upsert_heartbeat("offline")
        return

    # 保持連線，直到 13:35 (本機時間);期間每 5 分重整自選/Armed 並增量訂閱
    last_reload = time.monotonic()
    while True:
        now = datetime.now()
        if past_close(now):
            logger.info("Market closed. Shutting down worker.")
            break
        if time.monotonic() - last_reload >= 300:
            try:
                load_armed_list()
                await subscribe_all()
            except SystemExit:
                logger.warning("監控名單重整失敗(fatal),沿用現有訂閱繼續。")
            except Exception as e:
                logger.error("監控名單重整失敗: %s", e)
            last_reload = time.monotonic()
        await asyncio.sleep(10)

    stock.disconnect()  # 同上,SDK 為同步方法
    # 離線時更新 heartbeat
    upsert_heartbeat("offline")

if __name__ == '__main__':
    asyncio.run(main())
