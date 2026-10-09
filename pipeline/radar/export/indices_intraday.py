"""大盤當日走勢(docs/49 §12.5):加權／櫃買／台指期近月的當日 1 分線 → ``market/indices_intraday.json``。

首頁市場概況走勢圖 sheet 的「1日」才抓這檔。內容只有最新一個交易日:

    {"date": "YYYY-MM-DD", "series": {"twse": [[epoch_s, close], …], "tpex": […], "tx": […]}}

* ``epoch_s`` 是真正的 Unix 秒(該分鐘的**開始時間**,與分K ``stocks/intraday`` 同一個慣例);
  前端照 ``chartTimeOf(twWallKey(epoch))`` 換成「台北牆上時間當 UTC」給圖表,09:00 就顯示 09:00。
* 每根 = 那一分鐘的最後一個值(1 分 K 的收盤)。缺分鐘不補。
* 某序列抓不到就不出那個鍵(前端顯示「暫無日內走勢」);三個都沒有 → 不寫檔、舊檔留著。

來源(全部免費、無驗證碼;第一次正式跑前用 ``pipeline/tools/probe_index_intraday.py`` 在 VPS 核對):

* 加權:Fugle ``stock/intraday/candles/{FUGLE_TWSE_INDEX}``(1 分);沒金鑰或失敗 → TWSE
  ``TAIEX/MI_5MINS_INDEX``(每 5 秒一列,一天一次請求 ~1.2 MB)聚成 1 分。
* 櫃買:Fugle ``stock/intraday/candles/{FUGLE_TPEX_INDEX}``。TPEx 沒找到公開的盤中分鐘指數端點,無備援。
* 台指期:Fugle ``futopt/intraday/candles/{TXF+月碼+年尾}``(一般時段 08:45–13:45)。免費方案
  不含期權時回 4xx → 不出 ``tx``,前端寫「台指期暫無日內走勢」。

閘門與 spark_day 相同:有 ``FUGLE_API_KEY`` 且台北今天 == 價格日才打來源(盤後各輪;14:10 第一輪時
三個市場都已收盤)。
同一天已經三個都有 → 不再打(一天一次);缺哪個下一輪只補哪個。整步在 export 裡**隔離**:
``export_indices_intraday_safe`` 任何例外只記 warning。寫檔 tmp+rename,內容沒變不重寫。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .. import config
from .stock_parts import dumps_compact, write_atomic

_log = logging.getLogger(__name__)

OUT_FILE = "indices_intraday.json"
MARKETS = ("twse", "tpex", "tx")

# ── 來源代號(VPS probe 後可直接改這幾個常數) ──
FUGLE_TWSE_INDEX = "IX0001"   # 發行量加權股價指數
FUGLE_TPEX_INDEX = "IX0043"   # 櫃買指數(待 probe 核對:tickers?type=INDEX&exchange=TPEx)
FUGLE_TX_PRODUCT = "TXF"      # 台指期;完整代號 = TXF + 月碼(A=1月…L=12月)+ 西元年尾數,例 TXFJ6
FUGLE_TIMEFRAME = "1"

FUGLE_STOCK_CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{symbol}"
FUGLE_FUTOPT_CANDLES_URL = "https://api.fugle.tw/marketdata/v1.0/futopt/intraday/candles/{symbol}"
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


# ── 台指期近月代號 ──

_MONTH_CODES = "ABCDEFGHIJKL"


def tx_symbol(contract_month: str) -> str | None:
    """"202610" → "TXFJ6"(Fugle futopt 代號:商品 + 月碼 + 西元年尾數)。格式不對 → None。"""
    s = str(contract_month or "").strip()
    if len(s) != 6 or not s.isdigit() or not 1 <= int(s[4:]) <= 12:
        return None
    return f"{FUGLE_TX_PRODUCT}{_MONTH_CODES[int(s[4:]) - 1]}{s[3]}"


def near_month_by_rule(day: str) -> str:
    """沒有當天 TX 匯入列時的近月推算:當月第三個週三(含)以前 = 當月,之後 = 次月。
    不處理期交所的假日順延(那幾天 DB 的匯入列會蓋過這個推算)。"""
    d = date_cls.fromisoformat(day)
    first = d.replace(day=1)
    third_wed = first + timedelta(days=(2 - first.weekday()) % 7 + 14)
    if d <= third_wed:
        return f"{d.year}{d.month:02d}"
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return f"{y}{m:02d}"


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
        sym = tx_symbol(tx_month or near_month_by_rule(day))
        if not api_key or not sym:
            return []
        return parse_fugle_candles(
            _fugle_get(FUGLE_FUTOPT_CANDLES_URL.format(symbol=sym), api_key, sess), day, "tx")

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
