"""題材分類的 additive lifecycle 規則。

題材來源無法可靠地宣告「已退休」：抓取不完整、空回應或測試 limit 都可能
暫時少掉成分。因此 lifecycle 只會把資料降為 stale，絕不由自動匯入推論 retired。
"""
from __future__ import annotations

from datetime import date


THEME_TTL_DAYS = 35
ACTIVE = "active"
STALE = "stale"
RETIRED = "retired"
VALID_STATUSES = frozenset({ACTIVE, STALE, RETIRED})


def displayed_status(
    status: str | None,
    data_date: str | None,
    source_updated_at: str | None,
    quote_date: str,
) -> str | None:
    """回傳要顯示的狀態；舊列沒有 lifecycle metadata 時保留未知。

    `source_updated_at` 可含 ISO 時間，資料日優先，兩者都無法解析時不猜測。
    retired 是人工／明確來源狀態，絕不可被 TTL 覆寫。
    """
    if status not in VALID_STATUSES:
        return None
    if status == RETIRED:
        return RETIRED
    if status == STALE:
        return STALE
    source_day = data_date or (source_updated_at or "")[:10]
    try:
        age = (date.fromisoformat(quote_date) - date.fromisoformat(source_day)).days
    except (TypeError, ValueError):
        return STALE
    # A source date after the quote date is a future leak, never a fresh row.
    return STALE if age < 0 or age > THEME_TTL_DAYS else ACTIVE


def eligible_for_hot_theme(
    *, status: str | None, data_date: str | None, heat_date: str | None, quote_date: str,
) -> bool:
    """H1 僅接受當日熱度與可驗證的 active 公司分類，並拒絕未來資料。"""
    if status != ACTIVE or heat_date != quote_date or not data_date:
        return False
    try:
        return date.fromisoformat(data_date) <= date.fromisoformat(quote_date)
    except ValueError:
        return False
