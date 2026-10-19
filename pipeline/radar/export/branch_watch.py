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

權證(2026-10-20,docs/52 §8):分點今天在某檔標的的認購／認售權證淨額。**不另掃**:
export 的權證分點那段(``_WarrantWindowScan``)本來就產出「每 (標的, 分點) 的逐日認購／
認售金額」與 docs/51 的持有估算摘要,:meth:`BranchWatchCollector.add_warrants` 直接從裡面
取一天。權證分點日可能和現股分點日不同(兩條管線分開匯入),所以另帶 ``warrant`` 資料日;
權證比現股舊時那天的權證列照樣列出、但標成舊的,前端不算進今天的同買／同賣。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import text

from ..branch_names import CLOSED_MARKS
from ..branch_source import COVER_INDEX, has_date_cover
from ..compute.warrant_position_est import SUMMARY_FIELDS

FILE_VERSION = 1
WINDOW_TRADING_DAYS = 60     # 估計仍持有的視窗(交易日);理由見 docs/52 §3
SHARDS = 64
HOLD_MIN_LOTS = 100          # 當日沒出現的列:估計仍持有 ≥ 這個張數就輸出
HOLD_FLOOR_LOTS = 20         # 或 ≥ 該股 20 日均量且至少這麼多張(小型股的相對大部位;與前端「持有量大」同規則)
HOLD_TOP_PER_BRANCH = 60     # 當日沒出現的列:每個分點最多輸出幾檔(依估計仍持有由大到小)
AVG_VOL_DAYS = 20
# 權證:當天認購(或認售)淨額 |金額| ≥ 這個數才列出、才算參與。與權證分點明細門檻
# (json_export.WARRANT_BRANCH_DETAIL_MIN_AMOUNT)同值——低於它的配對,上游掃描本來就不一定留。
WARRANT_MIN_AMOUNT = 1_000_000
# 夜間權證分點池的成交金額門檻(vps/scripts/daily-branches.sh `--warrant-turnover-min 1000000`):
# 當天成交 < 這個數的權證不抓分點。
NIGHTLY_WARRANT_TURNOVER_MIN = 1_000_000


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

    from zoneinfo import ZoneInfo

    def ts(v):
        # 沒帶時區的列當台北時間:混到一列 naive 就讓 aware/naive 相減 TypeError、整個 export 掛掉。
        try:
            t = datetime.fromisoformat(v)
        except (TypeError, ValueError):
            return None
        return t if t.tzinfo else t.replace(tzinfo=ZoneInfo("Asia/Taipei"))

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


def warrant_pool_status(conn, day: str) -> str | None:
    """``day`` 權證分點那一段的匯入狀態(``import_logs`` dataset='branch_warrant_pool',最後一輪):
    'ok' / 'incomplete' / 'error';沒有紀錄 → None。"""
    row = conn.execute(text(
        "SELECT status FROM import_logs WHERE source = 'fubon' "
        "AND dataset = 'branch_warrant_pool' AND date = :d ORDER BY run_at DESC LIMIT 1"),
        {"d": day}).fetchone()
    return row[0] if row else None


def warrant_pool_underlyings(conn, day: str) -> set[str]:
    """``day`` 夜間權證池(importer ``import_branch_trades`` 的 warrant_turnover_min 那條)涵蓋的標的:
    當天成交金額 ≥ NIGHTLY_WARRANT_TURNOVER_MIN 的上市／上櫃認購、認售。不在裡面的標的,那天沒有
    權證分點可看(畫面「權證:未收集」)。條件與匯入端那條 SQL 相同。"""
    return {r[0] for r in conn.execute(text(
        "SELECT DISTINCT w.stock_id FROM warrant_daily d "
        "JOIN warrants w ON w.id = d.warrant_id "
        "JOIN stocks s ON s.id = w.stock_id AND s.type = 'stock' AND s.is_active = 1 "
        "WHERE d.date = :d AND d.turnover >= :m "
        "AND w.market IN ('twse', 'tpex') AND w.kind IN ('call', 'put')"),
        {"d": day, "m": NIGHTLY_WARRANT_TURNOVER_MIN})}


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
        # 分點名稱 → [(sid, buy, sell, net, hold, entry, obs, sum, last, avg_cost)]
        self.rows: dict[str, list[tuple]] = {}
        self.names: set[str] = set()
        # sid → [name, close, chg_pct, avg_vol20_lots, TODAY_*]
        self.stocks: dict[str, list] = {}
        # 每一檔餵進來的股票的摘要(權證列的標的可能沒有任何現股列入選,要從這裡補 stocks)
        self._meta_all: dict[str, list] = {}
        # 當日分點匯入覆蓋,照匯入端:pool = _branch_stock_pool(as_of);covered = 池裡今天已有
        # 分點列的檔數。17:40 那輪 ≥50% 就上線(2026-09-17 46% 被扣、09-16 86% 上線),22:00
        # 第二輪才補齊;complete = 匯入端記為完成(import_complete),那時沒列的是確認空。
        self.pool = pool or set()
        self.complete = complete
        self.covered = 0
        # 權證(add_warrants):None = 沒有權證分點資料(或沒呼叫);否則見 payloads 的 index["warrant"]
        self.warrant: dict | None = None
        # (分點, 標的) → [認購淨額|None, 認售淨額|None](當天、|金額| ≥ WARRANT_MIN_AMOUNT 才有值)
        self.w_today: dict[tuple[str, str], list] = {}
        # (分點, 標的) → [認購仍持有成本, 認購換算現股均價, 認售仍持有成本, 認售換算現股均價](docs/51)
        self.w_held: dict[tuple[str, str], list] = {}
        self.warrant_secs = 0.0
        # 那一天夜間權證池裡有權證的標的(None = 不知道:沒給 conn);不在裡面 → 前端「權證:未收集」
        self.w_pooled: set[str] | None = None

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
        meta = _stock_meta(candles, as_of)
        self._meta_all[sid] = [name, *meta, today_state]
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
        avg_vol = meta[2]
        px = _window_prices(candles, wf, as_of)
        emitted = False
        for bname, seq in seqs.items():
            if _closed(bname):
                continue
            self.names.add(bname)
            pos = 0
            entry = None
            total = 0
            # 平均成本(pnl-avgcost-v1,docs/42 同一套):買超日以當天收盤(還原到 as_of 的尺度)
            # 當成交價加權;賣超依均價扣張數不改均價;歸 0 就重來。這段持有裡任一買超日沒有收盤
            # → 均價未知(None),不拿部分成本充數。
            avg = 0.0
            known = True
            for dt, _b, _s, net in seq:
                total += net
                nxt = pos + net
                if nxt <= 0:
                    pos, entry, avg, known = 0, None, 0.0, True
                else:
                    if pos == 0:
                        entry = dt
                    if net > 0:
                        p = px.get(dt)
                        if p is None:
                            known = False
                        elif known:
                            avg = (pos * avg + net * p) / nxt
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
                round(avg, 2) if pos > 0 and known else None,
            ))
            emitted = True
        if emitted:
            # 第 5 欄 TODAY_*:當日三欄 null 是「未進前 15 大」(1)、「尚未匯入」(0)或「無分點資料」(2)。
            self.stocks[sid] = self._meta_all[sid]

    def add_warrants(self, data_date: str | None, daily: dict, summaries=(), conn=None) -> None:
        """權證分點那段掃完後呼叫(``json_export._export_warrant_branches``)。

        daily = ``_WarrantWindowScan.daily``:{(標的, 分點): [[日, 認購淨額, 認售淨額], …]}(日期遞增,
        只有任一區間 |金額| ≥ 100 萬的配對;牛熊證不在裡面)。summaries = ``PositionStream.summaries``
        (分點, 標的, kind, lots, cost, …)(docs/51,仍持有成本 ≥ 500 萬才有)。

        取哪一天:權證分點日 ≥ 現股分點日 → 取現股那一天(``counted``:算進今天);權證分點日比較舊
        (權證晚一步匯入)→ 取權證最新那天,標成舊的(``counted`` = False),前端只列不算。
        """
        import time
        t0 = time.perf_counter()
        as_of = self.as_of
        if as_of is None or data_date is None:
            return
        day = as_of if data_date >= as_of else data_date
        # 權證那一段的匯入完整嗎(docs/47 §8.10 的 branch_warrant_pool,最後一輪的狀態):
        # 沒有紀錄(本機/測試庫、兩段式之前的日子)→ 當作完整,沒有證據時不宣稱「未完整」。
        status = None
        if conn is not None:
            status = warrant_pool_status(conn, day)
            self.w_pooled = warrant_pool_underlyings(conn, day)
        complete = status in (None, "ok")
        self.warrant = {"data_date": data_date, "day": day, "counted": day == as_of and complete,
                        "complete": complete, "min_amount": WARRANT_MIN_AMOUNT,
                        "pool_turnover_min": NIGHTLY_WARRANT_TURNOVER_MIN}
        lo = WARRANT_MIN_AMOUNT
        for (u, branch), series in daily.items():
            if _closed(branch):
                continue
            hit = None
            for s in reversed(series):
                if s[0] <= day:
                    if s[0] == day:
                        hit = s
                    break
            if hit is None:
                continue
            c = hit[1] if abs(hit[1]) >= lo else None
            p = hit[2] if abs(hit[2]) >= lo else None
            if c is None and p is None:
                continue
            self.w_today[(branch, u)] = [c, p]
        fields = SUMMARY_FIELDS
        i_cost, i_avg = 3 + fields.index("cost"), 3 + fields.index("avg_under")
        for s in summaries:
            branch, sid, kind = s[0], s[1], s[2]
            if _closed(branch) or kind not in ("call", "put"):
                continue
            slot = self.w_held.setdefault((branch, sid), [None, None, None, None])
            k = 0 if kind == "call" else 2
            slot[k] = s[i_cost]
            slot[k + 1] = s[i_avg]
        self.warrant_secs += time.perf_counter() - t0

    def _warrant_rows(self) -> dict[str, list[list]]:
        """分點 → [[標的, 認購今天, 認售今天, 認購仍持有成本, 認購換算均價, 認售仍持有成本, 認售換算均價]]。
        收:今天有權證進出的配對;以及這個分點在這檔已有現股列(或今天有權證進出)的持有估算。"""
        out: dict[str, dict[str, list]] = {}
        for (branch, u), (c, p) in self.w_today.items():
            out.setdefault(branch, {})[u] = [u, c, p, None, None, None, None]
        stock_sids = {b: {r[0] for r in rows} for b, rows in self.rows.items()}
        for (branch, u), held in self.w_held.items():
            got = out.get(branch, {}).get(u)
            if got is None:
                if u not in stock_sids.get(branch, ()):
                    continue
                got = out.setdefault(branch, {})[u] = [u, None, None, None, None, None, None]
            got[3:7] = held
        return {b: [v[k] for k in sorted(v)] for b, v in out.items()}

    def _stock_payload(self, sid: str) -> list:
        m = self._meta_all.get(sid) or [sid, None, None, None, TODAY_NO_DATA]
        if self.w_pooled is None:
            return m
        return [*m, 1 if sid in self.w_pooled else 0]

    def payloads(self) -> tuple[dict, list[dict]]:
        """(index, [shard 0..SHARDS-1]),全部已排序、可逐位元重現。"""
        shards: list[dict] = [{} for _ in range(SHARDS)]
        wshards: list[dict] = [{} for _ in range(SHARDS)]
        wrows = self._warrant_rows() if self.as_of else {}
        names = self.names | set(wrows)
        index_rows = []
        for bname in sorted(names):
            rows = self.rows.get(bname, [])
            today = sorted((r for r in rows if r[3] is not None), key=lambda r: r[0])
            held_all = sorted((r for r in rows if r[3] is None), key=lambda r: (-r[4], r[0]))
            held = sorted(held_all[:HOLD_TOP_PER_BRANCH], key=lambda r: r[0])
            s = shard_of(bname)
            if today or held:
                shards[s][bname] = [list(r) for r in sorted(today + held, key=lambda r: r[0])]
            if bname in wrows:
                wshards[s][bname] = wrows[bname]
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
            # 權證:{data_date 權證分點最新日, day 取的那一天, counted 是否算進今天, min_amount}
            # 或 null(沒有權證分點資料)。
            "warrant": self.warrant,
            # [名稱, 分片, 當日買超檔數, 當日賣超檔數, 當日沒出現但估計仍持有(已輸出)檔數, 同上(截斷前)]
            "branches": index_rows,
        }
        out = []
        for i, branches in enumerate(shards):
            warrants = wshards[i]
            used = sorted({r[0] for rows in branches.values() for r in rows}
                          | {r[0] for rows in warrants.values() for r in rows})
            out.append({
                **head,
                "shard": i,
                # 每列 [代號, 當日買張, 當日賣張, 當日淨張, 估計仍持有, 進場日, 視窗內出現天數,
                #       視窗內淨張合計, 最後出現日, 均價(估)|null];當日三欄 null = 當日不在前 15 大(未知,不是 0)。
                "branches": {b: branches[b] for b in sorted(branches)},
                # 每列 [標的, 認購淨額, 認售淨額, 認購仍持有成本, 認購換算現股均價, 認售仍持有成本,
                #       認售換算現股均價](元;null = 沒有/未達門檻)。哪一天見 index.warrant。
                "warrants": {b: warrants[b] for b in sorted(warrants)},
                # 代號 → [名稱, 收盤, 漲跌%(還原價), 近 20 日均量(張), TODAY_* (1 有列/0 尚未匯入/2 無分點資料)]
                # 有權證資料(index.warrant)時多第 6 欄:1 = 這檔當天有權證進夜間權證池;0 = 沒有(權證:未收集)
                "stocks": {sid: self._stock_payload(sid) for sid in used},
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
            "warrant_rows": sum(len(r) for s in shards for r in s["warrants"].values()),
            "shard_bytes": sizes,
            "index_bytes": len(body.encode("utf-8")),
        }


def _window_prices(candles, wf: str, as_of: str) -> dict[str, float]:
    """視窗內每天的收盤,還原到 as_of 那根的尺度(close × adj / adj_as_of;docs/42 pnl-avgcost-v1
    同一個換算),所以均價可以直接跟今天的收盤比。沒有收盤的日子不給(均價就算未知)。"""
    i = len(candles) - 1
    while i >= 0 and candles[i][0] > as_of:
        i -= 1
    if i < 0:
        return {}
    af_last = candles[i][7] or 1.0
    out: dict[str, float] = {}
    while i >= 0 and candles[i][0] >= wf:
        c = candles[i]
        if c[4] is not None:
            out[c[0]] = c[4] * (c[7] or 1.0) / af_last
        i -= 1
    return out


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
