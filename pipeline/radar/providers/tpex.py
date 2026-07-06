"""TPEx (上櫃) endpoints. Site expects ROC dates: 115/07/06 for 2026-07-06."""
from ..dto import InstiRow, MarginRow, Quote
from ..http import get_json
from . import NoDataError, to_float, to_int

BASE = "https://www.tpex.org.tw/www/zh-tw"


def roc_date(date: str) -> str:
    """YYYYMMDD → ROC 'YYY/MM/DD'."""
    return f"{int(date[:4]) - 1911}/{date[4:6]}/{date[6:8]}"


def _table(j, what: str, date: str, first_field: str):
    if str(j.get("stat", "")).lower() not in ("ok",):
        raise NoDataError(f"tpex {what} {date}: stat={j.get('stat')}")
    for t in j.get("tables", []):
        fields = t.get("fields", [])
        if fields and fields[0] == first_field and t.get("data"):
            return t
    raise NoDataError(f"tpex {what} {date}: no populated table")


def fetch_daily_quotes(date: str) -> list[Quote]:
    """dailyQuotes type=AL — all OTC securities incl. 7xxxxx warrants (~10k rows)."""
    j = get_json(f"{BASE}/afterTrading/dailyQuotes",
                 {"date": roc_date(date), "type": "AL", "response": "json"})
    table = _table(j, "dailyQuotes", date, "代號")
    fields = [f.strip() for f in table["fields"]]
    idx = {name: i for i, name in enumerate(fields)}
    need = ["代號", "名稱", "收盤", "開盤", "最高", "最低", "成交股數", "成交金額(元)"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"tpex dailyQuotes {date}: missing fields {missing}; got {fields}")
    tx_idx = idx.get("成交筆數")
    quotes = []
    for row in table["data"]:
        quotes.append(Quote(
            code=str(row[idx["代號"]]).strip(),
            name=str(row[idx["名稱"]]).strip(),
            market="tpex",
            open=to_float(row[idx["開盤"]]),
            high=to_float(row[idx["最高"]]),
            low=to_float(row[idx["最低"]]),
            close=to_float(row[idx["收盤"]]),
            volume=to_int(row[idx["成交股數"]]),
            turnover=to_int(row[idx["成交金額(元)"]]),
            transactions=to_int(row[tx_idx]) if tx_idx is not None else None,
        ))
    return quotes


def fetch_institutional(date: str) -> list[InstiRow]:
    """insti/dailyTrade sect=EW. 24 positional columns:
    0代號 1名稱 | 2-4 外陸資(不含自營) | 5-7 外資自營 | 8-10 外資合計
    | 11-13 投信 | 14-16 自營(自行) | 17-19 自營(避險) | 20-22 自營合計 | 23 三大合計
    """
    j = get_json(f"{BASE}/insti/dailyTrade",
                 {"type": "Daily", "sect": "EW", "date": roc_date(date), "response": "json"})
    table = _table(j, "insti/dailyTrade", date, "代號")
    if len(table["fields"]) != 24:
        raise RuntimeError(f"tpex insti {date}: layout changed, {len(table['fields'])} fields")
    rows = []
    for r in table["data"]:
        if len(r) != 24:
            continue
        rows.append(InstiRow(
            code=str(r[0]).strip(),
            foreign_net=to_int(r[10]) or 0,
            trust_net=to_int(r[13]) or 0,
            dealer_net=to_int(r[22]) or 0,
            total_net=to_int(r[23]) or 0,
        ))
    return rows


def fetch_margin(date: str) -> list[MarginRow]:
    """margin/balance 融資融券餘額(張). Unique field names → name lookup."""
    j = get_json(f"{BASE}/margin/balance", {"date": roc_date(date), "response": "json"})
    table = _table(j, "margin/balance", date, "代號")
    fields = [f.strip() for f in table["fields"]]
    idx = {name: i for i, name in enumerate(fields)}
    need = ["代號", "資餘額", "前資餘額(張)", "資限額", "券餘額", "前券餘額(張)"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"tpex margin {date}: missing fields {missing}; got {fields}")
    rows = []
    for r in table["data"]:
        rows.append(MarginRow(
            code=str(r[idx["代號"]]).strip(),
            margin_balance=to_int(r[idx["資餘額"]]),
            margin_prev=to_int(r[idx["前資餘額(張)"]]),
            margin_limit=to_int(r[idx["資限額"]]),
            short_balance=to_int(r[idx["券餘額"]]),
            short_prev=to_int(r[idx["前券餘額(張)"]]),
        ))
    return rows
