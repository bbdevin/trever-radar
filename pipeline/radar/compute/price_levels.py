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

邊界:有效 K 棒 < 20 根 → {"status": "insufficient"};零成交量的 K 棒不貢獻量;
as_of = 最後一根 K 棒的日期(停牌股會早於資料日)。
"""
from __future__ import annotations

from typing import Iterable, Sequence

VERSION = 1
MA_WINDOWS = (5, 10, 20, 60, 120, 240)
HL_WINDOWS = (20, 60, 120, 240)
VP_WINDOW = 120
MIN_BARS = 20
MAX_BARS = max(max(MA_WINDOWS), max(HL_WINDOWS), VP_WINDOW)
BIN_PCT = 0.01


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
    }


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
