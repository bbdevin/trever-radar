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

* 當日欄位(buy/sell/net)只有當天真的有列才給數字;沒有列 → ``null``(不寫 0)。null 的意思
  由個股摘要第 5 欄分辨(見 :data:`TODAY_HAS_ROWS` 等三個值):這檔今天有分點列 → 該分點
  「未進前 15 大」;這檔是匯入池裡的股票、今天沒有列、而且當日匯入**沒有**被記為完成 →
  「尚未匯入」;其餘(匯入已完成的確認空、或根本不在匯入池的 ETF 等)→「無分點資料」。
  覆蓋的分子分母與「完成」與否都照匯入端:池 = ``importer._branch_stock_pool``(普通股、
  不含 ETF),完成 = ``import_logs`` 有當日整池那一輪的 ``branch`` status=ok(見
  :func:`import_complete`)。
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


# 個股摘要第 5 欄
TODAY_PENDING = 0    # 匯入池的股票、今天沒有列、當日匯入未完成 → 尚未匯入(未知)
TODAY_HAS_ROWS = 1   # 今天有分點列 → 選的分點沒列 = 未進前 15 大
TODAY_NO_DATA = 2    # 今天沒有列,但不是待補:匯入已完成(確認空)或不在匯入池(ETF 等)

_RUN_PAIR_SECONDS = 10   # 同一輪的 branch 與 branch_coverage 兩列在同一個交易裡相繼寫入


def import_complete(conn, as_of: str, pool_size: int) -> bool | None:
    """as_of 的現股分點匯入有沒有被匯入端記為「完成」。

    匯入端每一輪收尾(``importer._finish_branch_import``)在同一個交易裡寫兩列 import_logs:
    ``dataset='branch'``(status ok／incomplete／error)與 ``dataset='branch_coverage'``
    (error 欄 ``expected=N ...``,N = 這一輪要的股票檔數)。status=ok 表示這一輪**每一個目標
    都有答案**(有列,或經別站確認的空;failed=0)且覆蓋率不低於警報線。所以「完成」=
    有一輪 status=ok、而且那一輪要的是整個池(expected ≥ 池大小;``--top 80``、``--ids``
    那種局部輪不算)。

    回傳 None = 當日沒有任何分點匯入紀錄(本機/測試庫、或 import_logs 已被 prune):不知道,
    呼叫端當作完成——沒有證據時不宣稱「待補」。
    """
    import re
    from datetime import datetime

    rows = conn.execute(text(
        "SELECT run_at, dataset, status, error FROM import_logs "
        "WHERE source = 'fubon' AND dataset IN ('branch', 'branch_coverage') AND date = :d"),
        {"d": as_of}).fetchall()
    if not rows:
        return None

    def ts(v):
        try:
            return datetime.fromisoformat(v)
        except (TypeError, ValueError):
            return None

    ok_runs = [ts(r[0]) for r in rows if r[1] == "branch" and r[2] == "ok"]
    ok_runs = [t for t in ok_runs if t is not None]
    for run_at, dataset, _status, error in rows:
        if dataset != "branch_coverage":
            continue
        m = re.search(r"expected=(\d+)", error or "")
        t = ts(run_at)
        if not m or t is None or int(m.group(1)) < pool_size:
            continue
        if any(abs((t - o).total_seconds()) <= _RUN_PAIR_SECONDS for o in ok_runs):
            return True
    return False


def make_collector(conn, d: str) -> "BranchWatchCollector":
    """export 用:找 as_of、視窗、匯入池與完成與否,建好收集器(迴圈前幾條小查詢)。"""
    from ..importer import _branch_stock_pool

    as_of = latest_stock_branch_date(conn, d)
    if as_of is None:
        return BranchWatchCollector(None, None)
    pool = set(_branch_stock_pool(conn, as_of))
    complete = import_complete(conn, as_of, len(pool))
    return BranchWatchCollector(as_of, window_start(conn, as_of), pool=pool,
                                complete=complete is not False)


def _closed(name: str) -> bool:
    return any(m in name for m in CLOSED_MARKS)


class BranchWatchCollector:
    """個股迴圈逐檔餵入,結束後 :meth:`write`。as_of 為 None(沒有分點資料)時什麼都不收。"""

    def __init__(self, as_of: str | None, window_from: str | None,
                 pool: set[str] | None = None, complete: bool = True):
        self.as_of = as_of
        self.window_from = window_from
        # 分點名稱 → [(sid, buy, sell, net, hold, entry, obs, sum, last)]
        self.rows: dict[str, list[tuple]] = {}
        self.names: set[str] = set()
        # sid → [name, close, chg_pct, avg_vol20_lots, TODAY_*]
        self.stocks: dict[str, list] = {}
        # 當日分點匯入覆蓋,照匯入端:pool = _branch_stock_pool(as_of);covered = 池裡今天已有
        # 分點列的檔數。17:40 那輪 ≥50% 就上線(2026-09-17 46% 被扣、09-16 86% 上線),22:00
        # 第二輪才補齊;complete = 匯入端記為完成(import_complete),那時沒列的是確認空。
        self.pool = pool or set()
        self.complete = complete
        self.covered = 0

    def add_stock(self, sid: str, name: str, rows: list[tuple], candles) -> None:
        """rows = ``_branch_history_rows`` 的輸出 (date, branch_name, buy, sell, net),date DESC。
        candles = 該檔 K 線列 (date, o, h, l, c, v, turnover, adj_factor),date ASC。"""
        as_of, wf = self.as_of, self.window_from
        if as_of is None:
            return
        imported = False
        for r in rows:
            if r[0] <= as_of:
                imported = r[0] == as_of
                break
        in_pool = sid in self.pool
        if in_pool and imported:
            self.covered += 1
        today_state = (TODAY_HAS_ROWS if imported
                       else TODAY_PENDING if in_pool and not self.complete
                       else TODAY_NO_DATA)
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
            # 第 5 欄 TODAY_*:當日三欄 null 是「未進前 15 大」(1)、「尚未匯入」(0)或「無分點資料」(2)。
            self.stocks[sid] = [name, *meta, today_state]

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
            # 當日分點匯入覆蓋(照匯入端的池):complete=false 時頁面說「已匯入 X / Y 檔,其餘待下一輪」
            "coverage": ({"covered": self.covered, "expected": len(self.pool),
                          "complete": bool(self.complete)} if self.as_of else None),
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
                # 代號 → [名稱, 收盤, 漲跌%(還原價), 近 20 日均量(張), TODAY_* (1 有列/0 尚未匯入/2 無分點資料)]
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
