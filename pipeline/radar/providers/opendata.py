"""TWSE/TPEx OpenAPI — 公司基本資料與券商分公司(docs/27 G1 / docs/37 B)。"""
from datetime import date
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


def _source_date(value: str) -> str | None:
    """Normalize official Gregorian or ROC YYYYMMDD dates without guessing."""
    value = value.strip()
    if not value:
        return None
    digits = "".join(c for c in value if c.isdigit())
    if len(digits) == 7:  # ROC YYYMMDD, e.g. 1150826
        year = int(digits[:3]) + 1911
        month = int(digits[3:5])
        day = int(digits[5:7])
    elif len(digits) == 8:
        year = int(digits[:4])
        month = int(digits[4:6])
        day = int(digits[6:8])
        if year < 1911:
            year += 1911
    else:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _company_row(row: dict, *, market: str, source: str, keys: dict[str, tuple[str, ...]]) -> dict | None:
    sid = _cell(row, *keys["stock_id"])
    if not sid:
        return None
    return {
        "stock_id": sid,
        "address": _cell(row, *keys["address"]) or None,
        # Keep this as text: official codes can have meaningful leading zeros.
        "industry_code": _cell(row, *keys["industry_code"]) or None,
        "transfer_agent": _cell(row, *keys["transfer_agent"]) or None,
        "transfer_agent_phone": _cell(row, *keys["transfer_agent_phone"]) or None,
        "transfer_agent_address": _cell(row, *keys["transfer_agent_address"]) or None,
        "market": market,
        "source": source,
        "source_updated_at": _source_date(_cell(row, *keys["source_updated_at"])),
    }


def fetch_listed_companies() -> list[dict]:
    rows = get_json(TWSE_COMPANY)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("twse t187ap03_L: unexpected payload")
    keys = {
        "stock_id": ("公司代號",), "address": ("住址",), "industry_code": ("產業別",),
        "transfer_agent": ("股票過戶機構",), "transfer_agent_phone": ("過戶電話",),
        "transfer_agent_address": ("過戶地址",), "source_updated_at": ("出表日期",),
    }
    return [item for r in rows if (item := _company_row(r, market="twse", source=TWSE_COMPANY, keys=keys))]


def fetch_otc_companies() -> list[dict]:
    rows = get_json(TPEX_COMPANY)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("tpex t187ap03_O: unexpected payload")
    keys = {
        "stock_id": ("SecuritiesCompanyCode",), "address": ("Address",),
        "industry_code": ("SecuritiesIndustryCode",), "transfer_agent": ("StockTransferAgent",),
        "transfer_agent_phone": ("StockTransferAgentTelephone",),
        "transfer_agent_address": ("StockTransferAgentAddress",), "source_updated_at": ("Date",),
    }
    return [item for r in rows if (item := _company_row(r, market="tpex", source=TPEX_COMPANY, keys=keys))]


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
