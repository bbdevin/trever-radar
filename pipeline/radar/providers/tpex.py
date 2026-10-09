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
    """dailyQuotes type=AL — all OTC securities incl. 7xxxxx warrants (~10k rows).

    TPEx often has not populated this table at 14:10 (TWSE MI_INDEX is usually ready).
    Callers retry at 16:10 / 17:40 / 22:00; empty → NoDataError, not a hard fail.
    """
    j = get_json(
        f"{BASE}/afterTrading/dailyQuotes",
        {"date": roc_date(date), "type": "AL", "response": "json"},
        # 520 is a known intermittent TPEx edge/origin response.  It alone
        # gets five total attempts.  2026-10-06 and 10-08: the ~10k-row body is
        # also cut short mid-stream (ChunkedEncodingError) three times in a
        # row at 16:30; that transport failure gets five attempts here too
        # (linear 5/10/15/20 s backoff, +50 s worst case).  Other endpoints
        # keep the ordinary three.
        retries=5, status_retries={520: 5}, backoff_base=5.0,
        exponential_backoff=True, jitter_max=2.0,
    )
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


def fetch_ex_rights(start: str, end: str) -> list[dict]:
    """bulletin/exDailyQ 上櫃除權除息計算結果表,start/end = YYYYMMDD(含兩端)。

    與 twse.fetch_ex_rights 同形:``[{"date": "YYYY-MM-DD", "code": ...}]``,
    **只拿來挑股票代號**。區間內沒有資料時 stat=ok、data 為空 → 空清單。
    """
    j = get_json(f"{BASE}/bulletin/exDailyQ",
                 {"startDate": roc_date(start), "endDate": roc_date(end), "response": "json"})
    if str(j.get("stat", "")).lower() != "ok":
        raise RuntimeError(f"tpex exDailyQ {start}-{end}: stat={j.get('stat')}")
    tables = j.get("tables") or []
    if not tables:
        raise RuntimeError(f"tpex exDailyQ {start}-{end}: no tables")
    table = tables[0]
    fields = [str(f).strip() for f in table.get("fields") or []]
    idx = {name: i for i, name in enumerate(fields)}
    missing = [n for n in ("除權息日期", "代號") if n not in idx]
    if missing:
        raise RuntimeError(f"tpex exDailyQ {start}-{end}: missing fields {missing}; got {fields}")
    out = []
    for row in table.get("data") or []:
        parts = str(row[idx["除權息日期"]]).strip().split("/")
        code = str(row[idx["代號"]]).strip()
        if len(parts) != 3 or not all(p.isdigit() for p in parts) or not code:
            raise RuntimeError(f"tpex exDailyQ {start}-{end}: unparseable row {row[:3]}")
        y, mo, d = (int(x) for x in parts)
        out.append({"date": f"{y + 1911:04d}-{mo:02d}-{d:02d}", "code": code})
    return out


def fetch_warrant_master() -> list[dict]:
    """TPEx OpenAPI 權證發行基本資料(一般 + 牛熊 + 展延型)。直接含標的代號。"""
    from ..classify import warrant_kind

    out = []
    for path, cbbc in (("tpex_warrant_issue", False),
                       ("tpex_warrant_wcb_issue", True),
                       ("tpex_warrant_wxy_issue", True)):
        rows = get_json(f"https://www.tpex.org.tw/openapi/v1/{path}")
        if not isinstance(rows, list):
            continue
        for r in rows:
            code = str(r.get("Code", "")).strip()
            if not code:
                continue
            exp = str(r.get("ExpiryDate", "")).strip()  # YYYYMMDD
            maturity = f"{exp[:4]}-{exp[4:6]}-{exp[6:8]}" if len(exp) == 8 and exp.isdigit() else None
            if cbbc:
                kind = warrant_kind(code)               # 牛熊/展延依代號尾碼
            else:
                kind = "put" if str(r.get("Type", "")).strip() == "認售" else "call"
            out.append({
                "id": code,
                "kind": kind,
                "stock_id": str(r.get("UnderlyingStockCode", "")).strip() or None,
                "strike": to_float(r.get("LatestExercisePrice")),
                "exercise_ratio": to_float(r.get("Latest ExerciseRatio")),
                "maturity_date": maturity,
            })
    return out


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
    """margin/balance 融資融券餘額(張). Unique field names → name lookup.

    Real header (checked 2024-01 … 2026-10): 代號 名稱 前資餘額(張) 資買 資賣 現償
    資餘額 資屬證金 資使用率(%) 資限額 前券餘額(張) 券賣 券買 券償 券餘額 … 備註.
    Note the 融券 side lists 券賣 before 券買. Every column we store is required:
    the flow columns used to be optional under guessed names (資買進/券賣出/…),
    which never matched, so margin_buy etc. were silently NULL for all TPEx rows.
    """
    j = get_json(f"{BASE}/margin/balance", {"date": roc_date(date), "response": "json"})
    table = _table(j, "margin/balance", date, "代號")
    fields = [f.strip() for f in table["fields"]]
    idx = {name: i for i, name in enumerate(fields)}
    need = ["代號", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資限額",
            "前券餘額(張)", "券賣", "券買", "券償", "券餘額"]
    missing = [n for n in need if n not in idx]
    if missing:
        raise RuntimeError(f"tpex margin {date}: missing fields {missing}; got {fields}")
    rows = []
    for r in table["data"]:
        rows.append(MarginRow(
            code=str(r[idx["代號"]]).strip(),
            margin_buy=to_int(r[idx["資買"]]),
            margin_sell=to_int(r[idx["資賣"]]),
            margin_repay=to_int(r[idx["現償"]]),
            margin_balance=to_int(r[idx["資餘額"]]),
            margin_prev=to_int(r[idx["前資餘額(張)"]]),
            margin_limit=to_int(r[idx["資限額"]]),
            short_buy=to_int(r[idx["券買"]]),
            short_sell=to_int(r[idx["券賣"]]),
            short_repay=to_int(r[idx["券償"]]),
            short_balance=to_int(r[idx["券餘額"]]),
            short_prev=to_int(r[idx["前券餘額(張)"]]),
        ))
    return rows
