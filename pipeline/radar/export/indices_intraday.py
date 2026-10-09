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
16:40 之後那幾輪,例 20:00 mid-backfill-publish、20:45 資券)。台指期本身不需要金鑰,但仍走同一個閘門
(2026-10-09 決定):這把金鑰在專案裡就是「這台機器可以打盤中來源」的開關——VPS 一定有,本機與
``tools/export_parity.py`` 拿掉它就保證整個 export 不發網路;另開一個旗標要多改正式 VPS 環境,不值得。
同一天已經三個都有 → 不再打(一天一次);缺哪個下一輪只補哪個。整步在 export 裡**隔離**:每個市場各自
try(一個掛掉,已抓到的照寫)、整步總時限 ``BUDGET_S``(來源掛掉時 export 最多多等這麼久)、
``export_indices_intraday_safe`` 任何例外只記 warning。寫檔 tmp+rename,內容沒變不重寫。
"""
from __future__ import annotations

import json
import logging
import os
import time
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
    """逐筆成交 CSV 的文字列(已解碼、含表頭;可以是串流的檔案物件)→ 台指期近月一般時段 1 分線(每分鐘最後一筆)。

    ``contract_month``(YYYYMM)= 當天 ``market_indices`` tx 列的近月;缺 → 取一般時段有成交的非價差月份中
    最小者(與 ``providers.market_index.pick_tx_near_month`` 同一個定義)。同一秒多筆以檔案順序最後一筆為準。

    記憶體:逐列處理、先用字首(成交日期,商品代號)粗篩再交給 csv,每個月份只留「每分鐘最後一筆」
    (≤ 301 筆),不囤整天逐筆。整檔 ~34 MB 解壓,峰值見 docs/49 §12.5。
    """
    import csv

    d8 = day.replace("-", "")
    prefix = f"{d8},{TAIFEX_TX_CODE}"
    y, mo, d = (int(x) for x in day.split("-"))
    lo, hi = SESSION["tx"]
    # {month: {minute: (second, price)}}——同分鐘時間較晚(或同秒、檔案較後)者蓋掉,與 minute_series 同語意
    by_month: dict[str, dict[int, tuple[int, float]]] = {}
    for row in csv.reader(ln for ln in lines if ln.lstrip().startswith(prefix)):
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
        m = hh * 60 + mm
        if not lo <= m <= hi or (m == hi and ss > 0):
            continue
        mins = by_month.setdefault(month, {})
        cur = mins.get(m)
        if cur is None or ss >= cur[0]:
            mins[m] = (ss, px)
    if not by_month:
        return []
    month = (contract_month or "").strip() or min(by_month)
    pts = ((datetime(y, mo, d, m // 60, m % 60, ss, tzinfo=_TPE), px)
           for m, (ss, px) in by_month.get(month, {}).items())
    return minute_series(pts, day, "tx")


def parse_taifex_daily_zip(blob: bytes, day: str, contract_month: str | None = None) -> Series | None:
    """zip 位元組 → 台指期 1 分線,CSV **串流**解碼(``zf.open`` + ``TextIOWrapper``),不把 34 MB 文字整份
    讀進記憶體。不是 zip(檔案還沒公布時站方回 HTML 錯誤頁)、zip 壞掉(``PK`` 開頭但截斷/CRC 錯)、
    沒有 CSV → None(= 這輪沒有台指期,較晚的一輪再補)。"""
    import io
    import zipfile
    import zlib

    if not blob.startswith(b"PK"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            with zf.open(names[0]) as raw, \
                    io.TextIOWrapper(raw, encoding="cp950", errors="replace") as fh:
                return parse_taifex_daily_tx(fh, day, contract_month)
    except (zipfile.BadZipFile, zlib.error, EOFError) as e:
        print(f"indices_intraday: taifex daily zip unreadable ({type(e).__name__}: {e}) — treated as missing")
        return None


def tx_month_from_db(conn, day: str) -> str | None:
    """``market_indices`` 當天的 tx 近月(import-index 已跑過才有)。"""
    from sqlalchemy import text

    row = conn.execute(text(
        "SELECT contract_month FROM market_indices WHERE market='tx' AND date=:d"),
        {"d": day}).fetchone()
    return row[0] if row and row[0] else None


# ── 抓取 ──

# 這步是附加功能:整步有總時限(``BUDGET_S``),每個請求只打一次、逾時短(``REQ_TIMEOUT_S``,且不超過剩餘時限),
# 不走 providers.fugle._get_json / http.get_json 的多次重試與 429 長退避(Fugle 掛掉時那條路要 60–90 s)。
# 沒抓到的市場下一輪(同一天盤後還有好幾輪)再補。
BUDGET_S = 45.0
REQ_TIMEOUT_S = 10.0
TAIFEX_TIMEOUT_S = 20.0   # ~1.6 MB zip
_MIN_LEFT_S = 1.0         # 剩不到這麼多就不發請求


class _Deadline:
    def __init__(self, budget_s: float, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.at = clock() + budget_s

    def left(self) -> float:
        return self.at - self.clock()

    def timeout(self, cap: float) -> float | None:
        """這次請求可用的逾時秒數;時限已到 → None(不發)。"""
        left = self.left()
        return None if left < _MIN_LEFT_S else min(cap, left)


def _fugle_get(url: str, api_key: str, session, deadline: _Deadline) -> dict | None:
    """單次 Fugle GET(共用 providers.fugle 的 1.05 s 節流);429/4xx/5xx/逾時 → None,不退避重試。"""
    from ..providers.fugle import _throttle

    timeout = deadline.timeout(REQ_TIMEOUT_S)
    if timeout is None:
        return None
    _throttle()
    try:
        r = session.get(url, params={"timeframe": FUGLE_TIMEFRAME},
                        headers={"X-API-KEY": api_key, "User-Agent": config.USER_AGENT}, timeout=timeout)
        if r.status_code >= 400:
            print(f"indices_intraday: fugle {url.rsplit('/', 1)[-1]} HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001 — 來源掛了 = 這輪沒有這個序列
        print(f"indices_intraday: fugle {url.rsplit('/', 1)[-1]} failed: {e}")
        return None


def default_fetchers(api_key: str | None, tx_month: str | None,
                     deadline: _Deadline | None = None) -> dict[str, Callable[[str], Series]]:
    """{market: fetch(day) -> Series}。加權在 Fugle 失敗時退回 TWSE 官方 5 秒表。
    每個請求的逾時都受 ``deadline`` 限制(缺 → 自己開一個 ``BUDGET_S``)。"""
    import requests

    sess = requests.Session()
    dl = deadline or _Deadline(BUDGET_S)

    def twse(day: str) -> Series:
        if api_key:
            s = parse_fugle_candles(
                _fugle_get(FUGLE_STOCK_CANDLES_URL.format(symbol=FUGLE_TWSE_INDEX), api_key, sess, dl),
                day, "twse")
            if len(s) >= 2:
                return s
        timeout = dl.timeout(REQ_TIMEOUT_S)
        if timeout is None:
            return []
        try:
            r = sess.get(TWSE_5S_URL, params={"date": day.replace("-", ""), "response": "json"},
                         headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
            r.raise_for_status()
            j = r.json()
        except Exception as e:  # noqa: BLE001 — 備援失敗 = 沒有這個序列
            print(f"indices_intraday: twse 5s fallback failed: {e}")
            return []
        return parse_twse_5s(j, day)

    def tpex(day: str) -> Series:
        if not api_key:
            return []
        return parse_fugle_candles(
            _fugle_get(FUGLE_STOCK_CANDLES_URL.format(symbol=FUGLE_TPEX_INDEX), api_key, sess, dl),
            day, "tpex")

    def tx(day: str) -> Series:
        y, m, d = day.split("-")
        url = TAIFEX_DAILY_URL.format(y=y, m=m, d=d)
        timeout = dl.timeout(TAIFEX_TIMEOUT_S)
        if timeout is None:
            return []
        try:
            r = sess.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=timeout)
        except Exception as e:  # noqa: BLE001 — 來源掛了 = 這輪沒有台指期
            print(f"indices_intraday: taifex daily fetch failed: {e}")
            return []
        s = parse_taifex_daily_zip(r.content, day, tx_month) if r.status_code == 200 else None
        if s is None:
            print(f"indices_intraday: taifex daily {day} not published yet "
                  f"(HTTP {r.status_code}, {r.headers.get('Content-Type', '')})")
            return []
        return s

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
    budget_s: float = BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """寫 ``out/market/indices_intraday.json``。回傳統計(也印一行 log)。

    每個市場各自隔離:某個 fetcher 丟例外只算那個市場這輪沒有,已抓到的照寫。整步共用一個
    ``budget_s`` 時限,到了就略過剩下的市場(``stats["timed_out"]``),下一輪再補。
    """
    today = today if today is not None else taipei_today()
    target = Path(out) / "market" / OUT_FILE
    stats = {"date": price_date, "fetched": [], "kept": [], "failed": [], "timed_out": [],
             "written": False, "skip": ""}

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
        deadline = _Deadline(budget_s, clock)
        if fetchers is None:
            fetchers = default_fetchers(key, tx_month, deadline)
        for m in missing:
            if deadline.left() < _MIN_LEFT_S:
                stats["timed_out"].append(m)
                continue
            fn = fetchers.get(m)
            try:
                got = fn(price_date) if fn else []
            except Exception:  # noqa: BLE001 — 一個市場壞掉不拖累其他市場
                _log.warning("indices_intraday: %s fetch failed", m, exc_info=True)
                stats["failed"].append(m)
                continue
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
