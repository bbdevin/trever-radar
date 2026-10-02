"""分點名稱的正規化:亂碼修正、改名對照、停業判定(2026-10-02)。

為什麼需要它
------------
來源(MoneyDJ/Fubon 鏡像)給的分點名稱有三種問題,在 2026-10-02 用正式資料查出:

1. **亂碼**:「犇」不在來源編碼裡,被寫成「(牛牛牛)」——「(牛牛牛)亞證券」
   「(牛牛牛)亞-鑫豐」「(牛牛牛)亞-網路」三個分點都還在交易、還在排行裡。
2. **改名**:同一個營業據點換了名稱與代號。「台新-營業部」(9B17)最後一筆是
   2026-04-02,清明連假後 2026-04-07 起出現「台新」(9B00)並持續到今天
   (17 萬列)——同一個據點。改名後兩個名稱並存,歷史被切成兩半。
3. **停業**:來源在名稱後加「(停)」(8 個);也有沒加標記、但早已沒有任何交易的
   (凱基-天母理財,最後一筆 2024-12-20)。它們仍被排進分點可信度排行,
   元大-西門(停)甚至以 26 筆樣本排第一——一個已經不存在、無從追蹤的分點。

怎麼用
------
- ``canonical_name``:亂碼修正 + 改名對照。匯入新分點時套用,既有的
  ``branch_dim`` 由 ``db._migrate_sqlite`` 一次修正(冪等)。``branch_trades`` view
  讀的就是 ``branch_dim.branch_name``,所以改名之後全系統看到同一個名稱,兩段
  歷史自然合併成一家(兩段交易日期不重疊,不會重複計算)。
- ``is_closed``:停業判定。分點排行與自動追蹤排除停業分點;**歷史交易不刪**。

改名對照必須有證據(舊名最後交易日、新名第一個交易日、同一家券商),寫在旁邊。
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

# 字元層級的修正:來源編碼不支援的字被寫成替代字串。
TEXT_FIXES: tuple[tuple[str, str], ...] = (
    ("(牛牛牛)", "犇"),
)

# 舊名 → 新名。每一筆都要附證據,而且只收「同券商、舊的停在 A、新的從 A 之後
# 第一個交易日開始」的情況;只是停業(找不到接手者)的不收,交給 is_closed。
RENAMES: dict[str, str] = {
    # 9B17 台新-營業部 最後交易 2026-04-02(190,888 列);9B00 台新 首日 2026-04-07
    # (清明連假後第一個交易日)起持續至今。同券商 9B00 下沒有其他新分點。
    "台新-營業部": "台新",
}

CLOSED_MARKS: tuple[str, ...] = ("(停)",)

# 超過這麼多個日曆日沒有任何一筆交易,就當作已停業(來源不一定會加「(停)」)。
# 120 天:分點只在進入某檔股票前 15 大時才有列,冷門分點偶爾幾週沒列是正常的,
# 但四個月完全沒有任何一檔股票的紀錄,實際上已無從追蹤。
INACTIVE_DAYS = 120


def canonical_name(name: str) -> str:
    fixed = name
    for bad, good in TEXT_FIXES:
        fixed = fixed.replace(bad, good)
    return RENAMES.get(fixed, fixed)


def is_closed(name: str, last_seen: str | None, as_of: str) -> bool:
    """名稱標示停業,或最後一筆交易早於 as_of 前 INACTIVE_DAYS 天。"""
    if any(mark in name for mark in CLOSED_MARKS):
        return True
    if not last_seen:
        return True
    cutoff = date_cls.fromisoformat(as_of) - timedelta(days=INACTIVE_DAYS)
    return date_cls.fromisoformat(last_seen) < cutoff
