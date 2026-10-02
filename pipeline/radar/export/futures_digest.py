"""每日期貨量異常摘要(ntfy 推播用;docs/38 §7.19)。

只讀剛寫好的 ``radar.json`` 與 ``stocks_index.json``,**不開資料庫**:推播講的必須
就是網站上那一份,不是第二次計算。名單缺鍵(沒有算過)或空陣列(算過、沒有人
舉旗)時不產生任何訊息——單人網站,沒事就不吵。

措辭紀律與網站相同:只講「期貨量創新高、現貨有沒有跟上」這件被檢定過的事,
並把 docs/40 量到的漲跌次數原樣附上——它預告的是波動,不是上漲。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..compute.futures_volume_battery import FORWARD_SPOT_DAYS

SITE_URL = "https://radar.techtrever.com/?tab=futures"

# docs/40 第 1 次執行(docs/evidence/next-day-futures-signal-battery-20261002.json,
# companion.signal):F_only 之後第二個交易日漲 ≥3% / 跌 ≥3% 的次數。已凍結的歷史
# 紀錄,不是每天重算的數字;與前端 lib/futures.ts 的 NEXT_DAY_EVIDENCE 同一份。
NEXT_DAY_EVIDENCE = {"events": 551, "up3": 81, "down3": 112}


def contract_label(multiplier: int | None, stock_id: str) -> str:
    """契約代碼的白話名稱(使用者:「REF JFF 這些縮寫都要寫清楚是什麼」)。

    規則與前端 ``contractLabel`` 相同:代號 00 開頭(指數股票型基金)→ 指數基金期貨;
    每口 2,000 股 → 個股期貨;100 股 → 小型個股期貨;其他已知乘數 → 期貨(每口 N 股);
    未知 → 期貨。不寫 ETF 這個縮寫(使用者規則:縮寫不解釋就不要寫)。
    """
    if stock_id.startswith("00"):
        return "指數基金期貨"
    if multiplier == 2000:
        return "個股期貨"
    if multiplier == 100:
        return "小型個股期貨"
    if multiplier is not None:
        return f"期貨（每口 {multiplier:,} 股）"
    return "期貨"


def contract_labels(entries: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """``(stock_id, code) → 名稱``,同一檔的契約兩兩不同(與前端 ``contractLabelsByCode``
    同一套補法:先補「每口 N 股」,仍同名再補「第 N 個契約」)。"""
    by_stock: dict[str, dict[str, int | None]] = {}
    for e in entries:
        by_stock.setdefault(e["stock_id"], {}).setdefault(e["code"], e.get("multiplier"))
    out: dict[tuple[str, str], str] = {}
    for stock_id, contracts in by_stock.items():
        codes = list(contracts)
        labels = [contract_label(contracts[c], stock_id) for c in codes]
        labels = [
            f"{label}（每口 {contracts[c]:,} 股）"
            if labels.count(label) > 1 and contracts[c] is not None and "每口" not in label
            else label
            for c, label in zip(codes, labels)
        ]
        seen: dict[str, int] = {}
        final = []
        for label in labels:
            if labels.count(label) > 1:
                seen[label] = seen.get(label, 0) + 1
                label = f"{label}（第 {seen[label]} 個契約）"
            final.append(label)
        out.update({(stock_id, c): label for c, label in zip(codes, final)})
    return out


def _names(out: Path) -> dict[str, str]:
    path = out / "stocks_index.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        row[0]: row[1] for row in rows
        if isinstance(row, list) and len(row) >= 2
        and isinstance(row[0], str) and isinstance(row[1], str)
    }


def build_digest(out: Path) -> tuple[str, str] | None:
    """``(title, body)``;名單缺鍵或為空時 ``None``(呼叫端什麼都不送)。"""
    radar: dict[str, Any] = json.loads((out / "radar.json").read_text(encoding="utf-8"))
    entries = radar.get("futures_volume_anomalies")
    if not entries:
        return None
    meta = radar.get("futures_volume_anomalies_meta") or {}
    as_of = meta.get("as_of")
    window_days = meta.get("window_days")
    if not as_of or not window_days:
        # 講不出是哪一天、比的是幾日,就不送——推播不編日期。
        return None
    names = _names(out)
    lagging = [e for e in entries if e.get("spot_new_high") is False]
    labels = contract_labels(entries)
    listed = "、".join(
        f"{names.get(e['stock_id'], '')} {e['stock_id']}（"
        f"{labels[(e['stock_id'], e['code'])]}）".lstrip()
        for e in lagging
    )
    head = (
        f"{as_of} 有 {len(entries)} 個契約一般時段成交量創 {window_days} 日新高，"
        f"其中 {len(lagging)} 個現貨當日尚未同步創高"
    )
    head += f"：{listed}。" if lagging else "。"
    ev = NEXT_DAY_EVIDENCE
    tail = (
        f"回測只證明現貨量在 {FORWARD_SPOT_DAYS} 日內跟上的次數比平常多，不是漲跌"
        f"（漲 ≥3% {ev['up3']} 次／跌 ≥3% {ev['down3']} 次，共 {ev['events']} 次）。"
    )
    return f"期貨量異常 · {as_of}", f"{head}{tail}\n{SITE_URL}"
