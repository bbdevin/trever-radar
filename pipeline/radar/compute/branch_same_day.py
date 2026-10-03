"""同一分點名稱、同一檔、同一天有多列時的合併規則(docs/43 §1)。

`branch_trades` 是依 branch_key 存的;不同來源頁、改名後被 canonical_name
併成同一個名稱的多個 branch_key,可能在同一天各有一列。以分點**名稱**為單位
計算的模組(分點統計、v2 shadow、分位計數、PIT 帳本／報表、方向 battery)
以前遇到這種日子的處理,要嘛「留最後一列」(誰是最後一列取決於檔案的實體
排列或查詢計畫),要嘛「每列各算一次」——結果跟著版面走,而且語意上都不對。

規則:同名同日的各列**加總**。
* buy/sell/net 是張數,不同 branch_key 是同一個分點名稱下互不重疊的成交,相加
  就是這個名稱當天的量。
* pct 是該列淨買超佔當日成交值的百分比;分母(當日成交值)相同,所以相加後
  仍等於「合計淨買超 ÷ 成交值」,與 net 的加總一致。取平均或取最大都會讓 pct
  與 net 對不起來。
* 缺值:全部 None 才是 None;否則加總有值的部分(與只有一列時相同)。
* 浮點用 math.fsum:結果與列的先後無關(一般 sum 在三列以上會因順序差最後一位)。

只有一列的日子(絕大多數)數值原封不動。
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping


def combine(values: Iterable[Any]) -> Any:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    if any(isinstance(v, float) for v in vals):
        return math.fsum(vals)
    return sum(vals)


def merge_by_date(rows: Iterable[Mapping[str, Any]], fields: tuple[str, ...],
                  date_key: str = "date") -> dict[str, dict[str, Any]]:
    """一個(個股, 分點名稱)的列 → {date: {field: 合併值}},依日期排序。"""
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_date.setdefault(row[date_key], []).append(row)
    return {
        day: {field: combine(r[field] for r in day_rows) for field in fields}
        for day, day_rows in sorted(by_date.items())
    }
