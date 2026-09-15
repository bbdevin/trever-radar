"""TAIFEX 個股期貨(single-stock futures)provider —— 資料層。

三個來源,三件不同的事:

1. **當日行情** ``https://openapi.taifex.com.tw/v1/DailyMarketReportFut``
   JSON、免金鑰、約 883 KB、單日 2,332 列。一列 =(契約, 到期月份, 交易時段)。
   兩件實測到、與直覺相反的事:

   * ``?date=YYYYMMDD`` **被忽略**。2026-09-15 量測:要 20260911 與 20260910
     回來的是位元組相同的內容,內層 ``Date`` 都是 20260914。這個端點只供應
     最新一天,**不能拿它建歷史**(歷史走第 3 個來源)。
   * ``TradingSession`` 只有 ``一般`` 與 ``盤後`` 兩個值,而且**盤後掛在同一個
     ``Date`` 上**,不是次日。所以 (契約, 日期, 月份, 時段) 才是唯一鍵,
     (契約, 日期, 月份) 不是。

2. **契約 → 個股對照** ``https://www.taifex.com.tw/cht/2/stockLists``
   HTML。頁面有兩張表,要的是商品表;本模組用**表頭文字**認表,不用索引,
   這樣官網改版時會大聲失敗而不是靜靜解析錯一張表。
   標記欄有 ``●`` / ``◎`` 代表「是」,空白代表「否」。最後一列是
   「標的合計數:」的合計列,沒有商品代碼,必須跳過而不是當成一檔商品。

   **Join 規則(實測)**:當日行情的 ``Contract`` == 對照表 ``商品代碼`` + ``"F"``。
   2026-09-15 全日量測:對照表 320 列商品(第 321 列是合計列)全部在行情裡找得到,
   0 列落空;行情另有 65 個代碼沒有對照(台指等指數期貨與其他商品)。
   這個 320/65 的切分就是「個股期貨」與「其他」的分界。
   (任務書引用的是稍早一次量測的 301/84;標的清單會增修,比例會變,
   「對照表每一列都對得到」這個性質才是規則。)

3. **歷史行情** ``https://www.taifex.com.tw/cht/3/futDataDown`` —— **POST** 表單
   ``down_type=1&commodity_id=all&queryStartDate=YYYY/MM/DD&queryEndDate=...``,
   回 **Big5** CSV,欄位與當日行情一一對應。實測一次請求可涵蓋約一個月
   (29 天 → 3.9 MB / 49,626 列),所以 250 個交易日約 12 次請求,不是 250 次。

缺值:行情欄位的「沒有這個數字」有**三種**寫法 —— ``-``、空字串,以及
``NULL``(2026-09-15 量測:盤後列的 ``SettlementPrice`` 有 157 個 ``NULL``)。
三者一律解析成 ``None``。這與 0 是不同的事實:成交量 0 口是「今天沒人交易」,
``None`` 是「這個數字不存在/未公布」,兩者不可互相代換。
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date as date_cls

import requests

from .. import config
from ..http import get_json
from . import NoDataError

DAILY_URL = "https://openapi.taifex.com.tw/v1/DailyMarketReportFut"
STOCK_LIST_URL = "https://www.taifex.com.tw/cht/2/stockLists"
HISTORY_URL = "https://www.taifex.com.tw/cht/3/futDataDown"

SESSION_REGULAR = "一般"
SESSION_AFTER_HOURS = "盤後"

# 對照表商品代碼 → 行情契約代碼的後綴。見模組 docstring 的 join 量測。
CONTRACT_SUFFIX = "F"

# 「是」的兩種符號。頁面自己在表格上方寫明:實心圓(●)與雙圈圓(◎)皆代表「是」。
_TRUE_MARKS = ("●", "◎")

# 三種「沒有數字」的寫法,全部 → None。
_MISSING = frozenset({"", "-", "--", "---", "N/A", "NULL"})

_REQUEST_HEADERS = {"User-Agent": config.USER_AGENT}


class TaifexParseError(RuntimeError):
    """回應在結構上不符合已驗證的合約 —— 寧可大聲失敗,不要解析出垃圾。"""


@dataclass(frozen=True)
class FuturesDailyRow:
    """一列 =(契約, 日期, 到期月份, 交易時段)。不在這裡做任何彙總。"""

    contract_code: str        # 行情代碼,例 'CCF'
    date: str                 # YYYY-MM-DD
    contract_month: str       # 原樣保留,例 '202609' 或價差組合 '202609/202610'
    session: str              # 一般 / 盤後
    open: float | None
    high: float | None
    low: float | None
    last: float | None
    change: float | None
    volume: int | None
    settlement_price: float | None
    open_interest: int | None


@dataclass(frozen=True)
class FuturesContractRow:
    """股票期貨/選擇權交易標的一列。"""

    contract_code: str        # 商品代碼 + 'F',例 'CCF';與行情 join 用的鍵
    product_code: str         # 官網原始商品代碼,例 'CC'
    stock_id: str             # 證券代號,例 '2303'
    stock_name: str           # 標的證券簡稱
    is_stock_future: bool
    is_stock_option: bool
    is_weekly_option: bool
    market: str | None        # twse / tpex;四個標的證券欄推得,都空白則 None


# --------------------------------------------------------------------------- 解析工具


def _text(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).replace("\xa0", " ").split())


def _to_float(value) -> float | None:
    s = _text(value).replace(",", "").replace("%", "")
    if s in _MISSING:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(value) -> int | None:
    f = _to_float(value)
    return None if f is None else int(f)


def _iso_from_compact(value) -> str | None:
    """'20260914' / '2026/09/14' / '2026-09-14' → '2026-09-14'。"""
    digits = _text(value).replace("/", "").replace("-", "")
    if len(digits) != 8 or not digits.isdigit():
        return None
    try:
        return date_cls(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return None


def _is_marked(cell: str) -> bool:
    """標記欄:含 ● 或 ◎ 為真,空白(或僅空白字元)為假。"""
    return any(mark in cell for mark in _TRUE_MARKS)


# --------------------------------------------------------------------------- 當日行情


def parse_daily_report(payload) -> list[FuturesDailyRow]:
    """DailyMarketReportFut 的 JSON list → 行情列。

    ``session`` 與 ``contract_month`` 原樣保留(含 '202609/202610' 這種價差組合),
    彙總是上層的事,不在這裡做。
    """
    if isinstance(payload, (str, bytes, bytearray)):
        payload = json.loads(payload)
    if not isinstance(payload, list):
        raise TaifexParseError(f"DailyMarketReportFut: expected a list, got {type(payload)}")
    out: list[FuturesDailyRow] = []
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        contract = _text(raw.get("Contract"))
        iso = _iso_from_compact(raw.get("Date"))
        month = _text(raw.get("ContractMonth(Week)"))
        session = _text(raw.get("TradingSession"))
        if not contract or not iso or not month or not session:
            continue
        out.append(
            FuturesDailyRow(
                contract_code=contract,
                date=iso,
                contract_month=month,
                session=session,
                open=_to_float(raw.get("Open")),
                high=_to_float(raw.get("High")),
                low=_to_float(raw.get("Low")),
                last=_to_float(raw.get("Last")),
                change=_to_float(raw.get("Change")),
                volume=_to_int(raw.get("Volume")),
                settlement_price=_to_float(raw.get("SettlementPrice")),
                open_interest=_to_int(raw.get("OpenInterest")),
            )
        )
    return out


def fetch_daily_report() -> list[FuturesDailyRow]:
    """最新一個交易日的全市場期貨行情。

    這個端點**沒有日期參數可用**(見模組 docstring),所以呼叫端只能問「最新是哪天」,
    不能指定哪天;日期由回傳內容自己說。
    """
    rows = parse_daily_report(get_json(DAILY_URL))
    if not rows:
        raise NoDataError("taifex DailyMarketReportFut: empty parse")
    return rows


# --------------------------------------------------------------------------- 對照表

_HEADER_PRODUCT = "商品代碼"
_HEADER_STOCK_ID = "證券代號"
_HEADER_STOCK_NAME = "標的證券"
_HEADER_FUTURE = "股票期貨"
_HEADER_OPTION = "股票選擇權"
_HEADER_WEEKLY = "週契約"
_HEADER_TWSE = "上市"
_HEADER_TPEX = "上櫃"


def _collect_tables(html: str) -> list[list[list[str]]]:
    from .mops import _TableCollector  # 同一份標準函式庫 HTML 表格擷取器,不重複實作

    collector = _TableCollector()
    collector.feed(html)
    return collector.tables


def _pick_product_table(tables: list[list[list[str]]]) -> list[list[str]]:
    """用表頭文字認商品表。

    刻意**不用索引**(「第二張表」)。索引一旦對錯,解析出來的是另一張表的內容,
    而且看起來像成功;認表頭則是官網改版時立刻炸掉,這是想要的行為。
    """
    for table in tables:
        if not table:
            continue
        header = [_text(cell) for cell in table[0]]
        joined = "".join(header)
        if _HEADER_PRODUCT in joined and _HEADER_STOCK_ID in joined and _HEADER_STOCK_NAME in joined:
            return table
    raise TaifexParseError(
        "stockLists: no table whose header carries "
        f"{_HEADER_PRODUCT!r} + {_HEADER_STOCK_ID!r} + {_HEADER_STOCK_NAME!r} "
        "— the page layout changed; refusing to guess which table is the product table"
    )


def _header_index(header: list[str], *needles: str, without: str | None = None) -> int:
    for i, cell in enumerate(header):
        if all(n in cell for n in needles) and (without is None or without not in cell):
            return i
    raise TaifexParseError(f"stockLists: header column {needles!r} not found in {header!r}")


def parse_stock_list(html: str) -> list[FuturesContractRow]:
    """stockLists 頁面 → 契約/個股對照列。

    表頭認錯就丟 :class:`TaifexParseError`,不回傳半套資料。
    末列「標的合計數:」沒有商品代碼,跳過。
    """
    table = _pick_product_table(_collect_tables(html))
    header = [_text(cell) for cell in table[0]]
    i_product = _header_index(header, _HEADER_PRODUCT)
    i_stock_id = _header_index(header, _HEADER_STOCK_ID)
    i_name = _header_index(header, _HEADER_STOCK_NAME, "簡稱")
    i_future = _header_index(header, "是否為", _HEADER_FUTURE)
    # 「股票選擇權」與「股票選擇權週契約」兩欄的表頭互為前綴,認欄位時必須把週契約
    # 明確排除,否則兩個欄位會指到同一格,而且是靜靜地指錯。
    i_option = _header_index(header, "是否為", _HEADER_OPTION, "標的", without=_HEADER_WEEKLY)
    i_weekly = _header_index(header, "是否為", _HEADER_WEEKLY)
    i_twse_common = _header_index(header, _HEADER_TWSE, "普通股")
    i_tpex_common = _header_index(header, _HEADER_TPEX, "普通股")
    i_twse_etf = _header_index(header, _HEADER_TWSE, "ETF")
    i_tpex_etf = _header_index(header, _HEADER_TPEX, "ETF")
    widest = max(i_product, i_stock_id, i_name, i_future, i_option, i_weekly,
                 i_twse_common, i_tpex_common, i_twse_etf, i_tpex_etf)

    out: list[FuturesContractRow] = []
    for raw in table[1:]:
        if len(raw) <= widest:
            continue
        cells = [_text(cell) for cell in raw]
        product = cells[i_product]
        stock_id = cells[i_stock_id]
        if not product or not stock_id:
            # 合計列(「標的合計數:」)長這樣:沒有商品代碼,計數塞在標記欄裡。
            continue
        twse = _is_marked(cells[i_twse_common]) or _is_marked(cells[i_twse_etf])
        tpex = _is_marked(cells[i_tpex_common]) or _is_marked(cells[i_tpex_etf])
        out.append(
            FuturesContractRow(
                contract_code=product + CONTRACT_SUFFIX,
                product_code=product,
                stock_id=stock_id,
                stock_name=cells[i_name],
                is_stock_future=_is_marked(cells[i_future]),
                is_stock_option=_is_marked(cells[i_option]),
                is_weekly_option=_is_marked(cells[i_weekly]),
                market="twse" if twse else ("tpex" if tpex else None),
            )
        )
    return out


def fetch_stock_list() -> list[FuturesContractRow]:
    response = requests.get(STOCK_LIST_URL, headers=_REQUEST_HEADERS, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    rows = parse_stock_list(response.text)
    if not rows:
        raise NoDataError("taifex stockLists: empty parse")
    return rows


# --------------------------------------------------------------------------- 歷史 CSV

# futDataDown 的中文表頭 → FuturesDailyRow 欄位。位置會變,名稱不會,所以認名稱。
_HISTORY_COLUMNS = {
    "date": "交易日期",
    "contract_code": "契約",
    "contract_month": "到期月份",
    "session": "交易時段",
    "open": "開盤價",
    "high": "最高價",
    "low": "最低價",
    "last": "收盤價",
    "change": "漲跌價",
    "volume": "成交量",
    "settlement_price": "結算價",
    "open_interest": "未沖銷契約數",
}


def parse_history_csv(raw: bytes) -> list[FuturesDailyRow]:
    """futDataDown 的 Big5 CSV → 與當日行情相同形狀的列。

    解碼失敗(``UnicodeDecodeError``)**不吞、不用 errors='replace' 掩蓋**:
    這個端點的合約就是 Big5,解不開代表拿到的不是這個端點該給的東西
    (轉址到錯誤頁、被中間設備改寫、或官網換了編碼)。用替代字元硬撐下去只會把
    「契約名稱亂碼」寫進資料庫,而亂碼看起來像資料。所以這裡把它轉成
    :class:`TaifexParseError` 並保留原因,讓呼叫端當成失敗處理。
    """
    try:
        text = raw.decode("big5")
    except UnicodeDecodeError as exc:
        raise TaifexParseError(
            f"futDataDown: response is not Big5 ({exc}) — refusing to decode with "
            "replacement characters, which would store mojibake as if it were data"
        ) from exc

    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = [_text(cell) for cell in next(reader)]
    except StopIteration:
        return []
    index: dict[str, int] = {}
    for field, needle in _HISTORY_COLUMNS.items():
        for i, cell in enumerate(header):
            if needle in cell:
                index[field] = i
                break
        else:
            raise TaifexParseError(
                f"futDataDown: header column {needle!r} not found in {header!r}"
            )
    widest = max(index.values())

    out: list[FuturesDailyRow] = []
    for row in reader:
        if len(row) <= widest:
            continue
        cells = [_text(cell) for cell in row]
        iso = _iso_from_compact(cells[index["date"]])
        contract = cells[index["contract_code"]]
        month = cells[index["contract_month"]]
        session = cells[index["session"]]
        if not iso or not contract or not month or not session:
            continue
        out.append(
            FuturesDailyRow(
                contract_code=contract,
                date=iso,
                contract_month=month,
                session=session,
                open=_to_float(cells[index["open"]]),
                high=_to_float(cells[index["high"]]),
                low=_to_float(cells[index["low"]]),
                last=_to_float(cells[index["last"]]),
                change=_to_float(cells[index["change"]]),
                volume=_to_int(cells[index["volume"]]),
                settlement_price=_to_float(cells[index["settlement_price"]]),
                open_interest=_to_int(cells[index["open_interest"]]),
            )
        )
    return out


def fetch_history(start: str, end: str) -> list[FuturesDailyRow]:
    """一次請求抓 ``start``..``end``(YYYY-MM-DD,含兩端)的全市場歷史行情。

    實測一個月的區間是一次請求可以吃下的量;呼叫端負責按月切塊與請求間隔。
    """
    form = {
        "down_type": "1",
        "commodity_id": "all",
        "queryStartDate": start.replace("-", "/"),
        "queryEndDate": end.replace("-", "/"),
    }
    response = requests.post(
        HISTORY_URL, data=form, headers=_REQUEST_HEADERS, timeout=config.HTTP_TIMEOUT * 4
    )
    response.raise_for_status()
    rows = parse_history_csv(response.content)
    if not rows:
        raise NoDataError(f"taifex futDataDown {start}..{end}: empty parse")
    return rows


# --------------------------------------------------------------------------- join


def split_stock_futures(
    daily_rows: list[FuturesDailyRow], contracts: list[FuturesContractRow]
) -> tuple[list[FuturesDailyRow], list[str]]:
    """用 ``商品代碼 + 'F'`` 的 join 規則把個股期貨與其他商品分開。

    回傳 (個股期貨行情列, 對不到對照表的行情代碼排序清單)。後者就是指數期貨等
    其他商品,不是錯誤;但它為零、或個股期貨為零,都代表 join 規則壞了。
    """
    known = {c.contract_code for c in contracts}
    kept = [r for r in daily_rows if r.contract_code in known]
    leftover = sorted({r.contract_code for r in daily_rows if r.contract_code not in known})
    return kept, leftover
