"""docs/27 G1:匯入公司住址與券商分點地理。不寫 buybacks(無穩定 OpenAPI)。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config, schema
from .db import get_engine, init_db, upsert
from .geo import classify_broker_kind, normalize_branch_name, parse_city_district
from .importer import _log
from .providers import opendata


def _now() -> str:
    return datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")


def import_geo() -> dict:
    """全量覆寫兩張小表(週更;失敗不進交易)。庫藏股 KB 延後。"""
    init_db()
    today = _today()
    stamp = _now()
    listed = opendata.fetch_listed_companies()
    otc = opendata.fetch_otc_companies()
    hqs = opendata.fetch_broker_hq()
    branches = opendata.fetch_broker_branches()

    companies = []
    city_ok = 0
    for r in listed + otc:
        city, district = parse_city_district(r.get("address"))
        if city:
            city_ok += 1
        companies.append({
            "stock_id": r["stock_id"],
            "address": r.get("address"),
            "city": city,
            "district": district,
            "market": r["market"],
            "updated_at": stamp,
        })

    geo: dict[str, dict] = {}
    for r in hqs:
        key = normalize_branch_name(r["branch_name"])
        if not key:
            continue
        city, district = parse_city_district(r.get("address"))
        geo[key] = {
            "name_key": key,
            "broker_id": r.get("broker_id"),
            "branch_name": r["branch_name"],
            "address": r.get("address"),
            "city": city,
            "district": district,
            "kind": "hq",
            "updated_at": stamp,
        }
    conflicts = 0
    for r in branches:
        key = normalize_branch_name(r["branch_name"])
        if not key:
            continue
        city, district = parse_city_district(r.get("address"))
        kind = classify_broker_kind(r["branch_name"], is_hq=False)
        row = {
            "name_key": key,
            "broker_id": r.get("broker_id"),
            "branch_name": r["branch_name"],
            "address": r.get("address"),
            "city": city,
            "district": district,
            "kind": kind if key not in geo else geo[key]["kind"],
            "updated_at": stamp,
        }
        if key in geo and geo[key]["kind"] == "hq":
            # 總公司列優先,分公司檔若同名不覆蓋 kind
            continue
        if key in geo and geo[key]["branch_name"] != r["branch_name"]:
            conflicts += 1
        geo[key] = row

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(schema.company_profiles.delete())
        n_co = upsert(conn, schema.company_profiles, companies)
        conn.execute(schema.broker_branch_geo.delete())
        n_br = upsert(conn, schema.broker_branch_geo, list(geo.values()))
        _log(conn, "twse+tpex", "company_profiles", today, n_co, "ok")
        _log(conn, "twse", "broker_branch_geo", today, n_br, "ok")

    print(
        f"import-geo: companies={n_co} city_ok={city_ok} "
        f"brokers={n_br} hq={sum(1 for r in geo.values() if r['kind']=='hq')} "
        f"foreign={sum(1 for r in geo.values() if r['kind']=='foreign')} "
        f"name_conflicts={conflicts}"
    )
    return {
        "companies": n_co,
        "city_ok": city_ok,
        "brokers": n_br,
        "conflicts": conflicts,
    }
