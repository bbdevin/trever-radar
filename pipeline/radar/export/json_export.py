"""Export frontend JSON files from SQLite.

Until the scoring module exists, the radar page shows dynamic day-driven lists
(hot by turnover / surge by volume ratio / strong by change) plus a sector
money-flow panel built from industry sums vs their 20-day averages.
"""
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from .. import config
from ..db import get_engine, init_db
from .spark_day import attach_spark_day
from ..pocket import apply_pocket
from ..compute.strategy_performance import (
    compute_strategy_performance_from_events,
    fetch_strategy_events,
)
from ..compute.margin_cost import build_margin_cost_series
from ..compute.display_window import display_window_bounds, window_label

# 使用者確認的策略生命週期狀態(2026-08-19 Phase 3 報告後定案)
# Active: 無;Shadow: 其餘;Retired: 停止主介面宣稱有效
_STRATEGY_STATUS: dict[str, str] = {
    "S1_REBOUND": "shadow",
    "S2_BREAKOUT20": "retired",
    "S3_MA_CONVERGE_BREAKOUT": "shadow",
    "S4_VOLATILITY_CONTRACTION": "shadow",
    "S5_PULLBACK_SUPPORT": "retired",
    "S6_HIGH_BASE_BREAKOUT": "shadow",
    "S7_MACD_ZERO_CROSS": "shadow",
    "S8_GAP_BREAKOUT": "shadow",
    "S9_MA5_TREND": "shadow",
    "S10_BOTTOM_MACD": "shadow",
    "S11_INSTI_BREAKOUT": "shadow",
    "S12_BRANCH_ACCUMULATION": "shadow",
    "S13_SHORT_SQUEEZE": "shadow",
}


def derive_radar_state(
    *,
    sources: list[str],
    c_pct: float,
    c5_pct: float,
    technical: dict | None,
    score_risks: list,
    close: float | None,
    stop_price: float | None,
    score_final: float | None,
) -> str | None:
    """Quiet→Armed→Triggered→Extended→Faded（docs/22）。同日近似，無跨日 armed_days。"""
    touched_stop = (
        stop_price is not None
        and close is not None
        and float(close) <= float(stop_price)
    )
    if sources:
        reasons = (technical or {}).get("reasons") or []
        has_t2 = any(r.get("code") == "T2_20D_HIGH" for r in reasons)
        is_breakout = c_pct >= 4.0 or has_t2
        is_quiet = c_pct < 3.0 and c5_pct < 8.0
        tech_risks = (technical or {}).get("risks") or []
        has_risk = bool(score_risks) or bool(tech_risks)
        # Extended：已漲一截 + 既有風險 → 追高風險（§2.3）
        is_extended = has_risk and (
            c_pct >= 7.0
            or c5_pct >= 12.0
            or (is_breakout and (c_pct >= 5.0 or c5_pct >= 10.0))
        )
        if is_extended:
            state: str | None = "extended"
        elif is_breakout:
            state = "triggered"
        elif is_quiet:
            state = "armed"
        else:
            state = None
        if touched_stop:
            return "faded"
        return state
    # 來源已無，但觸及失效價且當日有評分 → Faded（無跨日歷史時的同日近似）
    if touched_stop and score_final is not None:
        return "faded"
    return None



DEFAULT_OUT = config.ROOT / "web" / "public" / "data"

MIN_TURNOVER = 100_000_000

# 樣本門檻:20 日成熟樣本數達此值才視為「有足夠證據」
_MIN_SAMPLES_20D = 30


def _build_strategy_meta() -> dict[str, dict]:
    """Build strategy_meta block for radar.json (read-only, no DB writes).

    Returns a dict keyed by S code, each with:
      status: 'active' | 'shadow' | 'retired'
      label: str
      h5/h10/h20: {samples, win_rate, avg_ret, median_ret}
      sufficient_samples: bool  (h20.samples >= _MIN_SAMPLES_20D)
    """
    try:
        events_by_code = fetch_strategy_events(lookback_dates=180)
        perf = compute_strategy_performance_from_events(events_by_code, recent_events=50)
    except Exception:
        perf = {}

    out: dict[str, dict] = {}
    for code, status in _STRATEGY_STATUS.items():
        p = perf.get(code, {})
        h20 = p.get("per_horizon", {}).get("h20", {})
        h10 = p.get("per_horizon", {}).get("h10", {})
        h5 = p.get("per_horizon", {}).get("h5", {})
        out[code] = {
            "status": status,
            "label": p.get("label", code),
            "h5": h5,
            "h10": h10,
            "h20": h20,
            "sufficient_samples": (h20.get("samples") or 0) >= _MIN_SAMPLES_20D,
        }
    return out          # 榜單門檻:成交金額 1 億
SURGE_MIN_RATIO = 1.5
MIN_WARRANT_TURNOVER = 20_000_000


def _directors_latest_payload(conn, sid: str) -> dict | None:
    """最新申報月董監明細(docs/34 §4.6 D1)。"""
    ym = conn.execute(text(
        "SELECT MAX(as_of_ym) FROM director_holdings WHERE stock_id = :s"
    ), {"s": sid}).scalar()
    if not ym:
        return None
    rows = conn.execute(text("""
        SELECT title, name, shares, shares_at_election, pledged_shares, pledged_pct,
               related_shares, market
        FROM director_holdings
        WHERE stock_id = :s AND as_of_ym = :ym
        ORDER BY shares DESC, name ASC
    """), {"s": sid, "ym": ym}).fetchall()
    if not rows:
        return None
    return {
        "as_of_ym": ym,
        "source": "twse_tpex_openapi",
        "note": "月更；證交所／櫃買董監事持股餘額明細",
        "rows": [
            {
                "title": r[0],
                "name": r[1],
                "shares": r[2],
                "lots": round((r[2] or 0) / 1000, 2),
                "shares_at_election": r[3],
                "pledged_shares": r[4],
                "pledged_pct": r[5],
                "related_shares": r[6],
                "market": r[7],
            }
            for r in rows
        ],
    }


def _insider_monthly_pcts(conn, sid: str) -> list[tuple[str, float]]:
    """(as_of_ym, insider_pct) 升序。pct = 董監目前持股加總 / 該月內最近 TDCC 週股數加總。"""
    monthly = conn.execute(text("""
        SELECT as_of_ym, SUM(shares) AS sh
        FROM director_holdings
        WHERE stock_id = :s
        GROUP BY as_of_ym
        ORDER BY as_of_ym ASC
    """), {"s": sid}).fetchall()
    if not monthly:
        return []
    out: list[tuple[str, float]] = []
    for ym, sh in monthly:
        # 該月最後一天或該月內最後一週 TDCC
        month_end = f"{ym}-28"
        tdcc_shares = conn.execute(text("""
            SELECT SUM(shares) FROM shareholding_dispersion
            WHERE stock_id = :s AND as_of = (
                SELECT MAX(as_of) FROM shareholding_dispersion
                WHERE stock_id = :s AND as_of <= :me AND as_of >= :ms
            )
        """), {"s": sid, "me": month_end, "ms": f"{ym}-01"}).scalar()
        if not tdcc_shares:
            tdcc_shares = conn.execute(text("""
                SELECT SUM(shares) FROM shareholding_dispersion
                WHERE stock_id = :s AND as_of = (
                    SELECT MAX(as_of) FROM shareholding_dispersion
                    WHERE stock_id = :s AND as_of <= :me
                )
            """), {"s": sid, "me": month_end}).scalar()
        if not tdcc_shares or not sh:
            continue
        out.append((ym, round(100.0 * float(sh) / float(tdcc_shares), 4)))
    return out


def _holders_history_payload(conn, sid: str, d: str) -> tuple[list[dict], dict]:
    """Weekly 大戶門檻序列 + display meta + 內部人％ ffill (docs/34 B1/B2/D2)."""
    from ..compute.shareholding import (
        aggregate_all_thresholds,
        aggregate_retail,
        tiers_dict_from_rows,
    )

    today = date.fromisoformat(d)
    display_from, display_to = display_window_bounds(today)
    raw = conn.execute(text("""
        SELECT as_of, tier, holders, shares, pct
        FROM shareholding_dispersion
        WHERE stock_id = :s AND as_of >= :from_d AND as_of <= :to_d
        ORDER BY as_of ASC, tier ASC
    """), {"s": sid, "from_d": display_from, "to_d": display_to}).fetchall()
    db_earliest = conn.execute(text(
        "SELECT MIN(as_of) FROM shareholding_dispersion WHERE stock_id = :s"
    ), {"s": sid}).scalar()
    stock_latest = conn.execute(text(
        "SELECT MAX(as_of) FROM shareholding_dispersion WHERE stock_id = :s"
    ), {"s": sid}).scalar()
    eff_to = display_to
    if stock_latest and stock_latest < eff_to:
        eff_to = stock_latest
    insider_series = _insider_monthly_pcts(conn, sid)
    insider_ym = insider_series[-1][0] if insider_series else None
    meta = {
        "display_from": display_from,
        "display_to": eff_to,
        "db_earliest": db_earliest,
        "window_label": window_label(display_from, eff_to, today),
        "source": "tdcc",
        "note": "週資料、級距為集保分級彙總，≠分點主力",
        "insider_as_of_ym": insider_ym,
        "insider_note": (
            "內部人％＝董監目前持股加總÷集保庫存（月更 ffill；不加關係人合計）"
            if insider_ym
            else None
        ),
    }
    if not raw:
        return [], meta
    by_asof: dict[str, list] = {}
    for as_of, tier, holders, shares, pct in raw:
        by_asof.setdefault(as_of, []).append((tier, holders, shares, pct))
    out = []
    for as_of in sorted(by_asof.keys()):
        rows = by_asof[as_of]
        thresholds = aggregate_all_thresholds(rows)
        retail = aggregate_retail(tiers_dict_from_rows(rows))
        # ffill: 取 as_of 所屬月及之前最後一個有值的申報月
        as_ym = as_of[:7]
        insider_pct = None
        for ym, pct_v in insider_series:
            if ym <= as_ym:
                insider_pct = pct_v
            else:
                break
        out.append({
            "t": as_of,
            "thresholds": thresholds,
            "retail_pct": retail["shares_pct"],
            "retail_holders": retail["holders"],
            "insider_pct": insider_pct,
        })
    out.reverse()  # 新→舊,對齊 margin_history
    return out, meta


def _margin_history_payload(conn, sid: str, d: str) -> tuple[list[dict], dict]:
    today = date.fromisoformat(d)
    display_from, display_to = display_window_bounds(today)
    rows = conn.execute(text("""
        SELECT m.date, m.margin_balance, m.margin_prev, m.margin_limit,
               m.margin_buy, m.margin_sell, m.margin_repay,
               m.short_balance, m.short_prev,
               p.close
        FROM daily_margins m
        LEFT JOIN daily_prices p ON p.stock_id = m.stock_id AND p.date = m.date
        WHERE m.stock_id = :s AND m.date >= :from_d AND m.date <= :to_d
        ORDER BY m.date ASC
    """), {"s": sid, "from_d": display_from, "to_d": display_to}).fetchall()
    db_earliest = conn.execute(text(
        "SELECT MIN(date) FROM daily_margins WHERE stock_id = :s"
    ), {"s": sid}).scalar()
    stock_latest = conn.execute(text(
        "SELECT MAX(date) FROM daily_margins WHERE stock_id = :s"
    ), {"s": sid}).scalar()
    eff_to = display_to
    if stock_latest and stock_latest < eff_to:
        eff_to = stock_latest
    meta = {
        "display_from": display_from,
        "display_to": eff_to,
        "db_earliest": db_earliest,
        "backfill_target_days": 240,
        "window_label": window_label(display_from, eff_to, today),
    }
    if not rows:
        return [], meta
    cost_series = build_margin_cost_series([(r[4], r[1], r[9]) for r in rows])
    out = []
    for i, r in enumerate(rows):
        bal, prev, lim = r[1], r[2], r[3]
        usage = round(bal / lim, 4) if bal is not None and lim else None
        out.append({
            "t": r[0],
            "balance": bal,
            "prev": prev,
            "limit": lim,
            "usage": usage,
            "chg": None if (bal is None or prev is None) else bal - prev,
            "buy": r[4],
            "sell": r[5],
            "repay": r[6],
            "short_balance": r[7],
            "short_prev": r[8],
            "cost_est": round(cost_series[i], 2) if cost_series[i] is not None else None,
        })
    return list(reversed(out)), meta


def _export_margin_usage(out: Path, conn, d: str, m_date: str | None) -> None:
    if not m_date:
        return
    # 收盤價對齊資券資料日 m_date(勿硬綁 quotes 日 d):資券常晚一天,
    # 否則有餘額但當日尚未有價(或停牌)的高使用率股會被 INNER JOIN 整排濾掉。
    rows = conn.execute(text("""
        SELECT m.stock_id, s.name, m.margin_balance, m.margin_prev, m.margin_limit,
               mp.margin_balance AS prev_bal, mp.margin_limit AS prev_lim,
               COALESCE(pm.close, p.close) AS close,
               COALESCE(ppm.close, pp.close) AS prev_close
        FROM daily_margins m
        JOIN stocks s ON s.id = m.stock_id AND s.type = 'stock'
        LEFT JOIN daily_margins mp ON mp.stock_id = m.stock_id AND mp.date = (
            SELECT MAX(date) FROM daily_margins
            WHERE stock_id = m.stock_id AND date < :m_date
        )
        LEFT JOIN daily_prices pm ON pm.stock_id = m.stock_id AND pm.date = :m_date
        LEFT JOIN daily_prices ppm ON ppm.stock_id = m.stock_id AND ppm.date = (
            SELECT MAX(date) FROM daily_prices
            WHERE stock_id = m.stock_id AND date < :m_date
        )
        LEFT JOIN daily_prices p ON p.stock_id = m.stock_id AND p.date = :d
        LEFT JOIN daily_prices pp ON pp.stock_id = m.stock_id AND pp.date = (
            SELECT MAX(date) FROM daily_prices
            WHERE stock_id = m.stock_id AND date < :d
        )
        WHERE m.date = :m_date AND m.margin_limit IS NOT NULL AND m.margin_limit > 0
          AND m.margin_balance IS NOT NULL
    """), {"d": d, "m_date": m_date}).fetchall()
    items = []
    for sid, name, bal, prev, lim, prev_bal, prev_lim, close, prev_close in rows:
        usage = round(bal / lim, 4)
        pb = prev if prev is not None else prev_bal
        pl = prev_lim if prev_lim and prev_lim > 0 else lim
        prev_usage = round(pb / pl, 4) if pb is not None and pl and pl > 0 else None
        usage_chg = round((usage - prev_usage) * 100, 2) if prev_usage is not None else None
        items.append({
            "id": sid,
            "name": name,
            "usage": usage,
            "balance": bal,
            "limit": lim,
            "chg": None if (bal is None or prev is None) else bal - prev,
            "usage_chg": usage_chg,
            "close": close,
        })
    items.sort(key=lambda x: x["usage"], reverse=True)
    items = items[:80]
    rank_dir = out / "rankings"
    rank_dir.mkdir(exist_ok=True)
    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
    (rank_dir / "margin_usage.json").write_text(
        json.dumps({
            "as_of": m_date,
            "data_date": d,
            "generated_at": now,
            "items": items,
        }, ensure_ascii=False),
        encoding="utf-8",
    )


def export_json(out_dir: Path | None = None) -> dict:
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        dates = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 22"))]
        if not dates:
            raise RuntimeError("no data in daily_prices; run import-daily first")
        d = dates[0]
        prev = dates[1] if len(dates) > 1 else None
        d5 = dates[5] if len(dates) > 5 else None
        base20 = dates[1:21]                       # 前 20 個交易日(不含今日)

        # 各資料集「有效資料日」:公布時間不同,晚到的先用最近一日並在前端標示
        def latest(table: str) -> str | None:
            return conn.execute(text(
                f"SELECT MAX(date) FROM {table} WHERE date <= :d"), {"d": d}).scalar()

        i_date = latest("daily_institutional")
        m_date = latest("daily_margins")
        w_date = latest("warrant_stock_daily")
        b_date = latest("branch_trades")
        freshness = {
            "quotes": {"date": d, "stale": False},
            "insti": {"date": i_date, "stale": i_date != d},
            "margin": {"date": m_date, "stale": m_date != d},
            "warrant": {"date": w_date, "stale": w_date != d},
            "branch": {"date": b_date, "stale": b_date != d},
        }

        rows = conn.execute(text("""
            SELECT p.stock_id, s.name, s.market, s.industry, s.description, p.close, p.turnover,
                   p.volume, p.transactions, pp.close AS prev_close,
                   i.foreign_net, i.trust_net, m.margin_balance, m.margin_prev,
                   a.avg_vol20,
                   w.call_turnover, w.call_volume, w.call_count,
                   w.put_turnover, w.put_volume, w.put_count,
                   wa.avg_call_turnover,
                   ti.tech_score, ti.ma20, ti.ma60, ti.rsi14, ti.volume_ratio AS tech_volume_ratio,
                   ti.reasons AS tech_reasons, ti.risks AS tech_risks,
                   ds.final AS score_final, ds.branch_score, ds.warrant_score, ds.inst_score, ds.theme_score,
                   ds.risk_penalty, ds.reasons AS score_reasons, ds.risks AS score_risks,
                   ds.watch_price, ds.stop_price, p5.close AS close5
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            LEFT JOIN daily_prices p5 ON p5.stock_id = p.stock_id AND p5.date = :d5
            LEFT JOIN daily_institutional i ON i.stock_id = p.stock_id AND i.date = :i_date
            LEFT JOIN daily_margins m ON m.stock_id = p.stock_id AND m.date = :m_date
            LEFT JOIN warrant_stock_daily w ON w.stock_id = p.stock_id AND w.date = :w_date
            LEFT JOIN indicators_daily ti ON ti.stock_id = p.stock_id AND ti.date = :d
            LEFT JOIN daily_scores ds ON ds.stock_id = p.stock_id AND ds.date = :d
            LEFT JOIN (
                SELECT stock_id, AVG(volume) AS avg_vol20 FROM daily_prices
                WHERE date >= :d20 AND date < :d GROUP BY stock_id
            ) a ON a.stock_id = p.stock_id
            LEFT JOIN (
                SELECT stock_id, AVG(call_turnover) AS avg_call_turnover
                FROM warrant_stock_daily
                WHERE date >= :d20 AND date < :d
                GROUP BY stock_id
            ) wa ON wa.stock_id = p.stock_id
            WHERE p.date = :d AND p.close IS NOT NULL
        """), {"d": d, "prev": prev, "d5": d5, "d20": base20[-1] if base20 else d,
               "i_date": i_date, "m_date": m_date, "w_date": w_date}).fetchall()

        all_stocks = []
        for r in rows:
            (sid, name, market, industry, description, close, turnover, volume, tx,
             prev_close, f_net, t_net, mb, mp, avg_vol20,
             call_turnover, call_volume, call_count,
             put_turnover, put_volume, put_count, avg_call_turnover,
             tech_score, tech_ma20, tech_ma60, tech_rsi14, tech_volume_ratio,
             tech_reasons, tech_risks,
              score_final, branch_score, warrant_score, inst_score, theme_score,
              risk_penalty, score_reasons, score_risks,
              watch_price, stop_price, close5) = r
            chg_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else None
            chg5_pct = round((close - close5) / close5 * 100, 2) if close5 else None
            vol_ratio = None
            if avg_vol20 and avg_vol20 > 0 and volume:
                vol_ratio = round(volume / avg_vol20, 2)
            warrant = None
            if call_turnover is not None or put_turnover is not None:
                call_turnover = call_turnover or 0
                put_turnover = put_turnover or 0
                ratio = None
                if avg_call_turnover and avg_call_turnover > 0:
                    ratio = round(call_turnover / avg_call_turnover, 2)
                warrant = {
                    "call_turnover": call_turnover,
                    "call_volume": call_volume or 0,
                    "call_count": call_count or 0,
                    "put_turnover": put_turnover,
                    "put_volume": put_volume or 0,
                    "put_count": put_count or 0,
                    "call_avg20": round(avg_call_turnover) if avg_call_turnover is not None else None,
                    "call_turnover_ratio": ratio,
                    "put_call_ratio": round(put_turnover / call_turnover, 2) if call_turnover > 0 else None,
                }
            technical = None
            if tech_score is not None:
                technical = {
                    "score": tech_score,
                    "ma20": tech_ma20,
                    "ma60": tech_ma60,
                    "rsi14": tech_rsi14,
                    "volume_ratio": tech_volume_ratio,
                    "reasons": json.loads(tech_reasons or "[]"),
                    "risks": json.loads(tech_risks or "[]"),
                }
            # Armed / Triggered / Extended / Faded (docs/22)
            c_pct = chg_pct or 0
            c5_pct = chg5_pct or 0
            raw_rs = json.loads(score_reasons or "[]")
            raw_risks = json.loads(score_risks or "[]")
            has_branch = any(r.get("code") == "S12_BRANCH_ACCUMULATION" for r in raw_rs) and (turnover or 0) >= MIN_TURNOVER
            has_warrant = False
            if warrant and warrant.get("call_turnover_ratio") is not None:
                if warrant["call_turnover_ratio"] >= 1.5 and warrant["call_turnover"] >= MIN_WARRANT_TURNOVER:
                    has_warrant = True

            sources = []
            if has_branch:
                sources.append("branch")
            if has_warrant:
                sources.append("warrant")

            state = derive_radar_state(
                sources=sources,
                c_pct=c_pct,
                c5_pct=c5_pct,
                technical=technical,
                score_risks=raw_risks,
                close=close,
                stop_price=stop_price,
                score_final=score_final,
            )

            all_stocks.append({
                "id": sid, "name": name, "market": market, "industry": industry,
                "description": description,
                "close": close, "chg_pct": chg_pct, "chg5_pct": chg5_pct,
                "turnover": turnover, "volume_lots": (volume or 0) // 1000,
                "volume_ratio": vol_ratio, "transactions": tx,
                "foreign_net_lots": None if f_net is None else f_net // 1000,
                "trust_net_lots": None if t_net is None else t_net // 1000,
                "margin_chg_lots": None if (mb is None or mp is None) else mb - mp,
                "warrant": warrant,
                "technical": technical,
                "scores": None if score_final is None else {
                    "final": score_final,
                    "branch": branch_score,
                    "warrant": warrant_score,
                    "tech": tech_score,
                    "inst": inst_score,
                    "theme": theme_score,
                    "risk_penalty": risk_penalty,
                    "watch_price": watch_price,
                    "stop_price": stop_price,
                },
                "state": state,
                "sources": sources,
                "reasons": [x["text"] for x in raw_rs[:4]],
                "raw_reasons": raw_rs,
                "risks": [x["text"] for x in raw_risks[:3]],
            })

        # ── 榜單(動態,依今日行情,保底15檔,上限40檔) ──
        score_all = sorted(
            [s for s in all_stocks if s["scores"]],
            key=lambda s: (s["scores"]["final"], s["turnover"] or 0), reverse=True)
        score = [s for s in score_all if s["scores"]["final"] >= 65]
        if len(score) < 15: score = score_all[:15]
        score = score[:40]

        hot_all = sorted(
            [s for s in all_stocks if s["turnover"] is not None],
            key=lambda s: s["turnover"], reverse=True)
        hot = [s for s in hot_all if s["turnover"] >= 1_000_000_000]
        if len(hot) < 15: hot = hot_all[:15]
        hot = hot[:40]

        surge_all = sorted(
            [s for s in all_stocks if (s["turnover"] or 0) >= MIN_TURNOVER and s["volume_ratio"] is not None],
            key=lambda s: s["volume_ratio"], reverse=True)
        surge = [s for s in surge_all if s["volume_ratio"] >= SURGE_MIN_RATIO]
        if len(surge) < 15: surge = surge_all[:15]
        surge = surge[:40]

        strong_all = sorted(
            [s for s in all_stocks if (s["turnover"] or 0) >= MIN_TURNOVER and s["chg_pct"] is not None],
            key=lambda s: s["chg_pct"], reverse=True)
        strong = [s for s in strong_all if s["chg_pct"] >= 5.0]
        if len(strong) < 15: strong = strong_all[:15]
        strong = strong[:40]

        warrant_all = sorted(
            [s for s in all_stocks if s["warrant"] and s["warrant"]["call_turnover"] >= MIN_WARRANT_TURNOVER],
            key=lambda s: (s["warrant"]["call_turnover_ratio"] or 0, s["warrant"]["call_turnover"]), reverse=True)
        warrant = [s for s in warrant_all if (s["warrant"]["call_turnover_ratio"] or 0) >= 1.5]
        if len(warrant) < 15: warrant = warrant_all[:15]
        warrant = warrant[:40]

        # 弱勢榜:跌幅排序(門檻同強勢,鏡像邏輯)
        weak = [s for s in reversed(strong_all) if (s["chg_pct"] or 0) <= -5.0]
        if len(weak) < 15:
            weak = list(reversed(strong_all))[:15]
        weak = weak[:40]

        # 策略榜單
        STRATEGY_CODES = [
            "S1_REBOUND", "S2_BREAKOUT20", "S3_MA_CONVERGE_BREAKOUT",
            "S4_VOLATILITY_CONTRACTION", "S5_PULLBACK_SUPPORT", "S6_HIGH_BASE_BREAKOUT",
            "S7_MACD_ZERO_CROSS", "S8_GAP_BREAKOUT", "S9_MA5_TREND",
            "S10_BOTTOM_MACD", "S11_INSTI_BREAKOUT", "S12_BRANCH_ACCUMULATION",
            "S13_SHORT_SQUEEZE"
        ]
        # S1 為雙軌:放寬版 S1_REBOUND_RELAXED 併入 S1_REBOUND 榜(對外仍只有一個鍵)
        STRATEGY_CODE_ALIASES = {"S1_REBOUND_RELAXED": "S1_REBOUND"}
        strategies_lists = {code: [] for code in STRATEGY_CODES}
        for s in all_stocks:
            for r in s.get("raw_reasons", []):
                code = STRATEGY_CODE_ALIASES.get(r.get("code"), r.get("code"))
                if code in strategies_lists:
                    strategies_lists[code].append(s)

        def _s1_points(s):
            # 嚴謹版 20 分 > 放寬版 15 分 → 嚴謹排前;同級內依 turnover
            return max((r.get("points") or 0) for r in s.get("raw_reasons", [])
                       if r.get("code") in ("S1_REBOUND", "S1_REBOUND_RELAXED"))

        for code in strategies_lists:
            if code == "S1_REBOUND":
                key = lambda x: (_s1_points(x), x["turnover"] or 0)
            else:
                key = lambda x: x["turnover"] or 0
            strategies_lists[code] = sorted(strategies_lists[code], key=key, reverse=True)[:40]

        union: dict[str, dict] = {}
        for s in score + hot + surge + strong + weak + warrant:
            union[s["id"]] = s
        for st_list in strategies_lists.values():
            for s in st_list:
                union[s["id"]] = s
        for s in union.values():
            s["spark"] = [row[0] for row in conn.execute(text(
                "SELECT close FROM (SELECT close, date FROM daily_prices "
                "WHERE stock_id = :s AND close IS NOT NULL AND date <= :d "
                "ORDER BY date DESC LIMIT 30) ORDER BY date"), {"s": s["id"], "d": d})]
        attach_spark_day(union, d)

        # ── 族群資金流(官方產業別;題材標籤之後人工維護再加) ──
        sector_today: dict[str, dict] = {}
        for s in all_stocks:
            ind = s["industry"]
            if not ind:
                continue
            g = sector_today.setdefault(ind, {"turnover": 0, "up": 0, "down": 0,
                                              "chgs": [], "stocks": []})
            g["turnover"] += s["turnover"] or 0
            if s["chg_pct"] is not None:
                g["chgs"].append(s["chg_pct"])
                if s["chg_pct"] > 0:
                    g["up"] += 1
                elif s["chg_pct"] < 0:
                    g["down"] += 1
            g["stocks"].append(s)

        prior = {r[0]: r[1] for r in conn.execute(text("""
            SELECT s.industry, SUM(p.turnover) * 1.0 / COUNT(DISTINCT p.date)
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            WHERE p.date >= :d20 AND p.date < :d AND s.industry IS NOT NULL
            GROUP BY s.industry
        """), {"d": d, "d20": base20[-1] if base20 else d})}

        total_today = sum(g["turnover"] for g in sector_today.values()) or 1

        def group_payload(name, g, prior_avg):
            top = sorted(g["stocks"], key=lambda s: s["turnover"] or 0, reverse=True)[:8]
            return {
                "name": name,
                "turnover": g["turnover"],
                "share": round(g["turnover"] / total_today * 100, 1),
                "vs20": round(g["turnover"] / prior_avg, 2) if prior_avg else None,
                "avg_chg": round(sum(g["chgs"]) / len(g["chgs"]), 2) if g["chgs"] else None,
                "up": g["up"], "down": g["down"],
                "top": [{"id": s["id"], "name": s["name"], "chg_pct": s["chg_pct"],
                         "turnover": s["turnover"]} for s in top],
            }

        sectors = [group_payload(ind, g, prior.get(ind)) for ind, g in sector_today.items()]
        sectors.sort(key=lambda x: x["turnover"], reverse=True)

        # ── 題材/概念股資金流(富邦概念股分類;成分重疊,share 僅供相對比較) ──
        by_id = {s["id"]: s for s in all_stocks}
        # Initialize themes array for all stocks
        for s in all_stocks:
            s["themes"] = []
            
        theme_groups: dict[str, dict] = {}
        for name, sid in conn.execute(text(
                "SELECT t.name, st.stock_id FROM stock_themes st "
                "JOIN themes t ON t.id = st.theme_id")):
            s = by_id.get(sid)
            if s is None:
                continue
            s["themes"].append(name) # Attach theme name to the stock
            g = theme_groups.setdefault(name, {"turnover": 0, "up": 0, "down": 0,
                                               "chgs": [], "stocks": []})
            g["turnover"] += s["turnover"] or 0
            if s["chg_pct"] is not None:
                g["chgs"].append(s["chg_pct"])
                if s["chg_pct"] > 0:
                    g["up"] += 1
                elif s["chg_pct"] < 0:
                    g["down"] += 1
            g["stocks"].append(s)
        theme_prior = {r[0]: r[1] for r in conn.execute(text("""
            SELECT t.name, SUM(p.turnover) * 1.0 / COUNT(DISTINCT p.date)
            FROM daily_prices p
            JOIN stock_themes st ON st.stock_id = p.stock_id
            JOIN themes t ON t.id = st.theme_id
            WHERE p.date >= :d20 AND p.date < :d
            GROUP BY t.name
        """), {"d": d, "d20": base20[-1] if base20 else d})}
        themes = [group_payload(name, g, theme_prior.get(name))
                  for name, g in theme_groups.items()
                  if len(g["stocks"]) >= 3 and g["turnover"] >= 5e8]
        themes.sort(key=lambda x: x["turnover"], reverse=True)

        # ── 產業下鑽子題材:每個產業內成分股的題材分解(sectors[].subs) ──
        # 口徑同題材聚合,但 group by (industry, theme);篩選:產業內成分 ≥2 檔、
        # 排除與產業同名題材;依 turnover 取前 10,每題材帶產業內金額前 5 成分股。
        sub_prior = {(r[0], r[1]): r[2] for r in conn.execute(text("""
            SELECT s.industry, t.name, SUM(p.turnover) * 1.0 / COUNT(DISTINCT p.date)
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            JOIN stock_themes st ON st.stock_id = p.stock_id
            JOIN themes t ON t.id = st.theme_id
            WHERE p.date >= :d20 AND p.date < :d AND s.industry IS NOT NULL
            GROUP BY s.industry, t.name
        """), {"d": d, "d20": base20[-1] if base20 else d})}
        for sec in sectors:
            ind = sec["name"]
            sub_groups: dict[str, dict] = {}
            for s in sector_today[ind]["stocks"]:
                for tname in s.get("themes", []):
                    if tname == ind:
                        continue
                    g = sub_groups.setdefault(tname, {"turnover": 0, "up": 0, "down": 0,
                                                      "chgs": [], "stocks": []})
                    g["turnover"] += s["turnover"] or 0
                    if s["chg_pct"] is not None:
                        g["chgs"].append(s["chg_pct"])
                        if s["chg_pct"] > 0:
                            g["up"] += 1
                        elif s["chg_pct"] < 0:
                            g["down"] += 1
                    g["stocks"].append(s)
            subs = []
            for tname, g in sub_groups.items():
                if len(g["stocks"]) < 2:
                    continue
                prior_avg = sub_prior.get((ind, tname))
                top = sorted(g["stocks"], key=lambda s: s["turnover"] or 0, reverse=True)[:5]
                subs.append({
                    "name": tname,
                    "turnover": g["turnover"],
                    "vs20": round(g["turnover"] / prior_avg, 2) if prior_avg else None,
                    "avg_chg": round(sum(g["chgs"]) / len(g["chgs"]), 2) if g["chgs"] else None,
                    "up": g["up"], "down": g["down"],
                    "top": [{"id": s["id"], "name": s["name"], "chg_pct": s["chg_pct"]}
                            for s in top],
                })
            if subs:
                subs.sort(key=lambda x: x["turnover"], reverse=True)
                sec["subs"] = subs[:10]

        # ── 集中度躍升榜(探索頁) ──
        conc_rows = conn.execute(text("""
            SELECT ds.stock_id, s.name, s.market, ds.buy_concentration, ds.concentration_avg20
            FROM daily_scores ds
            JOIN stocks s ON s.id = ds.stock_id
            WHERE ds.date = :d AND ds.buy_concentration IS NOT NULL
              AND ds.concentration_avg20 IS NOT NULL AND ds.concentration_avg20 > 0
        """), {"d": d}).fetchall()
        concentration = sorted((
            {
                "id": r[0], "name": r[1], "market": r[2],
                "buy_concentration": round(r[3], 4),
                "concentration_avg20": round(r[4], 4),
                "vs20": round(r[3] / r[4], 2),
            }
            for r in conc_rows
        ), key=lambda x: x["vs20"], reverse=True)[:40]

        # docs/27 G2:地緣/關鍵/題材 tag + 口袋名單(僅排序,不進 daily_scores.final)
        pocket_ids = apply_pocket(
            conn, all_stocks, dates, themes,
            {r["id"] for r in concentration},
        )
        for sid in pocket_ids:
            s = by_id.get(sid)
            if s is None:
                continue
            if sid not in union:
                union[sid] = s
                s["spark"] = [row[0] for row in conn.execute(text(
                    "SELECT close FROM (SELECT close, date FROM daily_prices "
                    "WHERE stock_id = :s AND close IS NOT NULL AND date <= :d "
                    "ORDER BY date DESC LIMIT 30) ORDER BY date"), {"s": sid, "d": d})]

        summary = conn.execute(text("""
            SELECT s.market,
                   SUM(p.turnover),
                   SUM(CASE WHEN pp.close IS NOT NULL AND p.close > pp.close THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pp.close IS NOT NULL AND p.close < pp.close THEN 1 ELSE 0 END)
            FROM daily_prices p
            JOIN stocks s ON s.id = p.stock_id AND s.type = 'stock'
            LEFT JOIN daily_prices pp ON pp.stock_id = p.stock_id AND pp.date = :prev
            WHERE p.date = :d AND p.close IS NOT NULL
            GROUP BY s.market
        """), {"d": d, "prev": prev}).fetchall()

        logs = conn.execute(text("""
            SELECT source, dataset, date, rows, status, MAX(run_at)
            FROM import_logs WHERE dataset IN ('quotes','insti','margin')
            GROUP BY source, dataset, date ORDER BY date DESC, source, dataset LIMIT 12
        """)).fetchall()

    now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")

    # F2: auto-generate summary_text (rule-based, ≤3 sentences, no LLM)
    def _build_summary_text() -> list[str]:
        out_sentences: list[str] = []
        score_count = len(score)
        if score_count > 0:
            branch_triggered = sum(
                1 for s in score if s.get("scores") and (s["scores"].get("branch") or 0) >= 5
            )
            warrant_triggered = sum(
                1 for s in score if s.get("scores") and (s["scores"].get("warrant") or 0) >= 5
            )
            out_sentences.append(
                f"綜合分池今日 {score_count} 檔"
                + (f"，其中 {branch_triggered} 檔有分點加分訊號" if branch_triggered else "")
                + (f"、{warrant_triggered} 檔有權證加分訊號" if warrant_triggered else "")
                + "。"
            )
        else:
            out_sentences.append("今日綜合分池暫無達門檻標的。")
        # Market summary: biggest market turnover
        if summary:
            top = max(summary, key=lambda x: x[1])
            mkt_label = {"tse": "上市", "otc": "上櫃"}.get(str(top[0]), str(top[0]))
            up_n, down_n = int(top[2]), int(top[3])
            out_sentences.append(
                f"{mkt_label}成交額 {top[1] / 1e8:.0f} 億，漲 {up_n} 跌 {down_n}。"
            )
        # Stale warning
        stale_labels = [
            {"insti": "法人", "margin": "融資券", "warrant": "權證", "branch": "分點"}.get(k, k)
            for k, v in (freshness or {}).items()
            if k != "quotes" and (v.get("stale") if isinstance(v, dict) else False)
        ]
        if stale_labels:
            out_sentences.append(f"{'、'.join(stale_labels)}資料尚未更新，稍後自動補齊。")
        return out_sentences[:3]

    radar = {
        "data_date": d,
        "generated_at": now,
        "freshness": freshness,
        "note": "綜合分=分點/權證/技術/法人/題材加權−風險扣分;≥65 為觀察門檻",
        "pocket_note": "地緣/關鍵僅涵蓋每日評分池(有分點前15大);tag 不進綜合分",
        "summary_text": _build_summary_text(),
        "summary": [
            {"market": m, "turnover": t, "up": up, "down": down}
            for m, t, up, down in summary
        ],
        "sectors": sectors[:16],
        "themes": themes[:36],
        "concentration": concentration,
        "lists": {
            "score": [s["id"] for s in score],
            "hot": [s["id"] for s in hot],
            "surge": [s["id"] for s in surge],
            "strong": [s["id"] for s in strong],
            "weak": [s["id"] for s in weak],
            "warrant": [s["id"] for s in warrant],
            "armed": [s["id"] for s in all_stocks if s.get("state") == "armed"],
            "triggered": [s["id"] for s in all_stocks if s.get("state") == "triggered"],
            "extended": [s["id"] for s in all_stocks if s.get("state") == "extended"],
            "faded": [s["id"] for s in all_stocks if s.get("state") == "faded"],
            "pocket": pocket_ids,
        },
        "strategies": {code: [s["id"] for s in st_list] for code, st_list in strategies_lists.items()},
        "strategy_meta": _build_strategy_meta(),
        "stocks": list(union.values()),
    }
    meta = {
        "generated_at": now,
        "datasets": [
            {"source": s, "dataset": ds, "date": dt, "rows": rw, "status": st, "run_at": ra}
            for s, ds, dt, rw, st, ra in logs
        ],
    }
    (out / "radar.json").write_text(json.dumps(radar, ensure_ascii=False), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    with engine.connect() as conn:
        _export_margin_usage(out, conn, d, m_date)

    # 全市場搜尋索引(id/名稱/市場/產業/描述;compact 陣列省體積)
    with engine.connect() as conn:
        idx = [[r[0], r[1], r[2], r[3] or "", r[4] or ""] for r in conn.execute(text(
            "SELECT id, name, market, industry, description FROM stocks "
            "WHERE type IN ('stock','etf') AND is_active = 1 ORDER BY id"))]
    (out / "stocks_index.json").write_text(
        json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 個股 K 線 JSON(docs/26 WP-M1):全市場 stock/etf 每日更新;
    # 榜單聯集=全歷史;其餘裁近 600 根。不再依賴「當日評分池」才重寫。
    stock_dir = out / "stocks"
    stock_dir.mkdir(exist_ok=True)
    by_id_all = {s["id"]: s for s in all_stocks}
    with engine.connect() as conn:
        # 權證分點(當日,權證代號=6碼)→ {權證id: 前8大進出}
        wb: dict[str, list] = {}
        for r in conn.execute(text(
            "SELECT stock_id, branch_name, buy_lots, sell_lots, net_lots "
            "FROM branch_trades WHERE date = :d AND LENGTH(stock_id) = 6"), {"d": d}):
            wb.setdefault(r[0], []).append(
                {"name": r[1], "buy": r[2], "sell": r[3], "net": r[4]})
        for rows_list in wb.values():
            rows_list.sort(key=lambda x: -abs(x["net"] or 0))
            del rows_list[8:]

        meta_rows = conn.execute(text(
            "SELECT id, name, market, industry, description FROM stocks "
            "WHERE type IN ('stock', 'etf') AND is_active = 1 "
            "AND EXISTS (SELECT 1 FROM daily_prices p WHERE p.stock_id = stocks.id "
            "            AND p.close IS NOT NULL)"
        )).fetchall()
        stock_meta = {r[0]: r for r in meta_rows}
        # 榜單優先(全歷史),其餘依代號排序,穩定輸出
        export_ids = list(dict.fromkeys(
            list(union.keys()) + sorted(stock_meta.keys())
        ))
        for sid in export_ids:
            s = by_id_all.get(sid)
            if s is None:
                m = stock_meta.get(sid)
                if m is None:
                    continue
                # 今日無報價(停牌/未進 quotes)仍匯出最新 K 線,避免個股頁卡在舊 JSON
                s = {
                    "id": m[0], "name": m[1], "market": m[2],
                    "industry": m[3], "description": m[4],
                    "warrant": None, "technical": None, "scores": None,
                    "reasons": [], "raw_reasons": [],
                    "pocket_tags": [], "pocket_score": 0, "risks": [],
                }
            if sid in union:
                candles = conn.execute(text(
                    "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
                    "FROM daily_prices p WHERE p.stock_id = :s AND p.close IS NOT NULL "
                    "ORDER BY p.date"), {"s": sid}).fetchall()
            else:
                candles = list(reversed(conn.execute(text(
                    "SELECT p.date, p.open, p.high, p.low, p.close, p.volume, p.turnover, p.adj_factor "
                    "FROM daily_prices p WHERE p.stock_id = :s AND p.close IS NOT NULL "
                    "ORDER BY p.date DESC LIMIT 600"), {"s": sid}).fetchall()))
            warrant_history = conn.execute(text("""
                SELECT date, call_turnover, put_turnover, call_count, put_count
                FROM warrant_stock_daily
                WHERE stock_id = :s
                ORDER BY date DESC LIMIT 60
            """), {"s": sid}).fetchall()
            active_warrants = conn.execute(text("""
                SELECT w.id, w.name, w.kind, w.strike, w.exercise_ratio, w.maturity_date,
                       d.close, d.volume, d.turnover
                FROM warrant_daily d
                JOIN warrants w ON w.id = d.warrant_id
                WHERE w.stock_id = :s
                  AND d.date = :d
                  AND w.kind IN ('call', 'put')
                  AND d.turnover > 0
                ORDER BY d.turnover DESC
                LIMIT 12
            """), {"s": sid, "d": d}).fetchall()
            stock_branches = conn.execute(text("""
                SELECT branch_name, buy_lots, sell_lots, net_lots, pct
                FROM branch_trades
                WHERE stock_id = :s AND date = :d
                ORDER BY net_lots DESC
            """), {"s": sid, "d": d}).fetchall()

            has_any_branch = conn.execute(text(
                "SELECT 1 FROM branch_trades WHERE stock_id = :s LIMIT 1"
            ), {"s": sid}).scalar()
            if has_any_branch:
                branch_history_rows = conn.execute(text("""
                    SELECT date, branch_name, buy_lots, sell_lots, net_lots
                    FROM branch_trades
                    WHERE stock_id = :s AND date >= date(:d, '-730 days')
                    ORDER BY date DESC
                """), {"s": sid, "d": d}).fetchall()
            else:
                branch_history_rows = []
            insti_history_rows = conn.execute(text("""
                SELECT date, foreign_net, trust_net, dealer_net, total_net
                FROM daily_institutional
                WHERE stock_id = :s AND date >= date(:d, '-400 days')
                ORDER BY date DESC
                LIMIT 240
            """), {"s": sid, "d": d}).fetchall()
            history_by_date: dict[str, list] = {}
            for r in branch_history_rows:
                history_by_date.setdefault(r[0], []).append({
                    "n": r[1], "b": r[2] or 0, "s": r[3] or 0, "net": r[4] or 0
                })
            # 2 年深度;每日僅留淨額前 12 分點,控制 JSON 體積
            branch_history = [
                {"t": dt, "branches": sorted(branches, key=lambda x: -abs(x["net"]))[:12]}
                for dt, branches in sorted(history_by_date.items(), reverse=True)[:480]
            ]
            margin_hist, margin_meta = _margin_history_payload(conn, sid, d)
            holders_hist, holders_meta = _holders_history_payload(conn, sid, d)
            directors_latest = _directors_latest_payload(conn, sid)
            payload = {
                "id": sid, "name": s["name"], "market": s["market"],
                "candles": [
                    {"t": c[0], "o": c[1], "h": c[2], "l": c[3], "c": c[4],
                     "v": (c[5] or 0) // 1000, "amt": c[6], "af": c[7] or 1.0}
                    for c in candles
                ],
                "technical": s["technical"],
                "scores": s["scores"],
                "reasons": s.get("reasons", []),
                "raw_reasons": s.get("raw_reasons", []),
                "pocket_tags": s.get("pocket_tags", []),
                "pocket_score": s.get("pocket_score") or 0,
                "risks": s.get("risks", []),
                "branches": [
                    {"name": r[0], "buy": r[1] or 0, "sell": r[2] or 0,
                     "net": r[3] or 0, "pct": r[4]}
                    for r in stock_branches
                ],
                "branch_history": branch_history,
                "warrant": s["warrant"],
                "warrant_history": [
                    {"t": r[0], "call_turnover": r[1] or 0, "put_turnover": r[2] or 0,
                     "call_count": r[3] or 0, "put_count": r[4] or 0}
                    for r in reversed(warrant_history)
                ],
                "active_warrants": [
                    {"id": r[0], "name": r[1], "kind": r[2], "strike": r[3],
                     "exercise_ratio": r[4], "maturity_date": r[5], "close": r[6],
                     "volume_lots": (r[7] or 0) // 1000, "turnover": r[8] or 0,
                     "branches": wb.get(r[0], [])}
                    for r in active_warrants
                ],
                "insti_history": [
                    {"t": r[0],
                     "foreign": (r[1] or 0) // 1000,
                     "trust": (r[2] or 0) // 1000,
                     "dealer": (r[3] or 0) // 1000,
                     "total": (r[4] or 0) // 1000}
                    for r in insti_history_rows
                ],
                "margin_history": margin_hist,
                "margin_meta": margin_meta,
                "holders_history": holders_hist,
                "holders_meta": holders_meta,
                "directors_latest": directors_latest,
            }
            (stock_dir / f"{sid}.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                
    # ── Export Branches ──
    _export_branches(out, engine, d)
    _export_warrant_branches(out, engine, d, base20)
    _export_tracked_branch_history(out, engine, d)

    return {"out": str(out), "date": d, "stocks": len(export_ids)}

def _export_branches(out: Path, engine, date: str):
    branches_dir = out / "branches"
    branches_dir.mkdir(exist_ok=True)
    with engine.connect() as conn:
        # Rankings：只取最新一次快照(branch_rankings 保留歷史,§5)。
        # 隔日沖分點另列 daytrade 清單,不混入主榜(§3b:它們是反指標/風險訊號)。
        rows = [dict(r._mapping) for r in conn.execute(text(
            "SELECT branch_name, as_of, rank_score, win_rate, avg_ret5, samples, style, is_daytrade, source "
            "FROM branch_rankings "
            "WHERE as_of = (SELECT MAX(as_of) FROM branch_rankings) "
            "ORDER BY rank_score DESC, samples DESC"
        ))]
        rankings = {
            "as_of": rows[0]["as_of"] if rows else None,
            "rankings": [r for r in rows if not r["is_daytrade"]],
            "daytrade": [r for r in rows if r["is_daytrade"]],
        }
        (branches_dir / "rankings.json").write_text(
            json.dumps(rankings, ensure_ascii=False), encoding="utf-8")
            
        # Today's Movements
        today_trades = [dict(r._mapping) for r in conn.execute(text("""
            SELECT b.branch_name, b.stock_id, s.name as stock_name, b.buy_lots, b.sell_lots, b.net_lots, b.pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id
            WHERE b.date = :d AND b.branch_name IN (SELECT branch_name FROM tracked_branches)
            ORDER BY b.branch_name, b.net_lots DESC
        """), {"d": date})]
        
        # Group by branch
        movements = {}
        for r in today_trades:
            bname = r["branch_name"]
            if bname not in movements:
                movements[bname] = []
            movements[bname].append(r)
            
        (branches_dir / "today.json").write_text(
            json.dumps(movements, ensure_ascii=False), encoding="utf-8")

        # 權證分點異動:近 40 個交易日,分點對單一權證的大額淨買(≥300 張)
        d40 = conn.execute(text(
            "SELECT MIN(date) FROM (SELECT DISTINCT date FROM daily_prices "
            "ORDER BY date DESC LIMIT 40)")).scalar()
        movers = [dict(r._mapping) for r in conn.execute(text("""
            SELECT b.branch_name,
                   b.stock_id AS warrant_id, w.name AS warrant_name, w.kind,
                   w.stock_id AS underlying_id, s.name AS underlying_name,
                   SUM(b.net_lots) AS net_lots, SUM(b.buy_lots) AS buy_lots,
                   COUNT(*) AS active_days, MAX(b.date) AS last_date
            FROM branch_trades b
            JOIN warrants w ON w.id = b.stock_id
            LEFT JOIN stocks s ON s.id = w.stock_id
            WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d40
            GROUP BY b.branch_name, b.stock_id
            HAVING SUM(b.net_lots) >= 300
            ORDER BY SUM(b.net_lots) DESC
            LIMIT 60
        """), {"d40": d40})]
        (branches_dir / "warrant_movers.json").write_text(
            json.dumps(movers, ensure_ascii=False), encoding="utf-8")

def _export_warrant_branches(out: Path, engine, date: str, base20: list[str]):
    branches_dir = out / "branches"
    branches_dir.mkdir(exist_ok=True)
    with engine.connect() as conn:
        dates = [r[0] for r in conn.execute(text("SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 120"))]
        if not dates:
            return
        
        d1 = dates[0]
        d2 = dates[1] if len(dates) > 1 else d1
        d5 = dates[4] if len(dates) > 4 else d2
        d30 = dates[29] if len(dates) > 29 else dates[-1]
        d120 = dates[-1]

        # Calculate estimated NTD amount: net_lots * 1000 * price
        # Since warrant_daily might miss some days, we fallback to 1.0 if unknown, though usually it's there.
        # We query per warrant to provide breakdown.
        rows = conn.execute(text("""
            SELECT 
                b.branch_name,
                w.stock_id AS underlying_id,
                s.name AS underlying_name,
                b.stock_id AS warrant_id,
                w.name AS warrant_name,
                w.kind,
                SUM(CASE WHEN b.date >= :d1 THEN b.net_lots ELSE 0 END) AS net_lots_1d,
                SUM(CASE WHEN b.date >= :d1 THEN b.net_lots * 1000 * COALESCE(wd.close, 1.0) ELSE 0 END) AS net_amt_1d,
                SUM(CASE WHEN b.date >= :d2 THEN b.net_lots ELSE 0 END) AS net_lots_2d,
                SUM(CASE WHEN b.date >= :d2 THEN b.net_lots * 1000 * COALESCE(wd.close, 1.0) ELSE 0 END) AS net_amt_2d,
                SUM(CASE WHEN b.date >= :d5 THEN b.net_lots ELSE 0 END) AS net_lots_5d,
                SUM(CASE WHEN b.date >= :d5 THEN b.net_lots * 1000 * COALESCE(wd.close, 1.0) ELSE 0 END) AS net_amt_5d,
                SUM(CASE WHEN b.date >= :d30 THEN b.net_lots ELSE 0 END) AS net_lots_30d,
                SUM(CASE WHEN b.date >= :d30 THEN b.net_lots * 1000 * COALESCE(wd.close, 1.0) ELSE 0 END) AS net_amt_30d,
                SUM(CASE WHEN b.date >= :d120 THEN b.net_lots ELSE 0 END) AS net_lots_120d,
                SUM(CASE WHEN b.date >= :d120 THEN b.net_lots * 1000 * COALESCE(wd.close, 1.0) ELSE 0 END) AS net_amt_120d
            FROM branch_trades b
            JOIN warrants w ON w.id = b.stock_id
            JOIN stocks s ON s.id = w.stock_id
            LEFT JOIN warrant_daily wd ON wd.warrant_id = b.stock_id AND wd.date = b.date
            WHERE LENGTH(b.stock_id) = 6 AND b.date >= :d120
              AND s.type = 'stock'
              AND s.name NOT LIKE '%指%'
            GROUP BY b.branch_name, w.stock_id, s.name, b.stock_id, w.name, w.kind
        """), {"d1": d1, "d2": d2, "d5": d5, "d30": d30, "d120": d120}).fetchall()

        # Group by timeframe for frontend
        results = {
            "1d": [], "2d": [], "5d": [], "30d": [], "120d": []
        }
        
        grouped = {}
        for r in rows:
            m = dict(r._mapping)
            key = (m["branch_name"], m["underlying_id"], m["underlying_name"])
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(m)
            
        for (branch_name, underlying_id, underlying_name), warrants in grouped.items():
            for tf in ["1d", "2d", "5d", "30d", "120d"]:
                total_amt = sum(w[f"net_amt_{tf}"] for w in warrants)
                if abs(total_amt) >= 5000000:
                    breakdown = []
                    for w in warrants:
                        w_amt = w[f"net_amt_{tf}"]
                        if abs(w_amt) > 0:
                            breakdown.append({
                                "warrant_id": w["warrant_id"],
                                "warrant_name": w["warrant_name"],
                                "kind": w["kind"],
                                "net_lots": int(w[f"net_lots_{tf}"]),
                                "net_amount": int(w_amt)
                            })
                    breakdown.sort(key=lambda x: -abs(x["net_amount"]))
                    
                    results[tf].append({
                        "branch_name": branch_name,
                        "underlying_id": underlying_id,
                        "underlying_name": underlying_name,
                        "net_amount": int(total_amt),
                        "breakdown": breakdown
                    })
                
        # Sort each list by absolute net amount
        for k in results:
            results[k].sort(key=lambda x: -abs(x["net_amount"]))

        (branches_dir / "warrant_branches.json").write_text(
            json.dumps(results, ensure_ascii=False), encoding="utf-8")


# 追蹤分點近 N 日明細:每個 tracked branch 一檔精簡 [date, stock_id, net_lots, pct] 列表,
# 前端做任意區間加總(docs/24 §3)。以 branch_name 為聚合單位(與 rankings/today 一致);
# 檔名用 branch_name 的 sha1 前 16 碼(URL/檔名安全、確定性),前端由 index.json 取得對照。
TRACK_WINDOW_DAYS = 120          # 近 N 個日曆日
TRACK_MAX_ROWS = 20_000          # 體積防線:超過則裁到最近 120 個交易日並標 truncated


def _track_safe_key(branch_name: str) -> str:
    return hashlib.sha1(branch_name.encode("utf-8")).hexdigest()[:16]


def _export_tracked_branch_history(out: Path, engine, date: str):
    track_dir = out / "branches" / "track"
    track_dir.mkdir(parents=True, exist_ok=True)
    # 清理:每次重寫該目錄,舊分點檔案不殘留
    for stale in track_dir.glob("*.json"):
        stale.unlink()

    with engine.connect() as conn:
        tracked = [dict(r._mapping) for r in conn.execute(text(
            "SELECT branch_name, source FROM tracked_branches ORDER BY branch_name"))]
        if not tracked:
            (track_dir / "index.json").write_text("[]", encoding="utf-8")
            return

        # 近 120 日曆日內、tracked 分點的每日×每股淨買超(買賣都要,net 帶正負)。
        # 以 (branch_name, date, stock_id) 聚合:同 branch_name 的多個 branch_key(不同來源頁)
        # net_lots 相加、pct 取平均(單一來源時即原值)。僅取 stocks 表內的證券(排除 6 碼權證)。
        rows = conn.execute(text("""
            SELECT b.branch_name, b.date, b.stock_id,
                   SUM(b.net_lots) AS net_lots, AVG(b.pct) AS pct
            FROM branch_trades b
            JOIN stocks s ON s.id = b.stock_id AND s.type IN ('stock', 'etf')
            WHERE b.branch_name IN (SELECT branch_name FROM tracked_branches)
              AND b.date >= date(:d, '-' || :win || ' days')
            GROUP BY b.branch_name, b.date, b.stock_id
            ORDER BY b.branch_name, b.date, b.stock_id
        """), {"d": date, "win": TRACK_WINDOW_DAYS}).fetchall()

        # 交易日視窗下緣(僅在單分點超量時用於裁切)
        td_cutoff = conn.execute(text(
            "SELECT MIN(date) FROM (SELECT DISTINCT date FROM daily_prices "
            "WHERE date <= :d ORDER BY date DESC LIMIT :win)"),
            {"d": date, "win": TRACK_WINDOW_DAYS}).scalar()

        by_branch: dict[str, list] = {}
        stock_ids: set[str] = set()
        for r in rows:
            m = r._mapping
            by_branch.setdefault(m["branch_name"], []).append(
                [m["date"], m["stock_id"],
                 int(m["net_lots"] or 0),
                 None if m["pct"] is None else round(m["pct"], 2)])
            stock_ids.add(m["stock_id"])

        # 股名 + 期末收盤(as_of 當日或最近有值日,未還原價):rows 出現過的每檔一次查齊
        stock_meta: dict[str, dict] = {}
        if stock_ids:
            meta_rows = conn.execute(text("""
                SELECT s.id, s.name,
                       (SELECT p.close FROM daily_prices p
                        WHERE p.stock_id = s.id AND p.date <= :d AND p.close IS NOT NULL
                        ORDER BY p.date DESC LIMIT 1) AS close
                FROM stocks s WHERE s.id IN :ids
            """).bindparams(bindparam("ids", expanding=True)),
                {"d": date, "ids": sorted(stock_ids)}).fetchall()
            for mid, name, close in meta_rows:
                stock_meta[mid] = {"name": name, "close": close}

    index = []
    for t in tracked:
        bname = t["branch_name"]
        b_rows = by_branch.get(bname, [])
        truncated = False
        if len(b_rows) > TRACK_MAX_ROWS and td_cutoff is not None:
            b_rows = [row for row in b_rows if row[0] >= td_cutoff]
            truncated = True

        used_ids = {row[1] for row in b_rows}
        payload = {
            "branch_name": bname,
            "source": t["source"],
            "as_of": date,
            "days": TRACK_WINDOW_DAYS,
            "rows": b_rows,
            "stocks": {sid: stock_meta[sid] for sid in used_ids if sid in stock_meta},
        }
        if truncated:
            payload["truncated"] = True

        fname = _track_safe_key(bname) + ".json"
        (track_dir / fname).write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")
        index.append({
            "branch_name": bname,
            "source": t["source"],
            "file": fname,
            "rows_count": len(b_rows),
            "first_date": b_rows[0][0] if b_rows else None,
        })

    (track_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
