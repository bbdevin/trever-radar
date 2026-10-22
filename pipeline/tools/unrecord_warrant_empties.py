"""把權證分點回補 state 檔裡可疑的 ``empty`` 撤銷,讓下一塊回補重抓。**預設 dry-run。**

``empty`` 是終端狀態(回補下次不再抓)。2026-10-22 事故懷疑有一批 empty 其實是鏡像回的
錯誤／限流頁;先用 ``tools/probe_backfill_empties.py`` 確認,再用這支把指定範圍的 empty
從 state 檔移除(移除 = 下一次回補把它當 pending 重抓)。**不碰 DB**——DB 只以
``mode=ro`` 讀到期日(``--scope live|expired`` 時)。

``--apply`` 才寫檔;寫之前每個檔另存一份 ``<檔名>.pre-unrecord-<時間>`` 備份,檔內加一筆
``unrecorded`` 稽核紀錄。要還原:把備份 rename 回原檔名即可。

**這是對正式 state 的變更,須人類核准後才加 ``--apply``**;而且必須在回補沒在跑時執行——
在主機上用 ``flock -n /tmp/radar-db.lock`` 包住(回補整塊都握著這把鎖,拿不到就代表它在跑):

    cd ~/trever-radar
    # 1) dry-run(預設):只印會改什麼
    docker run --rm -v "$PWD/pipeline":/app/pipeline -v "$PWD/data":/app/data -w /app/pipeline \\
      radar-pipeline python tools/unrecord_warrant_empties.py --from 2026-08-06 --to 2026-08-12 --scope live
    # 2) 核准後才 apply
    flock -n /tmp/radar-db.lock docker run --rm -v "$PWD/pipeline":/app/pipeline -v "$PWD/data":/app/data \\
      -w /app/pipeline radar-pipeline python tools/unrecord_warrant_empties.py \\
      --from 2026-08-06 --to 2026-08-12 --scope live --apply

``--scope``:``all``(範圍內全部 empty)/ ``live``(今天還沒過到期日的權證,含到期日未知)/
``expired``(今天已過到期日)。``--host-contains`` 只撤銷訊息裡寫著那一站回的 empty
(2026-10-22 之後的訊息才帶 host)。
"""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar import config  # noqa: E402
from radar.importer import _atomic_json_write  # noqa: E402
from tools.probe_backfill_empties import DEFAULT_STATE_BASE, state_files  # noqa: E402


def select(results: dict, scope: str, maturity: dict, today: str, host_contains: str | None) -> list[str]:
    out = []
    for sid, r in results.items():
        if r.get("status") != "empty":
            continue
        if host_contains and host_contains not in r.get("error", ""):
            continue
        mat = maturity.get(sid)
        expired = bool(mat and mat < today)
        if scope == "live" and expired:
            continue
        if scope == "expired" and not expired:
            continue
        out.append(sid)
    return out


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state-base", default=DEFAULT_STATE_BASE)
    ap.add_argument("--market", default="all")
    ap.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD, inclusive")
    ap.add_argument("--scope", choices=("all", "live", "expired"), default="all")
    ap.add_argument("--host-contains")
    ap.add_argument("--db", default=str(Path(config.DATA_DIR) / "radar.db"))
    ap.add_argument("--apply", action="store_true", help="actually rewrite the state files")
    args = ap.parse_args(argv)

    files = state_files(args.state_base, args.market, args.date_from, args.date_to)
    if not files:
        print(f"no state files for {args.state_base} market={args.market} "
              f"{args.date_from}..{args.date_to} (cwd={Path.cwd()})")
        return 1
    today = datetime.now(ZoneInfo(config.TZ)).date().isoformat()
    maturity: dict = {}
    if args.scope != "all":
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=30)
        maturity = {r[0]: r[1] for r in conn.execute("SELECT id, maturity_date FROM warrants")}
        conn.close()
    stamp = datetime.now(ZoneInfo(config.TZ)).strftime("%Y%m%dT%H%M%S")
    total = 0
    for d, path in files:
        state = json.loads(path.read_text(encoding="utf-8"))
        results = state.get("results", {})
        chosen = select(results, args.scope, maturity, today, args.host_contains)
        counts = collections.Counter(r.get("status") for r in results.values())
        print(f"{d}: {path.name} ok={counts['ok']} empty={counts['empty']} -> "
              f"un-record {len(chosen)} ({args.scope}"
              + (f", host~{args.host_contains}" if args.host_contains else "") + ")")
        total += len(chosen)
        if not chosen or not args.apply:
            continue
        backup = path.with_name(f"{path.name}.pre-unrecord-{stamp}")
        shutil.copy2(path, backup)
        for sid in chosen:
            del results[sid]
        state.setdefault("unrecorded", []).append({
            "at": stamp, "count": len(chosen), "scope": args.scope,
            "host_contains": args.host_contains, "backup": backup.name})
        _atomic_json_write(path, state)
        print(f"    written; backup {backup.name}")
    verb = "un-recorded" if args.apply else "would un-record (dry-run; add --apply after approval)"
    print(f"TOTAL {verb}: {total} empty entr{'y' if total == 1 else 'ies'} in {len(files)} file(s); "
          f"each costs ~2 requests (~2.5 s) in the next backfill chunk")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
