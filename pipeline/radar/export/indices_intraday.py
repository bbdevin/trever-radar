"""大盤當日走勢(docs/49 §12.5):加權／櫃買／台指期近月的當日 1 分線 → ``market/indices_intraday.json``。

首頁市場概況走勢圖 sheet 的「1日」才抓這檔。內容只有最新一個交易日:

    {"date": "YYYY-MM-DD", "series": {"twse": [[epoch_s, close], …], "tpex": […], "tx": […]}}

* ``epoch_s`` 是真正的 Unix 秒(該分鐘的**開始時間**,與分K ``stocks/intraday`` 同一個慣例);
  前端照 ``chartTimeOf(twWallKey(epoch))`` 換成「台北牆上時間當 UTC」給圖表,09:00 就顯示 09:00。
* 每根 = 那一分鐘的最後一個值(1 分 K 的收盤)。缺分鐘不補。
* 某序列抓不到就不出那個鍵(前端顯示「暫無日內走勢」);三個都沒有 → 不寫檔、舊檔留著。

來源(全部免費、無驗證碼;``pipeline/tools/probe_index_intraday.py`` 為唯讀核對工具):

* 加權:Fugle ``stock/intraday/candles/IX0001``(1 分;2026-10-09 VPS probe 確認 271 列、13:30 = 官方收盤);
  失敗 → TWSE ``TAIEX/MI_5MINS_INDEX``(每 5 秒一列,一天一次請求 ~1.2 MB)聚成 1 分。
* 櫃買:Fugle ``stock/intraday/candles/IX0043``(同上確認)。TPEx 沒找到公開的盤中分鐘指數端點,無備援。
* 台指期:TAIFEX 每日逐筆成交 ``Daily_YYYY_MM_DD.zip``(全期貨、Big5 CSV,~1.6 MB zip / ~34 MB 解壓;
  一天一次)。Fugle futopt 免費方案回 403(probe 確認),不用。檔案約 16:40 才公布(Last-Modified
  2026-10-07 16:38、10-08 16:37);還沒公布時站方回 200 + HTML 錯誤頁 → 當「還沒有」,較晚的一輪再補。

閘門與 spark_day 相同:有 ``FUGLE_API_KEY`` 且台北今天 == 價格日才打來源(盤後各輪;台指期要等
16:40 之後那幾輪,例 20:00 mid-backfill-publish、20:45 資券)。
同一天已經三個都有 → 不再打(一天一次);缺哪個下一輪只補哪個。整步在 export 裡**隔離**:
``export_indices_intraday_safe`` 任何例外只記 warning。寫檔 tmp+rename,內容沒變不重寫。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .. import config
from .stock_parts import dumps_compact, write_atomic

_log = logging.getLogger(__name__)

OUT_FILE = "indices_intraday.json"
MARKETS = ("twse", "tpex", "tx")

# ── 來源代號(VPS probe 後可直接改這幾個常數) ──
FUGLE_TWSE_INDEX = "IX0001"   # 發行量加權股價指數(VPS probe 2026-10-09 確認)
FUGLE_TPEX_INDEX = "IX0043"   # 櫃買指數(VPS probe 2026-10-09 確認)
FUGLE_TIMEFRAME = "1"

FUGLE_STOCK_CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
TAIFEX_DAILY_URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/DailydownloadCSV/Daily_{y}_{m}_{d}.zip"
TAIFEX_TX_CODE = "TX"         # 商品代號(來源右側補空白;小台 MTX、微台 TMF 不算)
TWSE_5S_URL = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_INDEX"
TWSE_5S_FIELD = "發行量加權股價指數"

# 交易時段(台北牆上時間,分鐘);時段外的列丟掉
SESSION = {"twse": (9 * 60, 13 * 60 + 30), "tpex": (9 * 60, 13 * 60 + 30),
           "tx": (8 * 60 + 45, 13 * 60 + 45)}

_TPE = ZoneInfo(config.TZ)

Series = list  # [[epoch_s, close], …]


def taipei_today() -> str:
    return datetime.now(_TPE).strftime("%Y-%m-%d")


def _num(x: float) -> float | int:
    r = round(float(x), 2)
    return int(r) if r == int(r) else r


def _parse_ts(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_TPE)
    return dt.astimezone(_TPE)


def minute_series(points, day: str, market: str) -> Series:
    """(台北 datetime, 值) 序列 → 該日、該市場交易時段內的 1 分線 [[epoch_s, close]](舊→新)。

    同一分鐘多筆取**最後一筆**(時間較晚者);值 ≤ 0 或缺(來源在開盤前常寫 0)丟掉。
    """
    lo, hi = SESSION[market]
    buckets: dict[int, tuple[datetime, float]] = {}
    for dt, v in points:
        if dt is None or v is None or dt.strftime("%Y-%m-%d") != day:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        m = dt.hour * 60 + dt.minute
        if m < lo or m > hi:
            continue
        cur = buckets.get(m)
        if cur is None or dt >= cur[0]:
            buckets[m] = (dt, v)
    y, mo, d = (int(x) for x in day.split("-"))
    out: Series = []
    for m in sorted(buckets):
        start = datetime(y, mo, d, m // 60, m % 60, tzinfo=_TPE)
        out.append([int(start.timestamp()), _num(buckets[m][1])])
    return out


def parse_fugle_candles(payload: dict | None, day: str, market: str) -> Series:
    """Fugle ``intraday/candles``(stock 與 futopt 同格式)→ 1 分線。``data[].date`` 是帶 +08:00 的
    開始時間;只用 ``close``(指數沒有量)。"""
    rows = (payload or {}).get("data") or []
    return minute_series(((_parse_ts(r.get("date", "")), r.get("close")) for r in rows
                          if isinstance(r, dict)), day, market)


def parse_twse_5s(payload: dict | None, day: str) -> Series:
    """TWSE ``MI_5MINS_INDEX``(``stat=OK``,``fields[0]=時間``)→ 加權 1 分線。
    每 5 秒一列;同一分鐘取最後一列(=該分鐘收盤),與 Fugle 1 分 K 同一語意。"""
    if not payload or payload.get("stat") != "OK":
        return []
    fields = payload.get("fields") or []
    try:
        i_t, i_v = fields.index("時間"), fields.index(TWSE_5S_FIELD)
    except ValueError:
        return []
    from ..providers import to_float

    y, mo, d = (int(x) for x in day.split("-"))
    pts = []
    for row in payload.get("data") or []:
        try:
            hh, mm, ss = (int(x) for x in str(row[i_t]).split(":"))
            pts.append((datetime(y, mo, d, hh, mm, ss, tzinfo=_TPE), to_float(row[i_v])))
        except (ValueError, IndexError, TypeError):
            continue
    return minute_series(pts, day, "twse")


# ── 台指期:TAIFEX 每日逐筆成交 ──
#
# 欄位:成交日期,商品代號,到期月份(週別),成交時間,成交價格,成交數量(B+S),近月價格,遠月價格,開盤集合競價
# 各欄右側補空白。D 日的檔含「前一晚夜盤」(成交日期 = D-1 的 15:00 起,以及 D 的 00:00–05:00)與
# D 的一般時段;只取成交日期 == D 且 08:45:00–13:45:00 的列。價差(到期月份含 "/")不算。
# 「開盤集合競價」欄標 "*" 的是開盤集合競價撮合那一筆(08:45:00 的開盤價,夜盤 15:00 也有一筆),
# 是真的成交價,照常計入(它落在 08:45 那一分鐘,同分鐘之後的成交會蓋掉它)。

def parse_taifex_daily_tx(lines, day: str, contract_month: str | None = None) -> Series:
    """逐筆成交 CSV 的文字列(已解碼、含表頭)→ 台指期近月一般時段 1 分線(每分鐘最後一筆)。

    ``contract_month``(YYYYMM)= 當天 ``market_indices`` tx 列的近月;缺 → 取一般時段有成交的非價差月份中
    最小者(與 ``providers.market_index.pick_tx_near_month`` 同一個定義)。同一秒多筆以檔案順序最後一筆為準。
    """
    import csv

    d8 = day.replace("-", "")
    y, mo, d = (int(x) for x in day.split("-"))
    lo, hi = SESSION["tx"]
    by_month: dict[str, list] = {}
    for row in csv.reader(lines):
        if len(row) < 5 or row[1].strip() != TAIFEX_TX_CODE or row[0].strip() != d8:
            continue
        month = row[2].strip()
        if "/" in month:
            continue
        t = row[3].strip().zfill(6)
        try:
            hh, mm, ss = int(t[:2]), int(t[2:4]), int(t[4:])
            px = float(row[4])
        except ValueError:
            continue
        if not lo <= hh * 60 + mm <= hi or (hh * 60 + mm == hi and ss > 0):
            continue
        by_month.setdefault(month, []).append((datetime(y, mo, d, hh, mm, ss, tzinfo=_TPE), px))
    if not by_month:
        return []
    month = (contract_month or "").strip() or min(by_month)
    return minute_series(by_month.get(month, []), day, "tx")


def read_taifex_daily_zip(blob: bytes) -> list[str] | None:
    """zip 位元組 → CSV 文字列;不是 zip(檔案還沒公布時站方回 HTML 錯誤頁)→ None。"""
    import io
    import zipfile

    if not blob.startswith(b"PK"):
        return None
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            return None
        return zf.read(names[0]).decode("cp950", errors="replace").splitlines()


def tx_month_from_db(conn, day: str) -> str | None:
    """``market_indices`` 當天的 tx 近月(import-index 已跑過才有)。"""
    from sqlalchemy import text

    row = conn.execute(text(
        "SELECT contract_month FROM market_indices WHERE market='tx' AND date=:d"),
        {"d": day}).fetchone()
    return row[0] if row and row[0] else None


# ── 抓取 ──

def _fugle_get(url: str, api_key: str, session) -> dict | None:
    from ..providers.fugle import _get_json

    return _get_json(url, {"timeframe": FUGLE_TIMEFRAME}, api_key, session, url.rsplit("/", 1)[-1])


def default_fetchers(api_key: str | None, tx_month: str | None) -> dict[str, Callable[[str], Series]]:
    """{market: fetch(day) -> Series}。加權在 Fugle 失敗時退回 TWSE 官方 5 秒表。"""
    import requests

    sess = requests.Session()

    def twse(day: str) -> Series:
        if api_key:
            s = parse_fugle_candles(
                _fugle_get(FUGLE_STOCK_CANDLES_URL.format(symbol=FUGLE_TWSE_INDEX), api_key, sess),
                day, "twse")
            if len(s) >= 2:
                return s
        from ..http import get_json

        try:
            j = get_json(TWSE_5S_URL, {"date": day.replace("-", ""), "response": "json"})
        except Exception as e:  # noqa: BLE001 — 備援失敗 = 沒有這個序列
            print(f"indices_intraday: twse 5s fallback failed: {e}")
            return []
        return parse_twse_5s(j, day)

    def tpex(day: str) -> Series:
        if not api_key:
            return []
        return parse_fugle_candles(
            _fugle_get(FUGLE_STOCK_CANDLES_URL.format(symbol=FUGLE_TPEX_INDEX), api_key, sess),
            day, "tpex")

    def tx(day: str) -> Series:
        y, m, d = day.split("-")
        url = TAIFEX_DAILY_URL.format(y=y, m=m, d=d)
        try:
            r = sess.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=max(config.HTTP_TIMEOUT, 60))
        except Exception as e:  # noqa: BLE001 — 來源掛了 = 這輪沒有台指期
            print(f"indices_intraday: taifex daily fetch failed: {e}")
            return []
        lines = read_taifex_daily_zip(r.content) if r.status_code == 200 else None
        if lines is None:
            print(f"indices_intraday: taifex daily {day} not published yet "
                  f"(HTTP {r.status_code}, {r.headers.get('Content-Type', '')})")
            return []
        return parse_taifex_daily_tx(lines, day, tx_month)

    return {"twse": twse, "tpex": tpex, "tx": tx}


# ── 檔案 ──

def read_existing(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("series"), dict):
        return None
    return data


def build_payload(day: str, series: dict[str, Series]) -> dict | None:
    """固定市場順序、只留 ≥ 2 點的序列;一個都沒有 → None。"""
    kept = {m: series[m] for m in MARKETS if len(series.get(m) or []) >= 2}
    return {"date": day, "series": kept} if kept else None


def update_indices_intraday(
    out: Path,
    price_date: str,
    *,
    today: str | None = None,
    fetchers: dict[str, Callable[[str], Series]] | None = None,
    api_key: str | None = None,
    tx_month: str | None = None,
) -> dict:
    """寫 ``out/market/indices_intraday.json``。回傳統計(也印一行 log)。"""
    today = today if today is not None else taipei_today()
    target = Path(out) / "market" / OUT_FILE
    stats = {"date": price_date, "fetched": [], "kept": [], "written": False, "skip": ""}

    if today != price_date:
        stats["skip"] = f"today={today}"
    existing = read_existing(target)
    have: dict[str, Series] = {}
    if existing and existing.get("date") == price_date:
        have = {m: s for m, s in existing["series"].items() if m in MARKETS and len(s or []) >= 2}
    stats["kept"] = sorted(have)
    missing = [m for m in MARKETS if m not in have]
    if not stats["skip"] and not missing:
        stats["skip"] = "complete"
    key = api_key if api_key is not None else os.environ.get("FUGLE_API_KEY")
    if not stats["skip"] and fetchers is None and not key:
        stats["skip"] = "no FUGLE_API_KEY"   # 與 spark_day 同一閘門(本機/parity 不打網路)

    if not stats["skip"]:
        if fetchers is None:
            fetchers = default_fetchers(key, tx_month)
        for m in missing:
            fn = fetchers.get(m)
            got = fn(price_date) if fn else []
            if len(got or []) >= 2:
                have[m] = got
                stats["fetched"].append(m)
        payload = build_payload(price_date, have)
        if payload is not None:
            text = dumps_compact(payload)
            try:
                same = target.read_text(encoding="utf-8") == text
            except OSError:
                same = False
            if not same:
                target.parent.mkdir(parents=True, exist_ok=True)
                write_atomic(target, text)
                stats["written"] = True

    print("indices_intraday: " + " ".join(f"{k}={v}" for k, v in stats.items()), flush=True)
    return stats


def export_indices_intraday_safe(out: Path, price_date: str, *, conn=None, **kw) -> dict | None:
    """json_export 用的入口;``conn`` 有給就從 DB 讀當天台指期近月。任何例外只記 warning。"""
    try:
        if conn is not None and "tx_month" not in kw:
            try:
                kw["tx_month"] = tx_month_from_db(conn, price_date)
            except Exception:  # noqa: BLE001 — 表不存在等:退回規則推算
                kw["tx_month"] = None
        return update_indices_intraday(out, price_date, **kw)
    except Exception:  # noqa: BLE001 — 附加檔,壞了不能拖垮 export
        _log.warning("indices_intraday export failed; previous file kept", exc_info=True)
        return None
