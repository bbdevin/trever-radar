"""docs/27 G2:地緣買/賣、關鍵分點同買、熱門題材 tag(Shadow,不進綜合分)。"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import text

from .geo import classify_broker_kind, normalize_branch_name
from .theme_lifecycle import eligible_for_hot_theme

DUAL_NORTH = frozenset({"台北市", "新北市"})
GEO_WINDOW = 20
KEY_WINDOW = 5
GEO_VOL_SHARE = 0.005          # 地緣淨額 ≥ 期間成交量 0.5%
GEO_TOP15_SHARE = 0.25         # 或 ≥ 期間前15大總淨買(賣) 25%
GEO_MIN_BROKERS = 2
GEO_STREAK = 3
KEY_VOL_SHARE = 0.003          # 近 5 日淨買 ≥ 成交量 0.3%
KEY_MIN_LOTS = 500
HOT_THEME_VS20 = 1.15
HOT_THEME_TOP = 10
RANK_SCORE_MIN = 70

# 家數 × 佔比兩級:≥3 家且(佔量≥1% 或佔前15≥40%)→ strong
STRONG_BROKERS = 3
STRONG_VOL_SHARE = 0.01
STRONG_TOP15_SHARE = 0.40

POCKET_WEIGHTS = {"GEO": 30, "KEY": 30, "BUYBACK": 15, "THEME": 15, "ARMED_OR_CONC": 10}

# V1 噪音名單可擴;總公司/外資已由 kind 排除
NOISE_NAME_KEYS: frozenset[str] = frozenset()


def broker_family(branch_name: str, broker_id: str | None = None) -> str:
    """不同券商歸戶:優先名稱連字號前綴(G0:BHID 是母券商層,不宜當分點差)。"""
    key = normalize_branch_name(branch_name)
    if "-" in key:
        return key.split("-", 1)[0]
    if broker_id:
        return broker_id
    return key


def in_geo_circle(
    company_city: str | None,
    company_district: str | None,
    branch_city: str | None,
    branch_district: str | None,
) -> bool | None:
    """True/False=可判定;None=抽不到縣市或雙北缺行政區 → fail-safe 不判地緣。"""
    if not company_city or not branch_city:
        return None
    if company_city in DUAL_NORTH:
        if not company_district or not branch_district:
            return None
        return company_city == branch_city and company_district == branch_district
    return company_city == branch_city


def _is_excluded(branch_name: str, geo: dict | None) -> bool:
    key = normalize_branch_name(branch_name)
    if key in NOISE_NAME_KEYS:
        return True
    kind = (geo or {}).get("kind")
    if kind in ("hq", "foreign"):
        return True
    if geo is None and classify_broker_kind(branch_name) in ("hq", "foreign"):
        return True
    return False


def _consecutive_side(net_by_date: dict[str, int], window_dates: list[str], side: str) -> bool:
    """window_dates 由舊到新。缺列視為 0。連買/連賣 ≥ GEO_STREAK 個交易日。"""
    need = 1 if side == "buy" else -1
    run = 0
    for d in window_dates:
        net = net_by_date.get(d, 0)
        hit = net > 0 if need > 0 else net < 0
        run = run + 1 if hit else 0
        if run >= GEO_STREAK:
            return True
    return False


def geo_trigger(
    *,
    company_city: str | None,
    company_district: str | None,
    trades: list[dict],
    geo_by_key: dict[str, dict],
    window_dates: list[str],
    volumes: dict[str, int],
    side: str = "buy",
) -> dict | None:
    """近 20 日三條件皆滿足才回傳 tag dict;否則 None。side=buy|sell。"""
    if not company_city:
        return None
    if company_city in DUAL_NORTH and not company_district:
        return None
    win = set(window_dates)
    want_buy = side == "buy"
    geo_rows = []
    top_side_total = 0
    nets: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    brokers: set[str] = set()
    names_by_broker: dict[str, set[str]] = defaultdict(set)

    for t in trades:
        dt = t["date"]
        if dt not in win:
            continue
        net = int(t.get("net_lots") or 0)
        if want_buy and net > 0:
            top_side_total += net
        elif not want_buy and net < 0:
            top_side_total += abs(net)
        name = t.get("branch_name") or ""
        key = normalize_branch_name(name)
        geo = geo_by_key.get(key)
        if _is_excluded(name, geo):
            continue
        if geo is None or not geo.get("city"):
            continue
        circled = in_geo_circle(
            company_city, company_district, geo.get("city"), geo.get("district"),
        )
        if circled is not True:
            continue
        geo_rows.append(t)
        nets[name][dt] += net
        if (want_buy and net > 0) or (not want_buy and net < 0):
            fam = broker_family(name, (geo or {}).get("broker_id"))
            brokers.add(fam)
            names_by_broker[fam].add(name)

    if len(brokers) < GEO_MIN_BROKERS:
        return None

    geo_net = sum(int(t.get("net_lots") or 0) for t in geo_rows)
    if want_buy and geo_net <= 0:
        return None
    if not want_buy and geo_net >= 0:
        return None
    geo_abs = abs(geo_net)
    period_vol = sum(int(volumes.get(d) or 0) for d in window_dates)
    vol_share = (geo_abs * 1000 / period_vol) if period_vol > 0 else 0.0
    top_share = (geo_abs / top_side_total) if top_side_total > 0 else 0.0
    if vol_share < GEO_VOL_SHARE and top_share < GEO_TOP15_SHARE:
        return None

    streak_ok = any(
        _consecutive_side(nets[name], window_dates, side) for name in nets
    )
    if not streak_ok:
        return None

    n = len(brokers)
    strong = n >= STRONG_BROKERS and (
        vol_share >= STRONG_VOL_SHARE or top_share >= STRONG_TOP15_SHARE
    )
    branch_names = sorted({n for names in names_by_broker.values() for n in names})
    verb = "買超" if want_buy else "賣超"
    text = (
        f"{n} 家地緣分點{verb}、佔量 {vol_share * 100:.1f}%"
        f"（統計推測，僅每日評分池）"
    )
    return {
        "code": "G1_GEO_BUY" if want_buy else "G2_GEO_SELL",
        "family": "GEO",
        "strength": "strong" if strong else "weak",
        "text": text,
        "brokers": n,
        "branches": branch_names[:8],
        "vol_share": round(vol_share, 4),
        "top15_share": round(top_share, 4),
    }


def key_buy_trigger(
    *,
    trades: list[dict],
    key_keys: set[str],
    window_dates: list[str],
    volumes: dict[str, int],
) -> dict | None:
    """近 5 日任一關鍵分點累計淨買 ≥ 成交量 0.3% 或 ≥ 500 張。"""
    if not key_keys:
        return None
    win = set(window_dates)
    nets: dict[str, int] = defaultdict(int)
    for t in trades:
        if t["date"] not in win:
            continue
        name = t.get("branch_name") or ""
        if normalize_branch_name(name) not in key_keys:
            continue
        nets[name] += int(t.get("net_lots") or 0)
    hits = [(name, net) for name, net in nets.items() if net > 0]
    if not hits:
        return None
    period_vol = sum(int(volumes.get(d) or 0) for d in window_dates)
    qualified = []
    for name, net in sorted(hits, key=lambda x: -x[1]):
        share = (net * 1000 / period_vol) if period_vol > 0 else 0.0
        if net >= KEY_MIN_LOTS or share >= KEY_VOL_SHARE:
            qualified.append((name, net, share))
    if not qualified:
        return None
    shown = [n for n, _, _ in qualified[:3]]
    text = "關鍵分點同買：" + "、".join(shown)
    return {
        "code": "K1_KEY_BUY",
        "family": "KEY",
        "text": text,
        "branches": shown,
    }


def hot_theme_trigger(
    stock_themes: list[str],
    hot_names: list[str],
) -> dict | None:
    """個股題材落在 vs20≥1.15 前 10。"""
    if not stock_themes or not hot_names:
        return None
    hot = set(hot_names)
    hit = [n for n in stock_themes if n in hot]
    if not hit:
        return None
    shown = hit[:3]
    return {
        "code": "H1_HOT_THEME",
        "family": "THEME",
        "text": "題材熱門：" + "、".join(shown),
        "themes": shown,
    }


def hot_theme_names(themes: list[dict], quote_date: str | None = None) -> list[str]:
    """資金流入榜:vs20≥1.15,依 vs20 取前 HOT_THEME_TOP。"""
    ranked = [
        t for t in themes
        if t.get("vs20") is not None and t["vs20"] >= HOT_THEME_VS20
        and eligible_for_hot_theme(
            status=t.get("status"), data_date=t.get("data_date"),
            heat_date=t.get("heat_date"), quote_date=quote_date or "",
        )
    ]
    ranked.sort(key=lambda t: (t.get("vs20") or 0, t.get("turnover") or 0), reverse=True)
    return [t["name"] for t in ranked[:HOT_THEME_TOP] if t.get("name")]


def pocket_score(families: set[str]) -> int:
    """僅供口袋名單排序,不進 daily_scores.final。"""
    score = 0
    if "GEO" in families:
        score += POCKET_WEIGHTS["GEO"]
    if "KEY" in families:
        score += POCKET_WEIGHTS["KEY"]
    if "BUYBACK" in families:
        score += POCKET_WEIGHTS["BUYBACK"]
    if "THEME" in families:
        score += POCKET_WEIGHTS["THEME"]
    if "ARMED" in families or "CONC" in families:
        score += POCKET_WEIGHTS["ARMED_OR_CONC"]
    return score


def pocket_qualifies(families: set[str]) -> bool:
    return len(families) >= 2


def buyback_status(buyback: dict, as_of: str) -> str:
    """Return the fact status under the supplied point-in-time date.

    Completion wins only when MOPS reports Y *and* its period is parseable;
    all other incomplete inputs stay unknown rather than being guessed.
    """
    start, end = buyback.get("start_date"), buyback.get("end_date")
    flag = (buyback.get("completed_flag") or "").strip().upper()
    if not start or not end or start > end:
        return "unknown"
    if flag == "Y":
        return "completed"
    if flag == "N":
        if start <= as_of <= end:
            return "in_progress"
        if as_of > end:
            return "expired"
    return "unknown"


def buyback_window_trigger(buybacks: list[dict], as_of: str) -> dict | None:
    """KB1 is only the inclusive, verifiable MOPS buyback window fact."""
    active = [row for row in buybacks if buyback_status(row, as_of) == "in_progress"]
    if not active:
        return None
    active.sort(key=lambda row: (row.get("end_date") or "", row.get("start_date") or ""), reverse=True)
    first = active[0]
    suffix = f"（另有 {len(active) - 1} 項進行中計畫）" if len(active) > 1 else ""
    return {
        "code": "KB1_BUYBACK_WINDOW",
        "family": "BUYBACK",
        "text": f"庫藏股買回期間：{first['start_date']} 至 {first['end_date']}{suffix}",
    }


@dataclass
class PocketContext:
    companies: dict[str, dict] = field(default_factory=dict)
    geo_by_key: dict[str, dict] = field(default_factory=dict)
    key_keys: set[str] = field(default_factory=set)
    trades: dict[str, list] = field(default_factory=dict)
    volumes: dict[str, dict] = field(default_factory=dict)
    buybacks: dict[str, list] = field(default_factory=dict)


def load_pocket_context(conn, window_dates: list[str], stock_ids: list[str]) -> PocketContext:
    ctx = PocketContext()
    if not window_dates or not stock_ids:
        return ctx
    as_of = window_dates[-1]
    wanted_ids = set(stock_ids)
    ctx.companies = {
        r[0]: {"city": r[1], "district": r[2]}
        for r in conn.execute(text(
            "SELECT stock_id, city, district FROM company_profiles"
        ))
    }
    ctx.geo_by_key = {
        r[0]: {
            "broker_id": r[1], "city": r[2], "district": r[3],
            "kind": r[4], "branch_name": r[5],
        }
        for r in conn.execute(text(
            "SELECT name_key, broker_id, city, district, kind, branch_name "
            "FROM broker_branch_geo"
        ))
    }
    tracked = [r[0] for r in conn.execute(text(
        "SELECT branch_name FROM tracked_branches"
    ))]
    ranked = [r[0] for r in conn.execute(text(
        "SELECT branch_name FROM branch_rankings "
        "WHERE as_of = (SELECT MAX(as_of) FROM branch_rankings) "
        "AND rank_score >= :mn "
        "AND COALESCE(is_daytrade, 0) = 0"
    ), {"mn": RANK_SCORE_MIN})]
    ctx.key_keys = {normalize_branch_name(n) for n in tracked + ranked if n}

    # Point-in-time guard: plans published after the quote date cannot create a
    # historical KB1.  Null source dates are not treated as fresh.
    for row in conn.execute(text("""
        SELECT stock_id, start_date, end_date, completed_flag, report_date, source_updated_at
        FROM buybacks
        WHERE report_date IS NOT NULL AND report_date <= :as_of
          AND source_updated_at IS NOT NULL AND source_updated_at <= :as_of
    """), {"as_of": as_of}).mappings():
        if row["stock_id"] in wanted_ids:
            ctx.buybacks.setdefault(row["stock_id"], []).append(dict(row))

    lo, hi = window_dates[0], window_dates[-1]
    want = set(stock_ids)
    for r in conn.execute(text(
        "SELECT stock_id, date, branch_name, net_lots "
        "FROM branch_trades "
        "WHERE date >= :lo AND date <= :hi AND LENGTH(stock_id) = 4"
    ), {"lo": lo, "hi": hi}):
        if r[0] not in want:
            continue
        ctx.trades.setdefault(r[0], []).append({
            "date": r[1], "branch_name": r[2], "net_lots": r[3] or 0,
        })
    trade_ids = list(ctx.trades)
    if trade_ids:
        for i in range(0, len(trade_ids), 400):
            chunk = trade_ids[i:i + 400]
            placeholders = ",".join(f":s{j}" for j in range(len(chunk)))
            params = {f"s{j}": sid for j, sid in enumerate(chunk)}
            params.update({"lo": lo, "hi": hi})
            for r in conn.execute(text(
                f"SELECT stock_id, date, volume FROM daily_prices "
                f"WHERE date >= :lo AND date <= :hi AND stock_id IN ({placeholders})"
            ), params):
                ctx.volumes.setdefault(r[0], {})[r[1]] = r[2] or 0
    return ctx


def tag_stock(
    sid: str,
    stock: dict,
    ctx: PocketContext,
    window20: list[str],
    window5: list[str],
    hot_names: list[str],
    conc_ids: set[str],
) -> None:
    """在 stock dict 掛 pocket_tags / pocket_score / pocket_families。不改 scores。"""
    co = ctx.companies.get(sid) or {}
    trades = ctx.trades.get(sid, [])
    vols = ctx.volumes.get(sid, {})
    tags = []
    geo_buy = geo_trigger(
        company_city=co.get("city"),
        company_district=co.get("district"),
        trades=trades,
        geo_by_key=ctx.geo_by_key,
        window_dates=window20,
        volumes=vols,
        side="buy",
    )
    if geo_buy:
        tags.append(geo_buy)
    geo_sell = geo_trigger(
        company_city=co.get("city"),
        company_district=co.get("district"),
        trades=trades,
        geo_by_key=ctx.geo_by_key,
        window_dates=window20,
        volumes=vols,
        side="sell",
    )
    if geo_sell:
        tags.append(geo_sell)
    key = key_buy_trigger(
        trades=trades,
        key_keys=ctx.key_keys,
        window_dates=window5,
        volumes=vols,
    )
    if key:
        tags.append(key)
    # Export provides `_active_themes` even when it is an empty list. That makes
    # legacy/unknown, stale, and retired classifications fail closed for H1.
    theme = hot_theme_trigger(stock.get("_active_themes", stock.get("themes") or []), hot_names)
    if theme:
        tags.append(theme)
    buyback = buyback_window_trigger(ctx.buybacks.get(sid, []), window20[-1]) if window20 else None
    if buyback:
        tags.append(buyback)

    families = {t["family"] for t in tags}
    if stock.get("state") in ("armed", "triggered"):
        families.add("ARMED")
    if sid in conc_ids:
        families.add("CONC")
    stock["pocket_tags"] = tags
    stock["pocket_families"] = sorted(families)
    stock["pocket_score"] = pocket_score(families)


def apply_pocket(
    conn,
    all_stocks: list[dict],
    trading_dates_desc: list[str],
    themes: list[dict],
    conc_ids: set[str],
) -> list[str]:
    """Export 掛 tag。回傳口袋名單 id(≥2 family,pocket_score 降序,最多 40)。"""
    window20 = list(reversed(trading_dates_desc[:GEO_WINDOW]))
    window5 = list(reversed(trading_dates_desc[:KEY_WINDOW]))
    ids = [s["id"] for s in all_stocks]
    ctx = load_pocket_context(conn, window20, ids)
    quote_date = trading_dates_desc[0] if trading_dates_desc else None
    hot = hot_theme_names(themes, quote_date)
    for s in all_stocks:
        tag_stock(s["id"], s, ctx, window20, window5, hot, conc_ids)
    pocket = [
        s for s in all_stocks
        if pocket_qualifies(set(s.get("pocket_families") or []))
    ]
    pocket.sort(key=lambda s: (s.get("pocket_score") or 0, s.get("turnover") or 0), reverse=True)
    return [s["id"] for s in pocket[:40]]
