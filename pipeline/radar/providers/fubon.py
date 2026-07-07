"""富邦 ebrokerdj(MoneyDJ)個股分點進出頁 — 免費公開網頁,無登入無驗證碼。

注意(docs/03/13):非官方資料源,頁面可能改版或限流;僅供私人低頻盤後抓取,
每股每日前 15 大買/賣超(張)。長期正解仍是 FinMind 贊助方案的全量分點資料。
"""
import re

from ..http import get_text
from . import NoDataError

BASE = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"

_ROW = re.compile(
    r'zco0\.djhtm\?a=[^&"]*&(?:amp;)?b=([^&"]+)&(?:amp;)?BHID=([^"&]+)"[^>]*>([^<]+)</a></TD>\s*'
    r'<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>([\d,]+)</TD>\s*'
    r'<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>([\d.,]+)%?</TD>',
    re.IGNORECASE | re.DOTALL,
)


def _num(s: str) -> int:
    return int(s.replace(",", "") or 0)


def fetch_branch_trades(stock_id: str, date: str) -> list[dict]:
    """date: YYYYMMDD → 該日前 15 大買/賣超分點(合計最多 30 列)。"""
    dj = f"{int(date[:4])}-{int(date[4:6])}-{int(date[6:8])}"   # 頁面用 2026-7-6 格式
    html = get_text(BASE, {"a": stock_id, "e": dj, "f": dj})
    matches = _ROW.findall(html)
    if not matches:
        raise NoDataError(f"fubon zco {stock_id} {date}: no branch rows")
    iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    rows = []
    seen = set()
    for key, bhid, name, buy, sell, _net, pct in matches:
        if key in seen:            # 同分點理論上不重複,防禦頁面異常
            continue
        seen.add(key)
        b, s = _num(buy), _num(sell)
        try:
            pct_f = float(pct.replace(",", ""))
        except ValueError:
            pct_f = None
        rows.append({
            "stock_id": stock_id, "date": iso, "branch_key": key,
            "broker_id": bhid.strip(), "branch_name": name.strip(),
            "buy_lots": b, "sell_lots": s, "net_lots": b - s, "pct": pct_f,
            "source": "fubon",
        })
    return rows
