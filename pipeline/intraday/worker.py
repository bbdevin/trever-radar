import os
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
RADAR_JSON_URL = os.getenv("RADAR_JSON_URL", "https://trever-radar.pages.dev/data/radar.json")
# Cloudflare Access 服務權杖(預留):docs/21 Access 上線後 /data/radar.json 會被保護,
# 屆時於 .env 補上這兩把 token,worker 會自動夾帶 header 穿透 Access;未設則以公開方式抓取。
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
armed_stocks = {}  # { '2330': { 'name': '台積電', 'watch_price': 1000, 'adv20': 50000, 'last_price': 0, 'volume': 0, 'trades_5m': [] } }
sent_signals = set() # To avoid spamming the same signal for the same stock


def _build_radar_headers():
    """組出抓 radar.json 用的 headers;若 .env 提供 Cloudflare Access token 則一併夾帶。"""
    headers = {"User-Agent": HTTP_USER_AGENT}
    if CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET:
        # docs/21 Cloudflare Access 上線後穿透 /data/radar.json 保護用
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
            if resp.status_code == 403:
                # Access 保護生效但未帶 / 帶錯 service token
                raise RuntimeError(
                    f"403 Forbidden from {RADAR_JSON_URL} — 若 Cloudflare Access (docs/21) 已上線,"
                    "請於 .env 設定正確的 CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET"
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


def load_armed_list():
    """從遠端 radar.json 讀取昨日的 Armed 名單與相關基準數據。

    抓取失敗時:
      - 若記憶體已有上一次成功抓到的名單 → 沿用該名單繼續跑(不清空)。
      - 若首次抓取即失敗(尚無任何名單）→ fatal exit,訊息指引檢查 URL / Access token。
    """
    radar_data = fetch_radar_data()
    if radar_data is None:
        if armed_stocks:
            logger.warning("沿用上一次成功抓取的 Armed 名單(本次抓取失敗,共 %d 檔）。", len(armed_stocks))
            return
        logger.error(
            "首次抓取 radar.json 即失敗,無法取得 Armed 名單。"
            f" 請確認 RADAR_JSON_URL ({RADAR_JSON_URL}) 可連線;"
            " 若 Cloudflare Access (docs/21) 已上線,請檢查 .env 的 "
            "CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET 是否正確。"
        )
        raise SystemExit(1)

    # 先組出新名單,抓取成功才整批替換,避免半途覆寫掉可用的舊名單
    new_armed = {}
    armed_ids = radar_data.get('lists', {}).get('armed', [])
    stocks = {s['id']: s for s in radar_data.get('stocks', [])}

    for sid in armed_ids:
        if sid in stocks:
            s = stocks[sid]
            # 取得 watch_price, 如果沒有則取昨日收盤價 (close) 作為暫代
            tech = s.get('tech', {})
            watch_price = tech.get('watch_price', s.get('close', 0))
            adv20 = tech.get('adv20', 0)

            new_armed[sid] = {
                'name': s.get('name', ''),
                'watch_price': watch_price,
                'adv20': adv20,
                'last_price': 0,
                'volume': 0,
                'trades_5m': []  # store (timestamp, price)
            }

    armed_stocks.clear()
    armed_stocks.update(new_armed)
    logger.info(f"Loaded {len(armed_stocks)} Armed stocks to monitor.")

async def push_signal(stock_id: str, stock_name: str, signal_type: str, signal_desc: str, price: float, volume: int):
    """將訊號寫入 Supabase"""
    signal_key = f"{stock_id}_{signal_type}"
    if signal_key in sent_signals:
        # Avoid spamming the same signal within the session
        return

    logger.info(f"🚨 [SIGNAL {signal_type}] {stock_name} ({stock_id}) - {signal_desc} @ {price}")
    try:
        data = {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "signal_type": signal_type,
            "signal_desc": signal_desc,
            "price": price,
            "volume": volume
        }
        supabase.table("intraday_signals").insert(data).execute()
        sent_signals.add(signal_key)
    except Exception as e:
        logger.error(f"Failed to push signal to Supabase: {e}")

async def update_heartbeat():
    """定期更新 Worker 存活狀態"""
    while True:
        try:
            supabase.table("worker_heartbeat").upsert({"id": 1, "status": "online", "last_active_at": datetime.now(timezone.utc).isoformat()}).execute()
            logger.debug("Heartbeat updated.")
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
        await asyncio.sleep(30)

def process_trade(message):
    """處理逐筆成交並判定訊號"""
    try:
        # Fugle WebSocket Trade format (v1.0):
        # https://developer.fugle.tw/docs/marketdata/websocket/streaming/trades
        event = message.get("event")
        if event != "data": return

        data = message.get("data", {})
        sid = data.get("symbol")
        if sid not in armed_stocks: return

        price = data.get("price", 0)
        qty = data.get("volume", 0)

        state = armed_stocks[sid]
        state['last_price'] = price
        state['volume'] += qty

        amount = price * qty * 1000 # 成交金額 (TWD)

        # 紀錄最近 5 分鐘的價格用於急拉計算
        now = datetime.now()
        state['trades_5m'].append((now, price))
        # 清理 5 分鐘前的紀錄
        state['trades_5m'] = [(t, p) for t, p in state['trades_5m'] if now - t <= timedelta(minutes=5)]

        # 判定 I-1 (大單): 單筆大於 500 萬
        if amount >= 5000000:
            asyncio.create_task(push_signal(sid, state['name'], "I-1", f"單筆大單 {amount/10000:.0f}萬", price, state['volume']))

        # 判定 I-3 (急拉): 5分鐘漲幅 >= 2%
        if len(state['trades_5m']) > 0:
            min_price = min(p for t, p in state['trades_5m'])
            if min_price > 0 and (price - min_price) / min_price >= 0.02:
                asyncio.create_task(push_signal(sid, state['name'], "I-3", "5分鐘急拉 >=2%", price, state['volume']))

        # 判定 I-4 (發動): 突破觀察價且有動能 (這裡簡化為只要突破且不是剛開盤)
        if state['watch_price'] > 0 and price >= state['watch_price']:
            asyncio.create_task(push_signal(sid, state['name'], "I-4", f"突破觀察價 {state['watch_price']}", price, state['volume']))

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
        logger.warning("No Armed stocks to monitor. Exiting.")
        return

    # Start Heartbeat background task
    asyncio.create_task(update_heartbeat())

    logger.info("Connecting to Fugle WebSocket...")
    client = WebSocketClient(api_key=FUGLE_API_KEY)
    stock = client.stock

    stock.on('message', lambda msg: process_trade(msg))

    await stock.connect()

    # 訂閱所有 Armed 股票
    for sid in armed_stocks.keys():
        logger.info(f"Subscribing {sid}...")
        await stock.subscribe({
            'channel': 'trades',
            'symbol': sid
        })
        # 避免觸發 Fugle WS rate limit
        await asyncio.sleep(0.1)

    logger.info("All subscriptions complete. Monitoring...")

    # 保持連線，直到 13:35 (本機時間)
    while True:
        now = datetime.now()
        if now.hour == 13 and now.minute >= 35:
            logger.info("Market closed. Shutting down worker.")
            break
        await asyncio.sleep(10)

    await stock.disconnect()
    # 離線時更新 heartbeat
    supabase.table("worker_heartbeat").upsert({"id": 1, "status": "offline", "last_active_at": datetime.now(timezone.utc).isoformat()}).execute()

if __name__ == '__main__':
    asyncio.run(main())
