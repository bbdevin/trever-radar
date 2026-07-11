import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
from fugle_marketdata import WebSocketClient, RestClient

# --- Configuration & Setup ---
load_dotenv()
FUGLE_API_KEY = os.getenv("FUGLE_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

if not FUGLE_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("Missing FUGLE_API_KEY, SUPABASE_URL, or SUPABASE_KEY in .env")
    exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- State Management ---
armed_stocks = {}  # { '2330': { 'name': '台積電', 'watch_price': 1000, 'adv20': 50000, 'last_price': 0, 'volume': 0, 'trades_5m': [] } }
sent_signals = set() # To avoid spamming the same signal for the same stock

def load_armed_list():
    """從 radar.json 讀取昨日的 Armed 名單與相關基準數據"""
    # 假設從 web/public/data/radar.json 讀取
    file_path = os.path.join(os.path.dirname(__file__), '../../web/public/data/radar.json')
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            radar_data = json.load(f)
            
        armed_ids = radar_data.get('lists', {}).get('armed', [])
        stocks = {s['id']: s for s in radar_data.get('stocks', [])}
        
        for sid in armed_ids:
            if sid in stocks:
                s = stocks[sid]
                # 取得 watch_price, 如果沒有則取昨日收盤價 (close) 作為暫代
                tech = s.get('tech', {})
                watch_price = tech.get('watch_price', s.get('close', 0))
                adv20 = tech.get('adv20', 0)
                
                armed_stocks[sid] = {
                    'name': s.get('name', ''),
                    'watch_price': watch_price,
                    'adv20': adv20,
                    'last_price': 0,
                    'volume': 0,
                    'trades_5m': [] # store (timestamp, price)
                }
        logger.info(f"Loaded {len(armed_stocks)} Armed stocks to monitor.")
    except Exception as e:
        logger.error(f"Failed to load radar.json: {e}")

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
    logger.info("Starting Intraday Radar Worker...")
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
