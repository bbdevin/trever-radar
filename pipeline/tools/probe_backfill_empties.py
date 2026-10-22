"""唯讀:權證分點回補記下的 empty 到底是真的空,還是鏡像回了錯誤／限流／下市頁。

2026-10-22 事故(吞吐塌陷 1.24 列/秒,08-06..08-12 那一塊 fetched=7964 empty=5770)的調查工具。
**不寫 DB、不寫 state 檔**;DB 一律以 ``mode=ro`` 開啟。兩個子命令:

``report``(不連網)
    讀 ``<stem>-YYYY-MM-DD-<market>.json`` 各日 state 檔,逐日列 ok/empty/error/pending,
    empty 再拆上市/上櫃、今天是否已過到期日、哪一站回的(2026-10-22 之後的訊息才帶 host)。

``probe``(連網,禮貌:每站兩次請求至少間隔 ``--per-host-interval`` 秒,預設 5)
    從 state 檔抽 ``--empties`` 個 empty(預設 30,依 上市/上櫃 × 已到期/未到期 分層)與
    ``--controls`` 個有列的對照(預設 10;一半挑**今天已到期**的權證——它們當初抓得到列,
    現在若抓不到,就證明鏡像不再供已下市代號的歷史頁),每一對到 ``--mirrors`` 個不同
    鏡像站(預設 3)各抓一次,印 HTTP 狀態、大小、<title>、解析出的列數、錯誤頁關鍵字。

用法(VPS,在 repo 根;回補先暫停——暫停檔 /tmp/radar-warrant-backfill.pause 在就好):

    cd ~/trever-radar
    docker run --rm -v "$PWD/pipeline":/app/pipeline:ro -v "$PWD/data":/app/data \\
      -w /app/pipeline radar-pipeline \\
      python tools/probe_backfill_empties.py report --from 2026-08-06 --to 2026-08-12

    docker run --rm -v "$PWD/pipeline":/app/pipeline:ro -v "$PWD/data":/app/data \\
      -v /tmp/probe-dump:/dump -w /app/pipeline radar-pipeline \\
      python tools/probe_backfill_empties.py probe --from 2026-08-06 --to 2026-08-12 --dump-dir /dump

``/app/data`` 掛成可寫只是因為 SQLite 的 WAL 模式要 -shm;程式本身以 ``mode=ro`` 開 DB。
``--dump-dir`` 可省略;給了就把每個回應的原始 HTML 存在那裡(檔名 sid_date_host.html)。
請求數 = (empties + controls) × mirrors,預設 120 次,約 3–6 分鐘(一次一個請求、每站 ≥5 秒)。
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

from radar import config  # noqa: E402
from radar.providers import fubon  # noqa: E402

DEFAULT_STATE_BASE = "data/warrant-branch-backfill.json"
_HOST_RE = re.compile(r"@(https?://[^\s|]+)")
_BYTES_RE = re.compile(r"bytes=(\d+)")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
# 錯誤／限流／查無資料頁可能出現的字。命中只是提示,判斷以「別站有沒有列」為準。
SUSPECT_WORDS = ("查無", "無資料", "沒有資料", "錯誤", "頻繁", "稍後", "忙碌", "維護", "驗證碼",
                 "error", "Error", "ERROR", "Too Many", "denied", "Denied", "Forbidden",
                 "blocked", "captcha", "Captcha", "Service Unavailable", "Request Rejected")


def today_iso() -> str:
    return datetime.now(ZoneInfo(config.TZ)).date().isoformat()


def state_files(base: str, market: str, d_from: str | None, d_to: str | None) -> list[tuple[str, Path]]:
    b = Path(base)
    out = []
    pat = re.compile(re.escape(b.stem) + r"-(\d{4}-\d{2}-\d{2})-" + re.escape(market) + re.escape(b.suffix or ".json") + "$")
    for p in sorted(b.parent.glob(f"{b.stem}-*-{market}{b.suffix or '.json'}")):
        m = pat.match(p.name)
        if not m:
            continue
        d = m.group(1)
        if (d_from and d < d_from) or (d_to and d > d_to):
            continue
        out.append((d, p))
    return out


def open_ro(db: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=30)


def warrant_info(conn: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    return {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, market, maturity_date FROM warrants")}


def host_of(msg: str) -> str:
    m = _HOST_RE.search(msg or "")
    return urlparse(m.group(1)).netloc if m else "unknown(pre-2026-10-22 msg)"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"!! cannot read {path}: {e}")
        return {}


def cmd_report(args) -> None:
    files = state_files(args.state_base, args.market, args.date_from, args.date_to)
    if not files:
        print(f"no state files matching {args.state_base} market={args.market} in range "
              f"(cwd={Path.cwd()}); container path is /app/pipeline/data/, host path $REPO/pipeline/data/")
        return
    conn = open_ro(args.db)
    info = warrant_info(conn)
    today = today_iso()
    tot = collections.Counter()
    hosts_all = collections.Counter()
    print(f"today={today} db={args.db} (read-only)")
    print(f"{'date':10} {'targets':>7} {'ok':>6} {'empty':>6} {'error':>5} {'pend':>5} | "
          f"{'e_twse':>6} {'e_tpex':>6} {'e_expired':>9} {'e_live':>6} {'e_ratio':>7}  updated_at")
    for d, p in files:
        st = load(p)
        res = st.get("results", {})
        c = collections.Counter(r.get("status") for r in res.values())
        e = collections.Counter()
        for sid, r in res.items():
            if r.get("status") != "empty":
                continue
            mkt, mat = info.get(sid, ("?", None))
            e[mkt] += 1
            e["expired" if (mat and mat < today) else "live"] += 1
            hosts_all[host_of(r.get("error", ""))] += 1
        attempted = c["ok"] + c["empty"]
        ratio = c["empty"] / attempted if attempted else 0.0
        print(f"{d:10} {st.get('target_count', len(res)):>7} {c['ok']:>6} {c['empty']:>6} "
              f"{c['error']:>5} {c['pending']:>5} | {e['twse']:>6} {e['tpex']:>6} "
              f"{e['expired']:>9} {e['live']:>6} {ratio:>7.1%}  {st.get('updated_at', '')}")
        tot.update(c)
        tot.update({f"e_{k}": v for k, v in e.items()})
    print(f"TOTAL ok={tot['ok']} empty={tot['empty']} error={tot['error']} pending={tot['pending']} "
          f"| empty twse={tot['e_twse']} tpex={tot['e_tpex']} expired_now={tot['e_expired']} "
          f"live={tot['e_live']}")
    print("empty by mirror (from the recorded message):")
    for h, n in hosts_all.most_common():
        print(f"  {h}: {n}")
    conn.close()


def stratified(items: list, key, n: int, rng: random.Random) -> list:
    groups = collections.defaultdict(list)
    for it in items:
        groups[key(it)].append(it)
    for g in groups.values():
        rng.shuffle(g)
    out = []
    keys = sorted(groups)
    while len(out) < n and any(groups[k] for k in keys):
        for k in keys:
            if groups[k] and len(out) < n:
                out.append(groups[k].pop())
    return out


class Polite:
    """每站兩次請求之間至少 ``interval`` 秒;站與站之間互不等待(一次只發一個請求)。"""

    def __init__(self, interval: float):
        self.interval = interval
        self.last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        gap = self.interval - (time.monotonic() - self.last.get(host, -1e9))
        if gap > 0:
            time.sleep(gap)
        self.last[host] = time.monotonic()


def fetch_raw(session: requests.Session, base: str, sid: str, date_iso: str) -> dict:
    y, m, d = date_iso.split("-")
    dj = f"{int(y)}-{int(m)}-{int(d)}"
    url = f"{base}/z/zc/zco/zco.djhtm"
    t0 = time.monotonic()
    try:
        r = session.get(url, params={"a": sid, "e": dj, "f": dj}, timeout=config.HTTP_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        return {"status": -1, "bytes": 0, "secs": time.monotonic() - t0, "html": "",
                "err": f"{type(e).__name__}: {str(e)[:80]}"}
    r.encoding = "big5"
    html = r.text
    return {"status": r.status_code, "bytes": len(r.content), "secs": time.monotonic() - t0,
            "html": html, "final_url": r.url, "err": None, "dj": dj}


def describe(html: str, sid: str, dj: str) -> dict:
    title = _TITLE_RE.search(html)
    text = re.sub(r"\s+", " ", _TAG_RE.sub(" ", html)).strip()
    hits = [w for w in SUSPECT_WORDS if w in html]
    hint = ""
    if hits:
        i = text.find(hits[0])
        hint = text[max(0, i - 40): i + 60] if i >= 0 else ""
    else:
        i = text.find(sid)
        hint = text[i: i + 100] if i >= 0 else text[:100]
    return {"rows": len(fubon._ROW.findall(html)), "title": (title.group(1).strip()[:40] if title else ""),
            "has_sid": sid in html, "has_date": dj in html, "suspect": hits[:4], "hint": hint}


def cmd_probe(args) -> None:
    files = state_files(args.state_base, args.market, args.date_from, args.date_to)
    if not files:
        print("no state files in range; run `report` first to check the path")
        return
    conn = open_ro(args.db)
    info = warrant_info(conn)
    today = today_iso()
    rng = random.Random(args.seed)
    empties, oks = [], []
    for d, p in files:
        for sid, r in load(p).get("results", {}).items():
            mkt, mat = info.get(sid, ("?", None))
            item = {"sid": sid, "date": d, "market": mkt, "maturity": mat,
                    "expired": bool(mat and mat < today), "recorded": r.get("status"),
                    "msg": r.get("error", "")}
            if r.get("status") == "empty":
                empties.append(item)
            elif r.get("status") == "ok":
                oks.append(item)
    pick_e = stratified(empties, lambda x: (x["market"], x["expired"]), args.empties, rng)
    # 對照組要 DB 裡真的有列(state 的 ok 可能是 rows=0 的空表)。
    rng.shuffle(oks)
    ctl_exp, ctl_live = [], []
    n_exp = (args.controls + 1) // 2
    n_live = args.controls - n_exp
    for it in oks:
        if len(ctl_exp) >= n_exp and len(ctl_live) >= n_live:
            break
        bucket, cap = (ctl_exp, n_exp) if it["expired"] else (ctl_live, n_live)
        if len(bucket) >= cap:
            continue
        n = conn.execute("SELECT COUNT(*) FROM branch_trades_raw WHERE stock_id=? AND date=?",
                         (it["sid"], it["date"])).fetchone()[0]
        if n > 0:
            it["db_rows"] = n
            bucket.append(it)
    if len(ctl_exp) < n_exp:
        # 範圍內沒有「已到期卻抓得到列」的對照時,往範圍外的日期找(新的日期優先)。
        in_range = {p for _, p in files}
        for d, p in reversed(state_files(args.state_base, args.market, None, None)):
            if len(ctl_exp) >= n_exp or p in in_range:
                continue
            for sid, r in load(p).get("results", {}).items():
                mkt, mat = info.get(sid, ("?", None))
                if r.get("status") != "ok" or not (mat and mat < today):
                    continue
                n = conn.execute("SELECT COUNT(*) FROM branch_trades_raw WHERE stock_id=? AND date=?",
                                 (sid, d)).fetchone()[0]
                if n > 0:
                    ctl_exp.append({"sid": sid, "date": d, "market": mkt, "maturity": mat,
                                    "expired": True, "recorded": "ok", "msg": "", "db_rows": n})
                    if len(ctl_exp) >= n_exp:
                        break
    pairs =[dict(x, kind="EMPTY") for x in pick_e] + [dict(x, kind="CTRL") for x in ctl_exp + ctl_live]
    for it in pairs:
        it["last_trade"] = conn.execute("SELECT MAX(date) FROM warrant_daily WHERE warrant_id=?",
                                        (it["sid"],)).fetchone()[0]
    conn.close()
    print(f"today={today}; empties in range={len(empties)}, ok in range={len(oks)}; "
          f"probing {len(pick_e)} empties + {len(ctl_exp)} expired-ctrl + {len(ctl_live)} live-ctrl "
          f"on {args.mirrors} mirror(s) each, >= {args.per_host_interval}s per host")
    dump = Path(args.dump_dir) if args.dump_dir else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = config.USER_AGENT
    polite = Polite(args.per_host_interval)
    hosts = list(fubon.MIRROR_HOSTS)
    summary = collections.Counter()
    for k, it in enumerate(pairs):
        print(f"\n[{it['kind']}] {it['sid']} {it['date']} market={it['market']} maturity={it['maturity']} "
              f"expired_now={it['expired']} last_trade={it['last_trade']} recorded={it['recorded']}"
              + (f" db_rows={it['db_rows']}" if "db_rows" in it else "")
              + (f"\n    recorded msg: {it['msg'][:220]}" if it["msg"] else ""))
        any_rows = False
        for j in range(args.mirrors):
            base = hosts[(k + j) % len(hosts)]
            netloc = urlparse(base).netloc
            polite.wait(netloc)
            r = fetch_raw(session, base, it["sid"], it["date"])
            if r["err"]:
                print(f"    {netloc:38} ERR {r['err']} ({r['secs']:.1f}s)")
                summary[f"{netloc} transport_error"] += 1
                continue
            dsc = describe(r["html"], it["sid"], r["dj"])
            any_rows = any_rows or dsc["rows"] > 0
            summary[f"{netloc} {'rows' if dsc['rows'] else 'zero'}"] += 1
            print(f"    {netloc:38} http={r['status']} bytes={r['bytes']} {r['secs']:.1f}s rows={dsc['rows']} "
                  f"title={dsc['title']!r} has_sid={dsc['has_sid']} has_date={dsc['has_date']} "
                  f"suspect={dsc['suspect']}\n{'':42}hint: {dsc['hint']!r}")
            if dump:
                (dump / f"{it['sid']}_{it['date']}_{netloc}.html").write_text(r["html"], encoding="utf-8")
        it["rows_now"] = any_rows
        summary[f"{it['kind']} {'expired' if it['expired'] else 'live'} rows_now={any_rows}"] += 1
    print("\n=== summary ===")
    for key in sorted(summary):
        print(f"  {key}: {summary[key]}")
    print("\nread it like this:")
    print("  EMPTY live rows_now=True      -> the recorded empty was a bad page; un-record and refetch")
    print("  EMPTY expired rows_now=False  + CTRL expired rows_now=False -> mirrors drop expired")
    print("        warrants' history; those empties are unrecoverable from this source (not poison)")
    print("  CTRL live rows_now=False      -> the mirrors are refusing us right now; stop and wait")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("report", "probe"):
        p = sub.add_parser(name)
        p.add_argument("--state-base", default=DEFAULT_STATE_BASE,
                       help="same value as WARRANT_STATE_BASE (relative to /app/pipeline)")
        p.add_argument("--market", default="all")
        p.add_argument("--from", dest="date_from", help="YYYY-MM-DD, inclusive")
        p.add_argument("--to", dest="date_to", help="YYYY-MM-DD, inclusive")
        p.add_argument("--db", default=str(Path(config.DATA_DIR) / "radar.db"))
        if name == "probe":
            p.add_argument("--empties", type=int, default=30)
            p.add_argument("--controls", type=int, default=10)
            p.add_argument("--mirrors", type=int, default=3)
            p.add_argument("--per-host-interval", type=float, default=5.0)
            p.add_argument("--seed", type=int, default=0)
            p.add_argument("--dump-dir")
    args = ap.parse_args(argv)
    if getattr(args, "per_host_interval", 5.0) < 5.0:
        ap.error("--per-host-interval below 5 s is not allowed (these are free mirrors)")
    if getattr(args, "mirrors", 1) > len(fubon.MIRROR_HOSTS):
        ap.error(f"--mirrors at most {len(fubon.MIRROR_HOSTS)}")
    {"report": cmd_report, "probe": cmd_probe}[args.cmd](args)


if __name__ == "__main__":
    main()
