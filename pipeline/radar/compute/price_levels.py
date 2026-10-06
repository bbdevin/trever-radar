"""個股「價格位置」事實(docs/45 §3 F1–F7):只給顯示用的價位、距離、比例、日期。

純函式,不讀 DB、不寫分數:export 把已讀進記憶體的 K 棒丟進來,結果放進
stocks/{id}.json 頂層 `price_levels`。**不得**併入 technical.reasons/risks
(derive_radar_state 用 technical.risks 判定 Armed/Extended)。

價格一律還原到今日基準:p_adj(t) = raw(t) × af(t) / af(today);成交量反向還原
v_adj(t) = v(t) × af(today) / af(t)(分割前後股數口徑一致,分割前後逐值相等)。

定義:
  F1 均線 MA5/10/20/60/120/240(還原收盤);不足 N 根 → null。前端:均線 ≥ 現價歸上方。
  F2 5/10/20 多頭(5>10>20)/空頭(5<10<20)排列;交錯或缺值 → null。
  F3 N 日最高/最低(N=20/60/120/240,含今日,用還原高低點);同價取最近一次的日期;
     不足 N 根 → null(不縮短視窗)。
  F4 收盤創 20 日新高/新低:與 T2 同口徑(前 20 根收盤至少 19 根有值,嚴格大於/小於)。
  F5 連 2 日量增價漲 / 量增價跌(T4 及其鏡像,嚴格遞增/遞減)。
  F6 近 120 根:每根量在 [low, high] 均勻分布(high == low 視為集中在該價),
     算落在現價之上/之下的比例;剛好等於現價的量兩邊都不算(另給 at)。不足 120 根 → null。
  F7 同視窗分價量,bin 寬 = 現價 1%,以現價為格線起點(沒有一格跨過現價);
     上方/下方各取量最大的一格,同量取離現價近者。
  F9 未回補缺口(P2,version 2):近 120 根裡「昨天以前」的跳空(今日的跳空由技術段「今日跳空」講),
     向上缺口 = 當根 low > 前根 high,之後各根的 low 往下吃掉多少就縮多少;向下缺口鏡像。
     剩餘寬度 ≥ 現價 0.5% 且整段在現價之下(向上缺口 → 下方支撐)/ 之上(向下缺口 → 上方壓力)才列;
     每側最多 2 個,離現價近者在前。與前端 levelFacts 舊 JSON 回退算法同一條定義。
  F11 收盤相對 20 日線的連續天數(P2,version 2):side = 今日收盤 ≥ MA20 → above,否則 below;
     n = 由今日往回數、關係相同的連續根數;capped = 可算 MA20 的根數全部同向(真實天數只多不少)。

邊界:有效 K 棒 < 20 根 → {"status": "insufficient"};零成交量的 K 棒不貢獻量;
as_of = 最後一根 K 棒的日期(停牌股會早於資料日)。
"""
from __future__ import annotations

from typing import Iterable, Sequence

VERSION = 2
MA_WINDOWS = (5, 10, 20, 60, 120, 240)
HL_WINDOWS = (20, 60, 120, 240)
VP_WINDOW = 120
MIN_BARS = 20
MAX_BARS = max(max(MA_WINDOWS), max(HL_WINDOWS), VP_WINDOW)
BIN_PCT = 0.01
GAP_WINDOW = 120
GAP_MIN_PCT = 0.005
GAP_PER_SIDE = 2


def _r(x: float | None, digits: int = 2) -> float | None:
    return None if x is None else round(x, digits)


def compute_price_levels(
    rows: Iterable[Sequence], as_of_limit: str | None = None,
) -> dict | None:
    """rows: (date, open, high, low, close, volume, adj_factor),日期遞增;close 為 None 的列略過。

    回傳 None = 完全沒有 K 棒(鍵照樣輸出為 null);其餘一律回 dict。
    """
    bars = []
    for r in rows:
        t, o, h, l, c, v, af = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
        if c is None or (as_of_limit is not None and t > as_of_limit):
            continue
        bars.append((t, h, l, c, v, af or 1.0))
    if not bars:
        return None
    bars = bars[-MAX_BARS:]
    as_of = bars[-1][0]
    if len(bars) < MIN_BARS:
        return {"version": VERSION, "status": "insufficient", "as_of": as_of, "bars": len(bars)}

    af_today = bars[-1][5]
    dates = [b[0] for b in bars]
    closes = [b[3] * b[5] / af_today for b in bars]
    # 高/低缺值時以收盤代替(只影響該根)。
    highs = [(b[1] if b[1] is not None else b[3]) * b[5] / af_today for b in bars]
    lows = [(b[2] if b[2] is not None else b[3]) * b[5] / af_today for b in bars]
    vols = [(b[4] or 0) * af_today / b[5] for b in bars]
    n = len(bars)
    close = closes[-1]

    ma = {}
    for w in MA_WINDOWS:
        ma[str(w)] = _r(sum(closes[-w:]) / w) if n >= w else None

    m5, m10, m20 = (sum(closes[-w:]) / w for w in (5, 10, 20))
    align = "bull" if m5 > m10 > m20 else "bear" if m5 < m10 < m20 else None

    def extreme(values: list[float], w: int, pick) -> dict | None:
        if n < w:
            return None
        best_i = n - w
        for i in range(n - w, n):
            # >= / <=:同價取最近一次。
            if pick(values[i], values[best_i]):
                best_i = i
        return {"p": _r(values[best_i]), "t": dates[best_i]}

    highs_out = {str(w): extreme(highs, w, lambda a, b: a >= b) for w in HL_WINDOWS}
    lows_out = {str(w): extreme(lows, w, lambda a, b: a <= b) for w in HL_WINDOWS}

    prior20 = closes[-21:-1]
    new_high_20 = len(prior20) >= 19 and close > max(prior20)
    new_low_20 = len(prior20) >= 19 and close < min(prior20)

    vp2 = None
    if n >= 3:
        c0, c1, c2 = closes[-3], closes[-2], closes[-1]
        v0, v1, v2 = vols[-3], vols[-2], vols[-1]
        if v2 > v1 > v0:
            vp2 = "up" if c2 > c1 > c0 else "down" if c2 < c1 < c0 else None

    profile, dense_above, dense_below = _volume_profile(highs, lows, vols, close, n)
    gaps_above, gaps_below = _gaps(highs, lows, dates, close, n)

    return {
        "version": VERSION,
        "status": "ok",
        "as_of": as_of,
        "bars": n,
        "close": _r(close),
        "ma": ma,
        "ma_align": align,
        "highs": highs_out,
        "lows": lows_out,
        "new_high_20": new_high_20,
        "new_low_20": new_low_20,
        "vol_price_2d": vp2,
        "vol_profile": profile,
        "dense_above": dense_above,
        "dense_below": dense_below,
        "gaps_above": gaps_above,
        "gaps_below": gaps_below,
        "ma20_streak": _ma20_streak(closes, n),
    }


def _gaps(highs, lows, dates, close, n):
    """F9:近 GAP_WINDOW 根、昨天以前的未回補缺口;回 (上方, 下方),各 ≤ GAP_PER_SIDE、近者在前。"""
    if n < 3 or close <= 0:
        return [], []
    i = n - 1
    above, below = [], []
    for j in range(max(1, n - GAP_WINDOW), i):
        if lows[j] > highs[j - 1]:
            lo = highs[j - 1]
            hi = lows[j]
            for k in range(j + 1, i + 1):
                hi = min(hi, lows[k])
            if hi - lo >= close * GAP_MIN_PCT and hi < close:
                below.append({"lo": _r(lo), "hi": _r(hi), "t": dates[j]})
        elif highs[j] < lows[j - 1]:
            lo = highs[j]
            hi = lows[j - 1]
            for k in range(j + 1, i + 1):
                lo = max(lo, highs[k])
            if hi - lo >= close * GAP_MIN_PCT and lo > close:
                above.append({"lo": _r(lo), "hi": _r(hi), "t": dates[j]})
    # 近者在前(上方看下緣、下方看上緣);同距離依日期舊→新(sort 穩定,掃描順序即日期序)
    above.sort(key=lambda g: g["lo"] - close)
    below.sort(key=lambda g: close - g["hi"])
    return above[:GAP_PER_SIDE], below[:GAP_PER_SIDE]


def _ma20_streak(closes, n):
    """F11:收盤 ≥/< MA20 的連續根數(含今日)。可算 MA20 的根數 = n - 19。"""
    if n < 20:
        return None
    ma20 = [sum(closes[j - 19:j + 1]) / 20 for j in range(19, n)]
    rel = [c >= m for c, m in zip(closes[19:], ma20)]
    side = rel[-1]
    k = 0
    for r in reversed(rel):
        if r != side:
            break
        k += 1
    return {"n": k, "side": "above" if side else "below", "capped": k == len(rel)}


def _volume_profile(highs, lows, vols, close, n):
    if n < VP_WINDOW or close <= 0:
        return None, None, None
    w = close * BIN_PCT
    above = below = at = total = 0.0
    # bin k ≥ 0:[close + k·w, close + (k+1)·w);k < 0:[close + k·w, close + (k+1)·w)。
    bins: dict[int, float] = {}
    for i in range(n - VP_WINDOW, n):
        v = vols[i]
        if v <= 0:
            continue
        lo, hi = lows[i], highs[i]
        if hi < lo:
            lo, hi = hi, lo
        total += v
        if hi == lo:
            if lo > close:
                above += v
            elif lo < close:
                below += v
            else:
                at += v
                continue
            k = int((lo - close) // w)
            bins[k] = bins.get(k, 0.0) + v
            continue
        span = hi - lo
        above += v * max(0.0, hi - max(lo, close)) / span
        below += v * max(0.0, min(hi, close) - lo) / span
        k_lo = int((lo - close) // w)
        k_hi = int((hi - close) // w)
        for k in range(k_lo, k_hi + 1):
            b_lo = close + k * w
            overlap = min(hi, b_lo + w) - max(lo, b_lo)
            if overlap > 0:
                bins[k] = bins.get(k, 0.0) + v * overlap / span
    if total <= 0:
        return None, None, None
    profile = {
        "window": VP_WINDOW,
        "above": _r(above / total, 4),
        "below": _r(below / total, 4),
        "at": _r(at / total, 4),
    }

    def densest(keys):
        best = None
        for k in keys:  # 由近到遠走,嚴格大於才換 → 同量取近者
            if best is None or bins[k] > bins[best]:
                best = k
        if best is None or bins[best] <= 0:
            return None
        return {
            "lo": _r(close + best * w),
            "hi": _r(close + (best + 1) * w),
            "share": _r(bins[best] / total, 4),
        }

    up_keys = sorted(k for k in bins if k >= 0)
    down_keys = sorted((k for k in bins if k < 0), reverse=True)
    return profile, densest(up_keys), densest(down_keys)
