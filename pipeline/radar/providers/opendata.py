"""TWSE/TPEx OpenAPI — 公司住址與券商分公司(docs/27 G1)。"""
from ..http import get_json

TWSE_COMPANY = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_COMPANY = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
BROKER_BRANCH = "https://openapi.twse.com.tw/v1/opendata/OpenData_BRK02"
BROKER_HQ = "https://openapi.twse.com.tw/v1/brokerService/brokerList"


def _cell(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def fetch_listed_companies() -> list[dict]:
    rows = get_json(TWSE_COMPANY)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("twse t187ap03_L: unexpected payload")
    out = []
    for r in rows:
        sid = _cell(r, "公司代號", "Code")
        addr = _cell(r, "住址", "地址", "Address")
        if sid:
            out.append({"stock_id": sid, "address": addr or None, "market": "twse"})
    return out


def fetch_otc_companies() -> list[dict]:
    rows = get_json(TPEX_COMPANY)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("tpex t187ap03_O: unexpected payload")
    out = []
    for r in rows:
        sid = _cell(r, "公司代號", "SecuritiesCompanyCode", "Code")
        addr = _cell(r, "Address", "住址", "地址")
        if sid:
            out.append({"stock_id": sid, "address": addr or None, "market": "tpex"})
    return out


def fetch_broker_branches() -> list[dict]:
    rows = get_json(BROKER_BRANCH)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("twse OpenData_BRK02: unexpected payload")
    out = []
    for r in rows:
        name = _cell(r, "名稱", "證券商名稱", "Name")
        if not name:
            continue
        out.append({
            "broker_id": _cell(r, "證券商代號", "Code") or None,
            "branch_name": name,
            "address": _cell(r, "地址", "Address") or None,
        })
    return out


def fetch_broker_hq() -> list[dict]:
    rows = get_json(BROKER_HQ)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("twse brokerList: unexpected payload")
    out = []
    for r in rows:
        name = _cell(r, "Name", "名稱", "證券商名稱")
        if not name:
            continue
        out.append({
            "broker_id": _cell(r, "Code", "證券商代號") or None,
            "branch_name": name,
            "address": _cell(r, "Address", "地址") or None,
        })
    return out
