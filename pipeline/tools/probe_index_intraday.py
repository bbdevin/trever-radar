"""唯讀探測:大盤當日走勢(docs/49 §12.5)的來源代號與回應格式。只印、不寫任何檔、不碰 DB。

    cd pipeline
    FUGLE_API_KEY=… python tools/probe_index_intraday.py [--date YYYY-MM-DD] [--tx-month YYYYMM] [--taifex]

VPS(金鑰只在容器 env 裡;見 vps/scripts/lib.sh `radar()`):

    cd ~/stock && source vps/scripts/lib.sh && radar_secret_env_new && \
      docker run --rm --env-file "$RADAR_SECRET_ENV_FILE" -v "$REPO/pipeline":/app/pipeline \
        -w /app/pipeline radar-pipeline python tools/probe_index_intraday.py; radar_secret_env_cleanup

Fugle intraday/candles 只有**當天**,所以要在交易日 13:45 之後、隔天 08:30 之前跑。約 6 次 Fugle
請求(間隔 1.1 秒)+ 1 次 TWSE + 1 次 TAIFEX HEAD(看逐筆成交 zip 公布了沒、Last-Modified);
``--taifex`` 另下載那個 zip(~1.6 MB)解析台指期近月一般時段。看完把結果寫回 docs/49 §12.5,
代號不對就改 ``radar/export/indices_intraday.py`` 頂端的 ``FUGLE_*`` 常數。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from radar.export import indices_intraday as ii  # noqa: E402

API = "https://api.fugle.tw/marketdata/v1.0"
GAP = 1.1


def get(url: str, params: dict, headers: dict) -> tuple[int, object]:
    time.sleep(GAP)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
    except Exception as e:  # noqa: BLE001
        return -1, str(e)
    try:
        body = r.json()
    except ValueError:
        body = r.text[:300]
    return r.status_code, body


def show_rows(label: str, status: int, body) -> list:
    rows = body.get("data") if isinstance(body, dict) else None
    print(f"\n[{label}] HTTP {status}")
    if not isinstance(rows, list):
        print("  body:", json.dumps(body, ensure_ascii=False)[:400])
        return []
    meta = {k: v for k, v in body.items() if k != "data"}
    print("  meta:", json.dumps(meta, ensure_ascii=False))
    print(f"  rows={len(rows)}")
    sample = rows if len(rows) <= 4 else rows[:2] + ["…"] + rows[-2:]
    for r in sample:
        print("   ", json.dumps(r, ensure_ascii=False))
    return rows


def show_tickers(label: str, status: int, body, needles: tuple[str, ...], prefix: str = "") -> None:
    rows = body.get("data") if isinstance(body, dict) else None
    print(f"\n[{label}] HTTP {status}")
    if not isinstance(rows, list):
        print("  body:", json.dumps(body, ensure_ascii=False)[:400])
        return
    print(f"  tickers={len(rows)}")
    hits = [r for r in rows if isinstance(r, dict) and (
        any(n in str(r.get("name", "")) for n in needles)
        or (prefix and str(r.get("symbol", "")).startswith(prefix)))]
    for r in (hits or rows)[:25]:
        print("   ", json.dumps(r, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", default=ii.taipei_today())
    ap.add_argument("--tx-month", default=None, help="YYYYMM;預設取一般時段有成交的最小月份")
    ap.add_argument("--taifex", action="store_true", help="下載 TAIFEX 逐筆成交 zip(~1.6 MB)並解析台指期")
    a = ap.parse_args()
    day = a.date
    print(f"date={day} tx_month={a.tx_month or '(auto)'}")
    print(f"configured: twse={ii.FUGLE_TWSE_INDEX} tpex={ii.FUGLE_TPEX_INDEX}")

    series: dict[str, list] = {}
    key = os.environ.get("FUGLE_API_KEY")
    if not key:
        print("\nFUGLE_API_KEY 未設定:跳過 Fugle,只測 TWSE。")
    else:
        h = {"X-API-KEY": key}
        # 1) 指數代號清單
        for ex in ("TWSE", "TPEx"):
            st, body = get(f"{API}/stock/intraday/tickers", {"type": "INDEX", "exchange": ex}, h)
            show_tickers(f"stock tickers INDEX {ex}", st, body, ("加權", "櫃買", "櫃檯", "OTC"))
        # 2) 指數 1 分 K
        for market, sym in (("twse", ii.FUGLE_TWSE_INDEX), ("tpex", ii.FUGLE_TPEX_INDEX)):
            st, body = get(f"{API}/stock/intraday/ticker/{sym}", {}, h)
            print(f"\n[stock ticker {sym}] HTTP {st} ", json.dumps(body, ensure_ascii=False)[:300])
            st, body = get(f"{API}/stock/intraday/candles/{sym}", {"timeframe": ii.FUGLE_TIMEFRAME}, h)
            show_rows(f"stock candles {sym} ({market})", st, body)
            if isinstance(body, dict):
                series[market] = ii.parse_fugle_candles(body, day, market)

    # 3) 台指期:TAIFEX 逐筆成交 zip(Fugle futopt 免費方案 403,2026-10-09 probe)
    y, m, d = day.split("-")
    url = ii.TAIFEX_DAILY_URL.format(y=y, m=m, d=d)
    try:
        r = requests.head(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        print(f"\n[TAIFEX daily HEAD] HTTP {r.status_code} Content-Type={r.headers.get('Content-Type')} "
              f"Last-Modified={r.headers.get('Last-Modified')} Length={r.headers.get('Content-Length')}")
        print("  (Content-Type 不是 application/zip = 還沒公布)")
        if a.taifex:
            time.sleep(GAP)
            g = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120)
            s = ii.parse_taifex_daily_zip(g.content, day, a.tx_month)
            if s is None:
                print(f"  download: not a readable zip ({len(g.content)} B)")
            else:
                print(f"  download: {len(g.content)} B zip, {len(s)} tx minutes")
                series["tx"] = s
    except Exception as e:  # noqa: BLE001
        print(f"\n[TAIFEX daily] {e}")

    # 4) TWSE 官方每 5 秒指數(加權備援)
    st, body = 0, None
    try:
        r = requests.get(ii.TWSE_5S_URL, params={"date": day.replace("-", ""), "response": "json"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        st, body = r.status_code, r.json()
    except Exception as e:  # noqa: BLE001
        body = str(e)
    print(f"\n[TWSE MI_5MINS_INDEX] HTTP {st}")
    if isinstance(body, dict):
        rows = body.get("data") or []
        print(f"  stat={body.get('stat')} title={body.get('title')} rows={len(rows)}")
        print("  fields[:3]=", (body.get("fields") or [])[:3])
        for r in rows[:2] + rows[-2:]:
            print("   ", r[:2])
        fb = ii.parse_twse_5s(body, day)
        print(f"  → 1 分線 {len(fb)} 點,first={fb[:1]} last={fb[-1:]}")
        series.setdefault("twse_fallback", fb)
    else:
        print("  ", str(body)[:300])

    # 5) 管線會寫出的樣子(不寫檔)
    print("\n[summary] 1 分線點數(≥2 才會進檔):")
    for m, s in series.items():
        print(f"  {m}: {len(s)} 點 first={s[:1]} last={s[-1:]}")
    payload = ii.build_payload(day, {m: s for m, s in series.items() if m in ii.MARKETS})
    if payload:
        from radar.export.stock_parts import dumps_compact
        print(f"  indices_intraday.json ≈ {len(dumps_compact(payload).encode())} B raw;series={list(payload['series'])}")
    else:
        print("  indices_intraday.json:沒有任何序列(不會寫檔)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
