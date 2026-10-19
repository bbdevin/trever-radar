"""自選「特定分點」資料(docs/52):任意分點的當日進出＋近 60 交易日估計仍持有。

使用者可以挑任何分點,所以要讓「任一分點的當日列」便宜可抓。這裡**不另掃**
``branch_trades_raw``:export 的個股迴圈本來就逐檔讀了 2 年分點列
(``_branch_history_rows``),每檔讀完就交給 :meth:`BranchWatchCollector.add_stock`,
只在記憶體裡留「當日有出現」或「估計仍持有達門檻」的 (分點, 個股) 摘要。

輸出 ``branches/watch/``:

* ``index.json`` — 近 60 交易日出現過的分點名稱 → 分片編號(前端搜尋清單也用它)。
* ``s00.json`` … ``s63.json`` — 64 個分片,每片是若干分點的列與用到的個股摘要。
  前端只抓使用者選的那幾個分點所在的分片(通常 3 片)。

資料誠實(與 docs/42、docs/51 同一套):分點列只有「當天在該股前 15 大買超或前 15 大
賣超」才存在。沒有列的日子是**未知**,不是 0。所以:

* 當日欄位(buy/sell/net)只有當天真的有列才給數字;沒有列 → ``null``(不寫 0)。null 有兩種
  意思,由個股摘要第 5 欄分辨:這檔 as_of 已匯入任何分點列(1)→ 該分點「未進前 15 大」;
  這檔還沒匯入(0,17:40 那輪可能只匯一半)→「尚未匯入」。index 的 ``coverage`` 給頁面
  說「今日分點已匯入 X / Y 檔」。
* 同名不同 branch_id(不同來源頁)同一天加總,與 ``branches/track`` 同口徑。進場日只看得到
  視窗內:60 交易日以前就持有的部位,進場日最早只會是視窗起點那段。
* 估計仍持有 = 視窗起點從 0 開始的累計淨買超,賣超超過已知買超時歸 0(更早的部位未知,
  不往負的推);進場日 = 這一段持有從 0 轉正的那一天。視窗內沒被觀察到的賣超不會被扣,
  所以這是「估」,畫面一律標「估」。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from ..branch_names import CLOSED_MARKS
from ..branch_source import COVER_INDEX, has_date_cover

FILE_VERSION = 1
WINDOW_TRADING_DAYS = 60     # 估計仍持有的視窗(交易日);理由見 docs/52 §3
SHARDS = 64
HOLD_MIN_LOTS = 100          # 當日沒出現的列:估計仍持有 ≥ 這個張數就輸出
HOLD_FLOOR_LOTS = 20         # 或 ≥ 該股 20 日均量且至少這麼多張(小型股的相對大部位;與前端「持有量大」同規則)
HOLD_TOP_PER_BRANCH = 60     # 當日沒出現的列:每個分點最多輸出幾檔(依估計仍持有由大到小)
AVG_VOL_DAYS = 20


def shard_of(branch_name: str) -> int:
    return int(hashlib.sha1(branch_name.encode("utf-8")).hexdigest()[:8], 16) % SHARDS


def latest_stock_branch_date(conn, d: str) -> str | None:
    """不晚於 d 的最新「現股/ETF」分點資料日(6 碼權證列不算:權證分點另一條管線,
    可能比現股早一步進來,不能拿它當今天)。依日期覆蓋索引倒著找,碰到第一列現股就停。"""
    hint = f" INDEXED BY {COVER_INDEX}" if has_date_cover(conn) else ""
    return conn.execute(text(
        f"SELECT date FROM branch_trades_raw{hint} "
        "WHERE date <= :d AND LENGTH(stock_id) < 6 ORDER BY date DESC LIMIT 1"),
        {"d": d}).scalar()


def window_start(conn, as_of: str) -> str:
    """as_of 往回第 WINDOW_TRADING_DAYS 個交易日(含 as_of;交易日取自 daily_prices)。"""
    start = conn.execute(text(
        "SELECT MIN(date) FROM (SELECT DISTINCT date FROM daily_prices "
        "WHERE date <= :d ORDER BY date DESC LIMIT :n)"),
        {"d": as_of, "n": WINDOW_TRADING_DAYS}).scalar()
    return start or as_of


def holding_worth_listing(hold: int, avg_vol: int | None) -> bool:
    """當日沒出現的 (分點, 股) 要不要輸出:≥ HOLD_MIN_LOTS,或 ≥ 20 日均量(且 ≥ HOLD_FLOOR_LOTS)。"""
    if hold >= HOLD_MIN_LOTS:
        return True
    return bool(avg_vol) and hold >= HOLD_FLOOR_LOTS and hold >= avg_vol


def _has_candle(candles, as_of: str) -> bool:
    for c in reversed(candles):
        if c[0] == as_of:
            return True
        if c[0] < as_of:
            return False
    return False


def _closed(name: str) -> bool:
    return any(m in name for m in CLOSED_MARKS)


class BranchWatchCollector:
    """個股迴圈逐檔餵入,結束後 :meth:`write`。as_of 為 None(沒有分點資料)時什麼都不收。"""

    def __init__(self, as_of: str | None, window_from: str | None):
        self.as_of = as_of
        self.window_from = window_from
        # 分點名稱 → [(sid, buy, sell, net, hold, entry, obs, sum, last)]
        self.rows: dict[str, list[tuple]] = {}
        self.names: set[str] = set()
        # sid → [name, close, chg_pct, avg_vol20_lots, today_imported(1/0)]
        self.stocks: dict[str, list] = {}
        # 當日分點匯入覆蓋:expected = as_of 有報價的檔數(與 importer._branch_date_fit 的
        # 分母同一個宇宙),covered = 其中 as_of 已有任何分點列的檔數。17:40 那輪可能只匯了一半
        # (2026-09-17 46%),22:00 第二輪才補齊——沒匯到的股票「今天」是未知,不是沒進前 15 大。
        self.expected = 0
        self.covered = 0

    def add_stock(self, sid: str, name: str, rows: list[tuple], candles) -> None:
        """rows = ``_branch_history_rows`` 的輸出 (date, branch_name, buy, sell, net),date DESC。
        candles = 該檔 K 線列 (date, o, h, l, c, v, turnover, adj_factor),date ASC。"""
        as_of, wf = self.as_of, self.window_from
        if as_of is None:
            return
        priced = _has_candle(candles, as_of)
        imported = False
        for r in rows:
            if r[0] <= as_of:
                imported = r[0] == as_of
                break
        if priced:
            self.expected += 1
            if imported:
                self.covered += 1
        if not rows:
            return
        # rows 依日期遞減:先跳過 as_of 之後的列(分點比報價新時才會有),再取到視窗下緣為止。
        seqs: dict[str, list[list]] = {}
        window = []
        for r in rows:
            dt = r[0]
            if dt > as_of:
                continue
            if dt < wf:
                break
            window.append(r)
        if not window:
            return
        # 由舊到新;同名不同 branch_id(不同來源頁)同一天合併。
        for dt, bname, buy, sell, net in reversed(window):
            seq = seqs.get(bname)
            if seq is None:
                seqs[bname] = [[dt, buy or 0, sell or 0, net or 0]]
            else:
                last = seq[-1]
                if last[0] == dt:
                    last[1] += buy or 0
                    last[2] += sell or 0
                    last[3] += net or 0
                else:
                    seq.append([dt, buy or 0, sell or 0, net or 0])
        meta = _stock_meta(candles, as_of)
        avg_vol = meta[2]
        emitted = False
        for bname, seq in seqs.items():
            if _closed(bname):
                continue
            self.names.add(bname)
            pos = 0
            entry = None
            total = 0
            for dt, _b, _s, net in seq:
                total += net
                nxt = pos + net
                if nxt <= 0:
                    pos, entry = 0, None
                else:
                    if pos == 0:
                        entry = dt
                    pos = nxt
            last = seq[-1]
            today = last[0] == as_of
            if not today and not holding_worth_listing(pos, avg_vol):
                continue
            self.rows.setdefault(bname, []).append((
                sid,
                last[1] if today else None,
                last[2] if today else None,
                last[3] if today else None,
                pos, entry, len(seq), total, last[0],
            ))
            emitted = True
        if emitted:
            # 第 5 欄:這檔 as_of 已有任何分點列(1)或還沒匯入(0)。0 時當日三欄 null 的意思是
            # 「尚未匯入」,不是「未進前 15 大」。
            self.stocks[sid] = [name, *meta, 1 if imported else 0]

    def payloads(self) -> tuple[dict, list[dict]]:
        """(index, [shard 0..SHARDS-1]),全部已排序、可逐位元重現。"""
        shards: list[dict] = [{} for _ in range(SHARDS)]
        index_rows = []
        for bname in sorted(self.names):
            rows = self.rows.get(bname, [])
            today = sorted((r for r in rows if r[3] is not None), key=lambda r: r[0])
            held_all = sorted((r for r in rows if r[3] is None), key=lambda r: (-r[4], r[0]))
            held = sorted(held_all[:HOLD_TOP_PER_BRANCH], key=lambda r: r[0])
            s = shard_of(bname)
            if today or held:
                shards[s][bname] = [list(r) for r in sorted(today + held, key=lambda r: r[0])]
            n_buy = sum(1 for r in today if r[3] > 0)
            n_sell = sum(1 for r in today if r[3] < 0)
            index_rows.append([bname, s, n_buy, n_sell, len(held), len(held_all)])
        head = {
            "version": FILE_VERSION,
            "as_of": self.as_of,
            "window_days": WINDOW_TRADING_DAYS,
            "window_from": self.window_from if self.as_of else None,
        }
        index = {
            **head,
            "shards": SHARDS,
            "hold_min": HOLD_MIN_LOTS,
            "hold_floor": HOLD_FLOOR_LOTS,
            "hold_top": HOLD_TOP_PER_BRANCH,
            # 當日分點匯入覆蓋:as_of 有報價的檔數裡,已有任何分點列的檔數
            "coverage": {"covered": self.covered, "expected": self.expected},
            # [名稱, 分片, 當日買超檔數, 當日賣超檔數, 當日沒出現但估計仍持有(已輸出)檔數, 同上(截斷前)]
            "branches": index_rows,
        }
        out = []
        for i, branches in enumerate(shards):
            used = sorted({r[0] for rows in branches.values() for r in rows})
            out.append({
                **head,
                "shard": i,
                # 每列 [代號, 當日買張, 當日賣張, 當日淨張, 估計仍持有, 進場日, 視窗內出現天數,
                #       視窗內淨張合計, 最後出現日];當日三欄 null = 當日不在前 15 大(未知,不是 0)。
                "branches": {b: branches[b] for b in sorted(branches)},
                # 代號 → [名稱, 收盤, 漲跌%(還原價), 近 20 日均量(張), 當日分點已匯入 1/0]
                "stocks": {sid: self.stocks[sid] for sid in used},
            })
        return index, out

    def write(self, out: Path) -> dict:
        watch_dir = out / "branches" / "watch"
        watch_dir.mkdir(parents=True, exist_ok=True)
        for stale in watch_dir.glob("*.json"):
            stale.unlink()
        index, shards = self.payloads()
        sizes = 0
        for i, payload in enumerate(shards):
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            (watch_dir / f"s{i:02d}.json").write_text(body, encoding="utf-8")
            sizes += len(body.encode("utf-8"))
        body = json.dumps(index, ensure_ascii=False, separators=(",", ":"))
        (watch_dir / "index.json").write_text(body, encoding="utf-8")
        return {
            "branches": len(index["branches"]),
            "rows": sum(len(r) for s in shards for r in s["branches"].values()),
            "shard_bytes": sizes,
            "index_bytes": len(body.encode("utf-8")),
        }


def _stock_meta(candles, as_of: str) -> list:
    """[收盤, 漲跌%, 近 20 日均量張];取不晚於 as_of 的最後一根。漲跌用還原價(除權息日不算跌)。"""
    i = len(candles) - 1
    while i >= 0 and candles[i][0] > as_of:
        i -= 1
    if i < 0:
        return [None, None, None]
    c = candles[i]
    close = c[4]
    chg = None
    if i > 0 and close is not None:
        p = candles[i - 1]
        prev_adj = (p[4] or 0) * (p[7] or 1.0)
        if prev_adj:
            chg = round(((close * (c[7] or 1.0)) - prev_adj) / prev_adj * 100, 2)
    vols = [(x[5] or 0) // 1000 for x in candles[max(0, i - AVG_VOL_DAYS + 1): i + 1]]
    avg = round(sum(vols) / len(vols)) if vols else None
    return [close, chg, avg]
