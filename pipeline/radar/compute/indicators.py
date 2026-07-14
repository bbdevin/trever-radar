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


def _stddev(values: list[float | None], window: int, i: int) -> float | None:
    if i + 1 < window:
        return None
    xs = values[i - window + 1:i + 1]
    if any(v is None for v in xs):
        return None
    avg = sum(xs) / window
    variance = sum((x - avg) ** 2 for x in xs) / window
    return variance ** 0.5


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
    opens = [_adj(r.get("open"), r.get("adj_factor")) for r in rows]
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


        std20 = _stddev(closes, 20, i)
        
        score, reasons, risks = score_technical(
            idx=i,
            open_=opens[i],
            high=highs[i],
            low=lows[i],
            close=close,
            opens=opens,
            closes=closes,
            highs=highs,
            lows=lows,
            volumes=volumes,
            ma5=ma5,
            ma10=ma10,
            ma20=ma20,
            ma60=ma60,
            std20=std20,
            high20=high20,
            box_high60=box_high60,
            box_low60=box_low60,
            adv20=adv20,
            volume_ratio=volume_ratio,
            rsi14=rsi[i],
            macd=macd,
            macd_signal=signal,
            macd_hist=macd_hist,
            prev_macd_hist=prev_macd_hist,
            k9=k9,
            d9=d9,
            prev_k=prev_k,
            prev_d=prev_d,
            is_limit_up_20d=is_limit_up_20d,
            has_volume_surge_5d=has_volume_surge_5d,
            is_macd_golden_cross=is_macd_golden_cross,
            is_surge_7pct_20d=is_surge_7pct_20d,
            has_volume_surge_1_5x_5d=has_volume_surge_1_5x_5d,
            is_macd_golden_cross_any=is_macd_golden_cross_any,
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

    def add_strategy(points: int, code: str, text: str, value=None):
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


    # 新增 10 項技術選股策略
    opens, highs, lows = x["opens"], x["highs"], x["lows"]
    open_, high, low = x["open_"], x["high"], x["low"]
    ma10 = x["ma10"]
    std20 = x.get("std20")
    macd = x.get("macd")
    macd_signal = x.get("macd_signal")

    def _val(arr, offset):
        if i - offset >= 0:
            return arr[i - offset]
        return None

    prev_close = _val(closes, 1)
    prev_ma5 = _val([_sma(closes, 5, j) for j in range(i+1)], 1)
    prev_ma20 = _val([_sma(closes, 20, j) for j in range(i+1)], 1)

    chg_pct = (close / prev_close - 1) * 100 if prev_close else 0

    # Helpers
    def get_max_vol(days):
        vols = [v for v in volumes[max(0, i - days + 1):i + 1] if v is not None]
        return max(vols) if vols else 0

    def get_max_high(days):
        h = [v for v in highs[max(0, i - days + 1):i + 1] if v is not None]
        return max(h) if h else float('inf')

    def get_min_low(days):
        l = [v for v in lows[max(0, i - days + 1):i + 1] if v is not None]
        return min(l) if l else 0

    adv20 = x["adv20"] or 0
    vol_ratio = x["volume_ratio"] or 0

    # S1: 漲停基因二次發動(雙軌:嚴謹 20 分,不中再看放寬 15 分;elif 不重複計分)
    if x.get("is_limit_up_20d") and x.get("has_volume_surge_5d") and x.get("is_macd_golden_cross"):
        add_strategy(20, "S1_REBOUND", "漲停基因二次發動(20日內曾漲停, MACD零上金叉, 5日內爆量)")
    elif x.get("is_surge_7pct_20d") and x.get("has_volume_surge_1_5x_5d") and x.get("is_macd_golden_cross_any"):
        add_strategy(15, "S1_REBOUND_RELAXED", "漲停基因二次發動-相近(20日內曾大漲7%, MACD金叉, 5日量增1.5倍)")

    # S2: 20 日新高爆量突破
    # 突破20日高; 量>2倍; 5>10>20; ma20向上; MACD>0且紅柱; 收盤近最高; 突破K無長上影
    if is_high20 and vol_ratio > 2.0 and x["ma5"] and ma10 and ma20 and x["ma5"] > ma10 > ma20:
        if prev_ma20 and ma20 > prev_ma20 and macd and macd > 0 and x["macd_hist"] and x["macd_hist"] > 0:
            if high and open_ and close >= high * 0.985:
                body = abs(close - open_)
                upper = high - max(open_, close)
                if upper <= body * 0.5:
                    add_strategy(20, "S2_BREAKOUT20", "20日新高爆量突破(多頭排列+爆量+實體長紅)")

    # S3: 均線糾結突破
    # 5,10,20接近(最高最低<3%); 收盤站上三均線; ma20向上或走平; 量>1.5; 突破10日高; MACD紅柱增強; RSI>50
    if x["ma5"] and ma10 and ma20:
        mas = [x["ma5"], ma10, ma20]
        if max(mas) / min(mas) < 1.03:
            if close > max(mas) and prev_ma20 and ma20 >= prev_ma20 * 0.999:
                if vol_ratio > 1.5 and close >= get_max_high(10):
                    if x["macd_hist"] and x["prev_macd_hist"] and x["macd_hist"] > x["prev_macd_hist"]:
                        if rsi14 and rsi14 > 50:
                            add_strategy(20, "S3_MA_CONVERGE_BREAKOUT", "均線糾結突破(均線收斂後帶量發動)")

    # S4: 波動收斂後突破
    # 10日振幅縮小; 5日均量低於20日均量70%; 布林寬度近60日低檔; 突破20日高; 量>2倍; 收盤近最高
    if is_high20 and vol_ratio > 2.0 and high and open_ and close >= high * 0.985:
        # Check volume contraction before breakout (avg of previous 5 days)
        prev_5_vols = [v for v in volumes[max(0, i-6):i-1] if v is not None]
        if len(prev_5_vols) == 5 and (sum(prev_5_vols)/5) < adv20 * 0.8:
            # check bollinger width (approximation)
            if std20 and ma20 and (std20 * 4 / ma20) < 0.15:
                add_strategy(20, "S4_VOLATILITY_CONTRACTION", "波動收斂後突破(量縮整理後爆量創高)")

    # S5: 強勢股量縮回踩
    # 20日內漲幅>15% (close / close[i-20]); 5>10>20; ma20向上; 回踩10或20日線(最低價接近); 量縮; 當日收紅; 站回5日線或破昨高
    c20 = _val(closes, 20)
    if c20 and close > c20 * 1.15 and x["ma5"] and ma10 and ma20 and x["ma5"] > ma10 > ma20:
        if prev_ma20 and ma20 > prev_ma20 and vol_ratio < 1.0 and open_ and close > open_:
            if (low and low <= ma10 * 1.02) or (low and low <= ma20 * 1.02):
                if close > x["ma5"] or (prev_close and close > prev_close):
                    add_strategy(20, "S5_PULLBACK_SUPPORT", "強勢股量縮回踩(多頭回踩均線不破且轉強)")

    # S6: 高檔平台再突破
    # 整理一段時間(近15日高點-低點 < 10%); close突破15日高; 突破量大於均量
    h15 = get_max_high(15)
    l15 = get_min_low(15)
    # l15 > 0:近15日 low 全為 NULL 時 get_min_low 回哨兵 0,除零會炸整支命令(同 NULL open 失效類別)
    if h15 > 0 and l15 > 0 and (h15 - l15) / l15 < 0.12 and ma20 and prev_ma20 and ma20 > prev_ma20:
        if close >= h15 and vol_ratio > 1.2:
            c30 = _val(closes, 30)
            if c30 and l15 > c30 * 1.1: # Before platform there was a rise
                add_strategy(20, "S6_HIGH_BASE_BREAKOUT", "高檔平台再突破(高檔盤堅後再度創高)")

    # S7: MACD 零軸上金叉
    # DIF>0, Signal>0; DIF穿越Signal; 紅柱轉正; 站上20日線; 突破10日高; 量>1.5; RSI 50-75
    if macd and macd_signal and macd > 0 and macd_signal > 0:
        if x["macd_hist"] and x["macd_hist"] > 0 and x["prev_macd_hist"] and x["prev_macd_hist"] <= 0:
            if ma20 and close > ma20 and close >= get_max_high(10):
                if vol_ratio > 1.5 and rsi14 and 50 <= rsi14 <= 75:
                    add_strategy(20, "S7_MACD_ZERO_CROSS", "MACD零軸上金叉(多頭趨勢重新加速)")

    # S8: 跳空突破不回補
    # 開盤 > 昨高; 跳空 2%~6%; 當日低點未補缺口; 突破20日高; 量>2倍; 收盤近高
    prev_high = _val(highs, 1)
    if prev_high and open_ and open_ > prev_high * 1.02 and open_ < prev_high * 1.06:
        if low and low > prev_high and is_high20 and vol_ratio > 2.0:
            if high and close >= high * 0.98:
                add_strategy(20, "S8_GAP_BREAKOUT", "跳空突破不回補(缺口強勢表態)")

    # S9: 五日線強勢續攻
    # 近10日漲幅>10%; 近5日收盤在5日線上; 5日線向上; 量增; 突破3日高
    c10 = _val(closes, 10)
    if c10 and close > c10 * 1.1:
        prev_5_closes = closes[max(0, i-4):i+1]
        prev_5_ma5s = [_sma(closes, 5, j) for j in range(max(0, i-4), i+1)]
        if all(c is not None and m is not None and c > m for c, m in zip(prev_5_closes, prev_5_ma5s)):
            if x["ma5"] and prev_ma5 and x["ma5"] > prev_ma5 and vol_ratio > 1.0:
                if close >= get_max_high(3):
                    add_strategy(20, "S9_MA5_TREND", "五日線強勢續攻(沿五日線強勢攀升)")

    # S10: 底部 MACD 轉強
    # 近60日跌幅>20%; 負柱狀體縮短; 低檔金叉; 站上20日線; 量增; RSI底背離或>50
    h60 = x["box_high60"]
    if h60 and close < h60 * 0.8:
        if x["macd_hist"] and x["prev_macd_hist"] and x["prev_macd_hist"] < 0 and x["macd_hist"] > x["prev_macd_hist"]:
            if macd and macd < 0 and x["macd_hist"] > 0: # just crossed
                if ma20 and close > ma20 and vol_ratio > 1.0 and rsi14 and rsi14 > 50:
                    add_strategy(20, "S10_BOTTOM_MACD", "底部MACD轉強(跌深止跌轉強)")

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
        MAX_HISTORY_BARS = 400
        rows = compute_series(price_rows)
        if days:
            rows = rows[-days:]
        else:
            rows = rows[-MAX_HISTORY_BARS:]
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
