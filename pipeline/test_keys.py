import asyncio
from fugle_marketdata import RestClient
key1 = 'NTNhZDMyOGUtOGViZS00YjZlLWI4MDEtOWUzMGUzNDdjOTRmIDc3M2ZkZTZhLTVhNTctNDQwMS1hNGZkLTM0NWI0YzYyOGRhZQ=='
key2 = '53ad328e-8ebe-4b6e-b801-9e30e347c94f'
key3 = '773fde6a-5a57-4401-a4fd-345b4c628dae'

for i, k in enumerate([key1, key2, key3]):
    print(f'Testing key {i+1}...')
    try:
        c = RestClient(api_key=k)
        r = c.stock.intraday.quote(symbol='2330')
        print(f'Key {i+1} Success!')
    except Exception as e:
        print(f'Key {i+1} failed:', e)
