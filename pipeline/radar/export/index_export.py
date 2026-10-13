"""`export-index`:只重寫大盤指數相關的三份檔(docs/49 §12.6.5,早上夜盤上線)。

早上 ``morning-index.sh`` 匯入前一夜的台指期盤後收盤(期交所標今天、05:00 收完)後呼叫;全量
``export-json`` 要 ~15 分鐘且握 DB 鎖,這裡只動首頁指數格與走勢 sheet 讀的東西:

* ``radar.json`` 的 ``indices`` 鍵、``home/head.json``(= radar 的投影,``write_home``)——卡片三格與夜盤那一行;
* ``market/indices_hist.json``(``write_indices_hist``)——走勢 sheet 的 1月以上與 1日 基準。

一致性:

* 資料日 ``d`` 讀**現有 radar.json 的 data_date**,不自己算——indices 與 head 的其他鍵(freshness、
  summary、法人)是同一個 d 算的,不會一半今天一半昨天。``indices`` 用的是全量 export 同一個
  ``latest_indices(conn, d)``,所以同一個 DB 狀態下這三份檔與全量 export 寫出來的逐位元相同
  (``indices_hist.json`` 的 ``generated_at`` 為寫檔時刻,與全量相同語意)。
* ``generated_at`` **不動**:``home/stocks.json`` 照原內容重寫(逐位元相同),head/stocks 的
  generated_at 配對(``homeLoad``)與多方榜的 ``radar_generated_at``(``bullBoard.staleText``)都不受影響。
* 三份都是 tmp+rename;``radar.json`` 鍵序照舊(``indices`` 原本沒有時插在 ``insti_market`` 前,
  與全量 export 的位置相同)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .. import config
from ..db import get_engine, init_db
from ..market_index import latest_indices, write_indices_hist
from .home_split import write_home
from .stock_parts import write_atomic


def _with_indices(radar: dict, indices: list[dict]) -> dict:
    """回傳換掉 ``indices`` 的新 dict;鍵序與全量 export 相同。沒有列 → 鍵不出(同全量)。"""
    if not indices:
        return {k: v for k, v in radar.items() if k != "indices"}
    if "indices" in radar:
        return {k: (indices if k == "indices" else v) for k, v in radar.items()}
    out: dict = {}
    for k, v in radar.items():
        if k == "insti_market":
            out["indices"] = indices
        out[k] = v
    if "indices" not in out:
        out["indices"] = indices
    return out


def export_index(out_dir: Path) -> dict:
    """重寫 radar.json 的 indices、home/{stocks,head}.json、market/indices_hist.json。

    radar.json 不存在 → FileNotFoundError(早上沒有前一輪全量 export 就沒有東西可以補)。
    回傳 ``{"date", "night"}``(night = tx 的 night 鍵或 None),給腳本 log。
    """
    out = Path(out_dir)
    radar_path = out / "radar.json"
    radar = json.loads(radar_path.read_text(encoding="utf-8"))
    d = radar["data_date"]
    init_db()
    with get_engine().connect() as conn:
        indices = latest_indices(conn, d)
        new = _with_indices(radar, indices)
        if new != radar or list(new) != list(radar):
            write_atomic(radar_path, json.dumps(new, ensure_ascii=False))
        write_home(out, new)
        now = datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")
        write_indices_hist(out, conn, d, now)
    tx = next((i for i in indices if i["market"] == "tx"), None)
    return {"date": d, "night": tx.get("night") if tx else None}
