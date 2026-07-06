"""TWSE (上市) after-trading endpoints. date format: YYYYMMDD."""
from ..dto import InstiRow, MarginRow, Quote
from ..http import get_json
from . import NoDataError, to_float, to_int

BASE = "https://www.twse.com.tw/rwd/zh"


def _check_ok(j, what: str, date: str):
    if j.get("stat") != "OK":
        raise NoDataError(f"twse {what} {date}: {j.get('stat')}")


def fetch_daily_quotes(date: str) -> list[Quote]:
    """MI_INDEX type=ALL — every listed security incl. warrants/ETF (~30k rows)."""
    j = get_json(f"{BASE}/afterTrading/MI_INDEX", {"date": date, "type": "ALL", "response": "json"})
    _check_ok(j, "MI_INDEX", date)
    table = None
    for t in j.get("tables", []):
        fields = t.get("fields", [])
        if fields and fields[0] == "證券代號":
            table = t
    if table is None:
        raise RuntimeError(f"twse MI_INDEX {date}: quotes table not found; titles="
                           f"{[t.get('title', '')[:20] for t in j.get('tables', [])]}")
    idx = {name: i for i, name in enumerate(table["fields"])}
    need = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"twse MI_INDEX {date}: missing fields {missing}; got {table['fields']}")
    quotes = []
    for row in table["data"]:
        quotes.append(Quote(
            code=row[idx["證券代號"]].strip(),
            name=row[idx["證券名稱"]].strip(),
            market="twse",
            open=to_float(row[idx["開盤價"]]),
            high=to_float(row[idx["最高價"]]),
            low=to_float(row[idx["最低價"]]),
            close=to_float(row[idx["收盤價"]]),
            volume=to_int(row[idx["成交股數"]]),
            turnover=to_int(row[idx["成交金額"]]),
            transactions=to_int(row[idx["成交筆數"]]),
        ))
    return quotes


def fetch_institutional(date: str) -> list[InstiRow]:
    """T86 三大法人買賣超(股). foreign = 外陸資(不含外資自營) + 外資自營."""
    j = get_json(f"{BASE}/fund/T86", {"date": date, "selectType": "ALL", "response": "json"})
    _check_ok(j, "T86", date)
    idx = {name: i for i, name in enumerate(j["fields"])}
    need = ["證券代號", "外陸資買賣超股數(不含外資自營商)", "外資自營商買賣超股數",
            "投信買賣超股數", "自營商買賣超股數", "三大法人買賣超股數"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"twse T86 {date}: missing fields {missing}; got {j['fields']}")
    rows = []
    n_fields = len(j["fields"])
    for r in j["data"]:
        if len(r) != n_fields:  # TWSE occasionally emits malformed short rows
            continue
        rows.append(InstiRow(
            code=r[idx["證券代號"]].strip(),
            foreign_net=(to_int(r[idx["外陸資買賣超股數(不含外資自營商)"]]) or 0)
                        + (to_int(r[idx["外資自營商買賣超股數"]]) or 0),
            trust_net=to_int(r[idx["投信買賣超股數"]]) or 0,
            dealer_net=to_int(r[idx["自營商買賣超股數"]]) or 0,
            total_net=to_int(r[idx["三大法人買賣超股數"]]) or 0,
        ))
    return rows


def fetch_margin(date: str) -> list[MarginRow]:
    """MI_MARGN 融資融券彙總(張). Field names repeat between 融資/融券 → positional parse."""
    j = get_json(f"{BASE}/marginTrading/MI_MARGN", {"date": date, "selectType": "ALL", "response": "json"})
    _check_ok(j, "MI_MARGN", date)
    table = None
    for t in j.get("tables", []):
        fields = t.get("fields", [])
        if fields and fields[0] == "代號":
            table = t
    if table is None or not table.get("data"):
        raise NoDataError(f"twse MI_MARGN {date}: detail table empty")
    if len(table["fields"]) != 16:
        raise RuntimeError(f"twse MI_MARGN {date}: layout changed, fields={table['fields']}")
    # 0代號 1名稱 | 融資: 2買進 3賣出 4現金償還 5前日餘額 6今日餘額 7限額
    #             | 融券: 8買進 9賣出 10現券償還 11前日餘額 12今日餘額 13限額 | 14資券互抵 15註記
    rows = []
    for r in table["data"]:
        if len(r) != 16:
            continue
        rows.append(MarginRow(
            code=r[0].strip(),
            margin_balance=to_int(r[6]),
            margin_prev=to_int(r[5]),
            margin_limit=to_int(r[7]),
            short_balance=to_int(r[12]),
            short_prev=to_int(r[11]),
        ))
    return rows
