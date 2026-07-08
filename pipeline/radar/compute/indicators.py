"""Daily technical indicators and V1 technical score."""
from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import text

from .. import schema
from ..db import get_engine, init_db, upsert


def _sma(values: list[float | None], window: int, i: int) -> float | None:
    if i + 1 < window:
        return None
    xs = values[i - window + 1:i + 1]
    if any(v is None for v in xs):
        return None
    return sum(xs) / window  # type: ignore[arg-type]


def _ema(prev: float | None, value: float | None, span: int) -> float | None:
    if value is None:
        return prev
    if prev is None:
        return value
    alpha = 2 / (span + 1)
    return value * alpha + prev * (1 - alpha)


def _rsi14(closes: list[float | None]) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    gains: list[float] = []
    losses: list[float] = []
    avg_gain = avg_loss = None
    for i in range(1, len(closes)):
        if closes[i] is None or closes[i - 1] is None:
            continue
        change = closes[i] - closes[i - 1]  # type: ignore[operator]
        gain = max(change, 0)
        loss = max(-change, 0)
        if i <= 14:
            gains.append(gain)
            losses.append(loss)
            if i == 14:
                avg_gain = sum(gains) / 14
                avg_loss = sum(losses) / 14
        elif avg_gain is not None and avg_loss is not None:
            avg_gain = (avg_gain * 13 + gain) / 14
            avg_loss = (avg_loss * 13 + loss) / 14
        if avg_gain is not None and avg_loss is not None:
            if avg_loss == 0:
                out[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                out[i] = 100 - (100 / (1 + rs))
    return out


def compute_series(price_rows: Iterable[dict]) -> list[dict]:
    """Compute indicator rows for one stock.

    Input rows must be sorted ascending by date and include raw OHLC plus
    adj_factor. Indicator prices are backward-adjusted values.
    """
    rows = list(price_rows)
    closes = [_adj(r.get("close"), r.get("adj_factor")) for r in rows]
    highs = [_adj(r.get("high"), r.get("adj_factor")) for r in rows]
    lows = [_adj(r.get("low"), r.get("adj_factor")) for r in rows]
    volumes = [r.get("volume") for r in rows]
    rsi = _rsi14(closes)

    out = []
    ema12 = ema26 = signal = None
    k_prev = d_prev = 50.0
    prev_macd_hist = prev_k = prev_d = None
    for i, r in enumerate(rows):
        close = closes[i]
        high = highs[i]
        low = lows[i]
        ma5 = _sma(closes, 5, i)
        ma10 = _sma(closes, 10, i)
        ma20 = _sma(closes, 20, i)
        ma60 = _sma(closes, 60, i)

        ema12 = _ema(ema12, close, 12)
        ema26 = _ema(ema26, close, 26)
        macd = None if ema12 is None or ema26 is None else ema12 - ema26
        signal = _ema(signal, macd, 9)
        macd_hist = None if macd is None or signal is None else macd - signal

        high9 = _window_max(lows=None, values=highs, i=i, window=9)
        low9 = _window_min(values=lows, i=i, window=9)
        if close is None or high9 is None or low9 is None or high9 == low9:
            k9 = k_prev
        else:
            rsv = (close - low9) / (high9 - low9) * 100
            k9 = k_prev * 2 / 3 + rsv / 3
        d9 = d_prev * 2 / 3 + k9 / 3

        high20 = _window_max(lows=None, values=closes, i=i, window=20)
        box_high60 = _window_max(lows=None, values=highs, i=i, window=60)
        box_low60 = _window_min(values=lows, i=i, window=60)
        adv20 = _prev_avg(volumes, i, 20)
        volume_ratio = (
            None if adv20 in (None, 0) or volumes[i] is None
            else volumes[i] / adv20
        )

        is_limit_up_20d = False
        is_surge_7pct_20d = False
        if i >= 1:
            for j in range(max(1, i - 19), i + 1):
                if closes[j] is not None and closes[j-1] is not None:
                    if closes[j] >= round(closes[j-1] * 1.095, 2):
                        is_limit_up_20d = True
                    if closes[j] >= round(closes[j-1] * 1.07, 2):
                        is_surge_7pct_20d = True

        has_volume_surge_5d = False
        has_volume_surge_1_5x_5d = False
        if i >= 20:
            for j in range(max(20, i - 4), i + 1):
                adv_j = _prev_avg(volumes, j, 20)
                if adv_j and volumes[j] is not None:
                    if volumes[j] >= adv_j * 2:
                        has_volume_surge_5d = True
                    if volumes[j] >= adv_j * 1.5:
                        has_volume_surge_1_5x_5d = True

        is_macd_golden_cross = False
        is_macd_golden_cross_any = False
        if macd_hist is not None and prev_macd_hist is not None:
            if macd_hist > 0 >= prev_macd_hist:
                is_macd_golden_cross_any = True
                if macd is not None and macd > 0:
                    is_macd_golden_cross = True

        is_mark_strategy = is_limit_up_20d and has_volume_surge_5d and is_macd_golden_cross
        is_mark_strategy_relaxed = is_surge_7pct_20d and has_volume_surge_1_5x_5d and is_macd_golden_cross_any

        score, reasons, risks = score_technical(
            idx=i,
            close=close,
            closes=closes,
            volumes=volumes,
            ma5=ma5,
            ma10=ma10,
            ma20=ma20,
            ma60=ma60,
            high20=high20,
            box_high60=box_high60,
            box_low60=box_low60,
            adv20=adv20,
            volume_ratio=volume_ratio,
            rsi14=rsi[i],
            macd_hist=macd_hist,
            prev_macd_hist=prev_macd_hist,
            k9=k9,
            d9=d9,
            prev_k=prev_k,
            prev_d=prev_d,
            is_mark_strategy=is_mark_strategy,
            is_mark_strategy_relaxed=is_mark_strategy_relaxed,
        )

        out.append({
            "stock_id": r["stock_id"],
            "date": r["date"],
            "ma5": _round(ma5),
            "ma10": _round(ma10),
            "ma20": _round(ma20),
            "ma60": _round(ma60),
            "rsi14": _round(rsi[i], 2),
            "k9": _round(k9, 2),
            "d9": _round(d9, 2),
            "macd": _round(macd, 4),
            "macd_signal": _round(signal, 4),
            "macd_hist": _round(macd_hist, 4),
            "high20": _round(high20),
            "box_high60": _round(box_high60),
            "box_low60": _round(box_low60),
            "adv20": _round(adv20, 2),
            "volume_ratio": _round(volume_ratio, 2),
            "tech_score": score,
            "reasons": json.dumps(reasons, ensure_ascii=False),
            "risks": json.dumps(risks, ensure_ascii=False),
        })
        prev_macd_hist = macd_hist
        prev_k = k9
        prev_d = d9
        k_prev = k9
        d_prev = d9
    return out


def score_technical(**x) -> tuple[int, list[dict], list[dict]]:
    score = 0
    reasons: list[dict] = []
    risks: list[dict] = []
    close = x["close"]
    if close is None:
        return score, reasons, risks

    def add(points: int, code: str, text: str, value=None):
        nonlocal score
        score += points
        reasons.append({"code": code, "points": points, "text": text, "value": value})

    ma20 = x["ma20"]
    ma60 = x["ma60"]
    if ma20 is not None and close > ma20:
        add(10, "T1_MA20", "收盤站上20日線", _round(close / ma20, 3))
    if ma60 is not None and close > ma60:
        add(10, "T1_MA60", "收盤站上60日線", _round(close / ma60, 3))
    if all(v is not None for v in (x["ma5"], x["ma10"], ma20)) and x["ma5"] > x["ma10"] > ma20:
        add(15, "T1_BULL_MA", "5/10/20日均線多頭排列")

    i = x["idx"]
    closes = x["closes"]
    prior20 = [v for v in closes[max(0, i - 20):i] if v is not None]
    is_high20 = len(prior20) >= 19 and close > max(prior20)
    if is_high20:
        add(15, "T2_20D_HIGH", "收盤創20日新高", _round(close))
        if x["volume_ratio"] is not None and x["volume_ratio"] >= 1.5:
            add(10, "T2_VOLUME_BREAKOUT", "突破日成交量達20日均量1.5倍", _round(x["volume_ratio"], 2))

    box_high60 = x["box_high60"]
    box_low60 = x["box_low60"]
    if box_high60 and box_low60 and box_low60 > 0:
        amp = (box_high60 - box_low60) / box_low60
        near_top = close >= box_high60 - (box_high60 - box_low60) * 0.1
        if amp < 0.25 and near_top:
            add(15, "T3_BOX_TOP", "60日箱型整理且收盤接近區間上緣", _round(amp, 3))

    volumes = x["volumes"]
    if i >= 2 and all(v is not None for v in (closes[i], closes[i - 1], closes[i - 2], volumes[i], volumes[i - 1], volumes[i - 2])):
        if closes[i] > closes[i - 1] > closes[i - 2] and volumes[i] > volumes[i - 1] > volumes[i - 2]:
            add(10, "T4_PRICE_VOLUME_UP", "連2日量增價漲")

    rsi14 = x["rsi14"]
    if rsi14 is not None:
        if 50 <= rsi14 <= 70:
            add(5, "T5_RSI", "RSI14位於50至70的健康動能區", _round(rsi14, 2))
        elif rsi14 > 80:
            risks.append({"code": "R_RSI_OVERHEAT", "text": "RSI14超過80,短線動能過熱", "value": _round(rsi14, 2)})

    if x["macd_hist"] is not None and x["prev_macd_hist"] is not None:
        if x["macd_hist"] > 0 >= x["prev_macd_hist"]:
            add(5, "T5_MACD_HIST_POS", "MACD柱狀體翻正", _round(x["macd_hist"], 4))

    if None not in (x["k9"], x["d9"], x["prev_k"], x["prev_d"]):
        if x["k9"] > x["d9"] and x["prev_k"] <= x["prev_d"] and x["k9"] < 50 and x["d9"] < 50:
            add(5, "T5_KD_GOLDEN_LOW", "KD於50以下黃金交叉", _round(x["k9"], 2))

    if x.get("is_mark_strategy"):
        add(20, "T6_MARK_STRATEGY", "策略(20日內曾漲停, MACD零上金叉, 5日內爆量)")
    elif x.get("is_mark_strategy_relaxed"):
        add(15, "T6_MARK_STRATEGY_RELAXED", "相近策略(20日內曾大漲, MACD金叉, 5日微量增)")

    return min(score, 100), reasons, risks


# 增量模式的暖機窗:MA240 + 60日箱型 + 緩衝;EMA(MACD)在 300+ 根後殘差可忽略
WARMUP_BARS = 340


def compute_indicators(ids: list[str] | None = None, top: int | None = None,
                       all_stocks: bool = False, days: int | None = None) -> dict:
    """days=None → 全歷史重算(還原因子變動後用);days=N → 增量:
    只取每檔最後 WARMUP+N 根計算、只回寫最後 N 根,且指標已是最新的股票直接跳過。"""
    init_db()
    engine = get_engine()
    with engine.connect() as conn:
        targets = _targets(conn, ids, top, all_stocks)
        skipped = 0
        if days:
            fresh = {r[0] for r in conn.execute(text("""
                SELECT p.stock_id FROM
                  (SELECT stock_id, MAX(date) AS md FROM daily_prices GROUP BY stock_id) p
                JOIN
                  (SELECT stock_id, MAX(date) AS mi FROM indicators_daily GROUP BY stock_id) i
                ON i.stock_id = p.stock_id AND i.mi >= p.md
            """))}
            before = len(targets)
            targets = [t for t in targets if t not in fresh]
            skipped = before - len(targets)

    written = done = 0
    for sid in targets:
        with engine.connect() as conn:
            if days:
                price_rows = [dict(r._mapping) for r in conn.execute(text("""
                    SELECT * FROM (
                        SELECT stock_id, date, open, high, low, close, adj_factor, volume
                        FROM daily_prices
                        WHERE stock_id = :sid AND close IS NOT NULL
                        ORDER BY date DESC LIMIT :lim
                    ) ORDER BY date
                """), {"sid": sid, "lim": WARMUP_BARS + days})]
            else:
                price_rows = [dict(r._mapping) for r in conn.execute(text("""
                    SELECT stock_id, date, open, high, low, close, adj_factor, volume
                    FROM daily_prices
                    WHERE stock_id = :sid AND close IS NOT NULL
                    ORDER BY date
                """), {"sid": sid})]
        rows = compute_series(price_rows)
        if days:
            rows = rows[-days:]
        with engine.begin() as conn:
            written += upsert(conn, schema.indicators_daily, rows)
        done += 1
        if not days:
            print(f"indicators {sid} ok: {len(rows)} rows", flush=True)
    print(f"indicators: {done} computed, {skipped if days else 0} already fresh, "
          f"{written} rows written", flush=True)
    return {"done": done, "rows": written}


def _targets(conn, ids: list[str] | None, top: int | None, all_stocks: bool) -> list[str]:
    if ids:
        return ids
    if top:
        return [r[0] for r in conn.execute(text("""
            SELECT stock_id FROM daily_prices
            WHERE date = (SELECT MAX(date) FROM daily_prices)
              AND turnover IS NOT NULL
            ORDER BY turnover DESC LIMIT :n
        """), {"n": top}).fetchall()]
    if all_stocks:
        return [r[0] for r in conn.execute(text("""
            SELECT DISTINCT s.id
            FROM stocks s
            JOIN daily_prices p ON p.stock_id = s.id
            WHERE s.type IN ('stock', 'etf')
            ORDER BY s.id
        """)).fetchall()]
    raise SystemExit("compute-indicators needs --ids, --top or --all")


def _adj(value, factor):
    if value is None:
        return None
    return value * (factor or 1.0)


def _round(value, digits=2):
    return None if value is None else round(value, digits)


def _window_max(lows, values: list[float | None], i: int, window: int):
    if i + 1 < window:
        return None
    xs = [v for v in values[i - window + 1:i + 1] if v is not None]
    return max(xs) if len(xs) == window else None


def _window_min(values: list[float | None], i: int, window: int):
    if i + 1 < window:
        return None
    xs = [v for v in values[i - window + 1:i + 1] if v is not None]
    return min(xs) if len(xs) == window else None


def _prev_avg(values: list[int | None], i: int, window: int):
    if i < window:
        return None
    xs = values[i - window:i]
    if any(v is None for v in xs):
        return None
    return sum(xs) / window  # type: ignore[arg-type]
