"""docs/27 G1:匯入公司住址與券商分點地理。不寫 buybacks(無穩定 OpenAPI)。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from . import config, schema
from .db import get_engine, init_db, upsert
from .geo import (
    classify_broker_kind,
    hq_seat_broker,
    normalize_branch_name,
    parse_city_district,
    transfer_agent_broker,
)
from .importer import _log
from .providers import opendata


def _now() -> str:
    return datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%d")


def _iso_day() -> str:
    return datetime.now(ZoneInfo(config.TZ)).strftime("%Y-%m-%d")


def update_transfer_agent_history(conn, companies: list[dict], day: str) -> list[dict]:
    """股代變動史(docs/37 §3.1):換了券商才新增一段,沒換只推 last_seen。回傳本次變動。

    比的是券商(transfer_agent_broker),不是原文——同一家券商換個寫法(「元大證券股份有限公司」
    →「元大證券(股)公司股務代理部」)不算換股代。這次沒出現在官方表的公司不動(下市/漏列)。
    """
    latest = {
        r[0]: {"first_seen": r[1], "broker": r[2]}
        for r in conn.execute(text(
            "SELECT h.stock_id, h.first_seen, h.broker FROM transfer_agent_history h "
            "JOIN (SELECT stock_id, MAX(first_seen) AS f FROM transfer_agent_history "
            "      GROUP BY stock_id) m ON m.stock_id = h.stock_id AND m.f = h.first_seen"
        ))
    }
    rows: list[dict] = []
    changes: list[dict] = []
    for c in companies:
        sid = c["stock_id"]
        broker = transfer_agent_broker(c.get("transfer_agent"))
        prev = latest.get(sid)
        if prev is not None and prev["broker"] == broker:
            rows.append({"stock_id": sid, "first_seen": prev["first_seen"], "last_seen": day,
                         "agent_text": c.get("transfer_agent")})
            continue
        if prev is not None and prev["first_seen"] >= day:
            # 同一天重跑又換了:覆寫當天那一段,不留零長度的段
            rows.append({"stock_id": sid, "first_seen": prev["first_seen"], "last_seen": day,
                         "broker": broker, "agent_text": c.get("transfer_agent")})
        else:
            rows.append({"stock_id": sid, "first_seen": day, "last_seen": day,
                         "broker": broker, "agent_text": c.get("transfer_agent")})
        if prev is not None:
            changes.append({"stock_id": sid, "from": prev["broker"], "to": broker})
    upsert(conn, schema.transfer_agent_history, rows)
    return changes


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
            "industry_code": r.get("industry_code"),
            "transfer_agent": r.get("transfer_agent"),
            "transfer_agent_phone": r.get("transfer_agent_phone"),
            "transfer_agent_address": r.get("transfer_agent_address"),
            "source": r.get("source"),
            "source_updated_at": r.get("source_updated_at"),
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

    # 股代對照自查(只印報告,不擋匯入):股代券商名要對得到 brokerList 的總公司
    # (kind='hq')。對不到 = 別名表缺一筆或來源改了簡稱,該券商的股代標籤就不會出現。
    agent_brokers = {b for c in companies if (b := transfer_agent_broker(c.get("transfer_agent")))}
    hq_ids = {
        hq_seat_broker(r["branch_name"]): r.get("broker_id")
        for r in geo.values() if r["kind"] == "hq"
    }
    agent_unmatched = sorted(b for b in agent_brokers if b not in hq_ids)

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(schema.company_profiles.delete())
        n_co = upsert(conn, schema.company_profiles, companies)
        conn.execute(schema.broker_branch_geo.delete())
        n_br = upsert(conn, schema.broker_branch_geo, list(geo.values()))
        _log(conn, "twse+tpex", "company_profiles", today, n_co, "ok")
        _log(conn, "twse", "broker_branch_geo", today, n_br, "ok")
        agent_changes = update_transfer_agent_history(conn, companies, _iso_day())
        # 換股代記一筆 import_logs:rows = 變動家數,error 欄當備註放明細
        # (同 branch_coverage 的用法;status 仍是 ok,不讓健康檢查誤判成失敗)。
        _log(conn, "twse+tpex", "transfer_agent_change", today, len(agent_changes), "ok",
             error="; ".join(f"{c['stock_id']}:{c['from']}->{c['to']}" for c in agent_changes)[:2000]
             or None)

    print(
        f"import-geo: companies={n_co} city_ok={city_ok} "
        f"brokers={n_br} hq={sum(1 for r in geo.values() if r['kind']=='hq')} "
        f"foreign={sum(1 for r in geo.values() if r['kind']=='foreign')} "
        f"name_conflicts={conflicts} agent_changes={len(agent_changes)}"
    )
    print(
        "import-geo agent-check: brokers=%d matched_hq=%d unmatched=%s map=%s" % (
            len(agent_brokers), len(agent_brokers) - len(agent_unmatched),
            ",".join(agent_unmatched) or "-",
            ",".join(f"{b}:{hq_ids[b]}" for b in sorted(agent_brokers) if b in hq_ids),
        )
    )
    return {
        "companies": n_co,
        "city_ok": city_ok,
        "brokers": n_br,
        "conflicts": conflicts,
        "agent_changes": agent_changes,
        "agent_unmatched": agent_unmatched,
    }
