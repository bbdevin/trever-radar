import asyncio
from fugle_marketdata import WebSocketClient
key1 = 'NTNhZDMyOGUtOGViZS00YjZlLWI4MDEtOWUzMGUzNDdjOTRmIDc3M2ZkZTZhLTVhNTctNDQwMS1hNGZkLTM0NWI0YzYyOGRhZQ=='
async def main():
    print('Testing WebSocket with key1...')
    c = WebSocketClient(api_key=key1)
    s = c.stock
    s.on('message', lambda msg: print('WS Msg:', msg))
    await s.connect()
    await s.subscribe({'channel':'trades', 'symbol':'2330'})
    await asyncio.sleep(2)
    await s.disconnect()
    print('WebSocket test completed.')
asyncio.run(main())
