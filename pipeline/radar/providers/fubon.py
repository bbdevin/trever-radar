"""富邦 ebrokerdj(MoneyDJ)個股分點進出頁 — 免費公開網頁,無登入無驗證碼。

注意(docs/03/13):非官方資料源,頁面可能改版或限流;僅供私人低頻盤後抓取,
每股每日前 15 大買/賣超(張)。長期正解仍是 FinMind 贊助方案的全量分點資料。
"""
import re

from ..http import get_text
from . import NoDataError

# MoneyDJ 平台鏡像站(同一套 zco 頁,資料一致——實測富邦/元富回傳位元級相同)。
# 輪替分散負載:整體 1.2 秒/請求時,單站有效節奏 = 1.2 × 站數。
MIRROR_HOSTS = [
    "https://fubon-ebrokerdj.fbs.com.tw",
    "https://newjust.masterlink.com.tw",
]
_mirror_i = 0


def _next_host() -> str:
    global _mirror_i
    host = MIRROR_HOSTS[_mirror_i % len(MIRROR_HOSTS)]
    _mirror_i += 1
    return host


BASE = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm"
THEME_LIST = "https://fubon-ebrokerdj.fbs.com.tw/z/zh/zha/zha.djhtm"
THEME_MEMBERS = "https://fubon-ebrokerdj.fbs.com.tw/z/zh/zhc/zhc.djhtm"

_THEME_LINK = re.compile(r'zhc\.djhtm\?a=(C\d+)"[^>]*>([^<]{1,20})</a>', re.IGNORECASE)
_MEMBER = re.compile(r"GenLink2stk\('A[SO]?(\d{4,6}[A-Z]?)','[^']+'\)")


def fetch_theme_list() -> list[tuple[str, str]]:
    """概念股分類清單 [(code, name), ...],約數百類。"""
    html = get_text(THEME_LIST)
    seen: dict[str, str] = {}
    for code, name in _THEME_LINK.findall(html):
        seen.setdefault(code, name.strip())
    if not seen:
        raise NoDataError("fubon zha: no theme links")
    return list(seen.items())


def fetch_theme_members(code: str) -> list[str]:
    """單一概念股分類的成分股代號(僅個股,4 碼)。"""
    html = get_text(THEME_MEMBERS, {"a": code})
    return sorted({m for m in _MEMBER.findall(html) if len(m) == 4 and m.isdigit()})

_ROW = re.compile(
    r'zco0\.djhtm\?a=[^&"]*&(?:amp;)?b=([^&"]+)&(?:amp;)?BHID=([^"&]+)"[^>]*>([^<]+)</a></TD>\s*'
    r'<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>([\d,]+)</TD>\s*'
    r'<TD[^>]*>([\d,]+)</TD>\s*<TD[^>]*>([\d.,]+)%?</TD>',
    re.IGNORECASE | re.DOTALL,
)


def _num(s: str) -> int:
    return int(s.replace(",", "") or 0)


def fetch_branch_trades(stock_id: str, date: str, throttle: float | None = None) -> list[dict]:
    """date: YYYYMMDD → 該日前 15 大買/賣超分點(合計最多 30 列)。鏡像站輪替。"""
    dj = f"{int(date[:4])}-{int(date[4:6])}-{int(date[6:8])}"   # 頁面用 2026-7-6 格式
    url = f"{_next_host()}/z/zc/zco/zco.djhtm"
    html = get_text(url, {"a": stock_id, "e": dj, "f": dj}, throttle=throttle)
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


def fetch_company_profile(stock_id: str) -> str | None:
    """抓取 MoneyDJ 的公司基本資料(營收比重)"""
    import html
    url = f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zca/zca_{stock_id}.djhtm"
    try:
        raw = get_text(url)
    except Exception:
        return None
    
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    
    m = re.search(r'營收比重(.*?)(?:\(| \d{4}年| $)', text)
    if m:
        s = m.group(1).strip()
        s = re.sub(r'\s*\(\d{4}.*$', '', s)
        s = re.sub(r'\s*$', '', s)
        if s and s not in ("N/A", "--", "---"):
            return s
    return None
