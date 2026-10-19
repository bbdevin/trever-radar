"""``radar fetch-intraday``:export 之前、**不握 DB 鎖**把 Fugle 抓進快取(docs/50 §3.1)。

以前 export-json 在握著 /tmp/radar-db.lock 的時候逐檔打 Fugle(spark_day 當日 1 分 K、
分K 補缺日的 historical 5 分 K):正式機 14:05 那輪 intraday 段 242 s、晚上第一次 export
71–122 s。現在拆成兩步:

1. 本模組(VPS 腳本先放 DB 鎖再跑):用 export **同一段程式**選出榜單聯集
   (``export_json(union_only=True)``,唯讀、不寫檔),然後
   * ``attach_spark_day`` 補抓聯集裡缺的當日分時 → ``data/spark_day.json``;
   * ``update_intraday(write_out=False)`` 用這一輪的 1 分 K 聚成當日 5 分 K、補抓缺日
     → ``data/intraday5/{id}.json``。不寫輸出檔、不做到期刪檔。
   閘門、每輪上限(``ROUND_CAP``)、節流(fugle 模組 ~57 次/分 + 429 退避)全部與在 export
   裡抓時相同——呼叫的就是同一組函式。
2. export-json(重新拿鎖)只讀這兩個快取(``fetch=False``),寫輸出。

同一個快取狀態下,「先抓再 export」的輸出與「export 自己抓」逐位元相同
(``tests/test_intraday_prefetch.py``)。

失敗語意:這一步任何地方壞掉都只是「export 用到比較舊的快取」,與以前在 export 裡
抓失敗相同;CLI 以非 0 結束讓腳本 warn,腳本照常 export。
"""
from __future__ import annotations

import logging
from pathlib import Path

from .intraday_bars import update_intraday
from .spark_day import attach_spark_day, taipei_today

_log = logging.getLogger(__name__)


def prefetch_intraday(out_dir: Path | None = None, *, today: str | None = None) -> dict:
    """抓進快取並回傳統計;``ok=False`` = 有一段丟了例外(已記 warning,另一段照跑)。"""
    from .json_export import DEFAULT_OUT, export_json

    out = Path(out_dir) if out_dir else DEFAULT_OUT   # write_out=False:只用來算路徑,不寫
    sel = export_json(out, union_only=True)
    d, ids = sel["date"], sel["union"]
    today = today if today is not None else taipei_today()
    stats: dict = {"date": d, "today": today, "union": len(ids), "spark_day": None,
                   "intraday": None, "ok": True}

    # spark_day:同 export 的 attach_spark_day(閘門 = 台北今天 = 價格日 + 有金鑰),只是掛在
    # 丟棄式的 dict 上——要的是它寫的快取與這一輪的 1 分 K(minute_rows),不是 union 本身。
    try:
        stats["spark_day"] = attach_spark_day({sid: {} for sid in ids}, d, today=today)
    except Exception:  # noqa: BLE001 — 分時壞了,分K 仍可用歷史端點補
        _log.warning("fetch-intraday: spark_day failed; cache left as is", exc_info=True)
        stats["ok"] = False

    try:
        st = update_intraday(out, ids, d,
                             allow_fetch=today == d, write_out=False)
        stats["intraday"] = {k: st[k] for k in ("requests", "fetched_days", "today")}
    except Exception:  # noqa: BLE001
        _log.warning("fetch-intraday: intraday bars failed; cache left as is", exc_info=True)
        stats["ok"] = False

    print(f"fetch-intraday: date={d} today={today} union={len(ids)} "
          f"spark_day={stats['spark_day']} intraday={stats['intraday']} ok={stats['ok']}",
          flush=True)
    return stats
