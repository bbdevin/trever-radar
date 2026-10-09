"""大盤指數日收(docs/49 §11):加權指數(TWSE)與櫃買指數(TPEx)。

兩個來源都是公開、無驗證碼的盤後端點;抓回來的值**逐筆照來源**(原始資料一致原則):
* TWSE ``afterTrading/MI_INDEX?type=IND``:第一張表「價格指數」,列「發行量加權股價指數」。
  收盤、漲跌點數、漲跌百分比三欄都有;方向在「漲跌(+/-)」欄(來源用 HTML 包著 + / -)。
* TPEx ``afterTrading/tradingIndex?date=YYYY/MM/DD``:該月逐日「成交量值及櫃買指數」,
  取「日期」等於要的那天的列;只有櫃買指數與漲/跌點數,**沒有百分比**(chg_pct 留 None)。

解析是純函式(``parse_*``),測試用抓回來的原始回應當 fixture 對值。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..http import get_json
from . import NoDataError, to_float
from .tpex import roc_date

TWSE_BASE = "https://www.twse.com.tw/rwd/zh"
TPEX_BASE = "https://www.tpex.org.tw/www/zh-tw"

TAIEX_NAME = "發行量加權股價指數"


@dataclass(slots=True)
class IndexRow:
    market: str            # twse | tpex
    date: str              # YYYY-MM-DD
    close: float
    change: float | None   # 漲跌點數(含正負)
    chg_pct: float | None  # 漲跌百分比;來源沒給 → None


def _iso(date: str) -> str:
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}"


def _sign(cell) -> int:
    """TWSE「漲跌(+/-)」欄:``<p style ='color:green'>-</p>`` / ``…>+</p>`` / 空白。"""
    s = str(cell or "")
    if "+" in s:
        return 1
    if "-" in s:
        return -1
    return 0


def parse_twse_index(j: dict, date: str) -> IndexRow:
    """MI_INDEX type=IND → 加權指數一列。``stat`` 不是 OK(休市/未公布)→ NoDataError。"""
    if j.get("stat") != "OK":
        raise NoDataError(f"twse MI_INDEX IND {date}: {j.get('stat')}")
    table = None
    for t in j.get("tables", []):
        fields = t.get("fields", [])
        if fields and fields[0] == "指數" and t.get("data"):
            table = t
            break
    if table is None:
        raise RuntimeError(f"twse MI_INDEX IND {date}: price-index table not found; "
                           f"titles={[t.get('title', '')[:20] for t in j.get('tables', [])]}")
    idx = {name: i for i, name in enumerate(table["fields"])}
    need = ["指數", "收盤指數", "漲跌(+/-)", "漲跌點數", "漲跌百分比(%)"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"twse MI_INDEX IND {date}: missing fields {missing}; got {table['fields']}")
    for row in table["data"]:
        if str(row[idx["指數"]]).strip() != TAIEX_NAME:
            continue
        close = to_float(row[idx["收盤指數"]])
        if close is None:
            raise NoDataError(f"twse MI_INDEX IND {date}: TAIEX close empty")
        sign = _sign(row[idx["漲跌(+/-)"]])
        pts = to_float(row[idx["漲跌點數"]])
        pct = to_float(row[idx["漲跌百分比(%)"]])
        return IndexRow(
            market="twse", date=_iso(date), close=close,
            change=None if pts is None else sign * abs(pts),
            # 百分比欄本身帶正負(-0.99);沒有方向欄時以它為準,否則用方向欄統一。
            chg_pct=None if pct is None else (sign * abs(pct) if sign else pct),
        )
    raise RuntimeError(f"twse MI_INDEX IND {date}: row {TAIEX_NAME!r} not found")


def parse_tpex_index(j: dict, date: str) -> IndexRow:
    """tradingIndex(整月)→ 取 ``date`` 那一列;那天不在表裡 = 還沒公布/休市 → NoDataError。"""
    if str(j.get("stat", "")).lower() != "ok":
        raise NoDataError(f"tpex tradingIndex {date}: stat={j.get('stat')}")
    table = None
    for t in j.get("tables", []):
        fields = [str(f).strip() for f in t.get("fields", [])]
        if fields and fields[0] == "日期":
            table = (t, fields)
            break
    if table is None:
        raise NoDataError(f"tpex tradingIndex {date}: no table")
    t, fields = table
    idx = {name: i for i, name in enumerate(fields)}
    need = ["日期", "櫃買指數", "漲/跌"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"tpex tradingIndex {date}: missing fields {missing}; got {fields}")
    want = roc_date(date)
    for row in t.get("data", []):
        if str(row[idx["日期"]]).strip() != want:
            continue
        close = to_float(row[idx["櫃買指數"]])
        if close is None:
            raise NoDataError(f"tpex tradingIndex {date}: close empty")
        return IndexRow(market="tpex", date=_iso(date), close=close,
                        change=to_float(row[idx["漲/跌"]]), chg_pct=None)
    raise NoDataError(f"tpex tradingIndex {date}: no row for {want}")


def fetch_twse_index(date: str) -> IndexRow:
    """date: YYYYMMDD。"""
    j = get_json(f"{TWSE_BASE}/afterTrading/MI_INDEX",
                 {"date": date, "type": "IND", "response": "json"})
    return parse_twse_index(j, date)


def fetch_tpex_index(date: str) -> IndexRow:
    """date: YYYYMMDD。端點吃 ROC 月份內任一天,回整月。"""
    j = get_json(f"{TPEX_BASE}/afterTrading/tradingIndex",
                 {"date": roc_date(date), "response": "json"})
    return parse_tpex_index(j, date)
