"""TDCC 集保戶股權分散表(docs/34 B1)。

來源:https://opendata.tdcc.com.tw/getOD.ashx?id=1-5
欄位:資料日期、證券代號、持股分級、人數、股數、占集保庫存數比例％
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from ..http import _get

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
_TIER_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class ShareholdingRow:
    stock_id: str
    as_of: str  # YYYY-MM-DD
    tier: int  # 1–15
    holders: int
    shares: int
    pct: float


def parse_tdcc_date(raw: str) -> str:
    """民國 YYYMMDD 或西元 YYYYMMDD / YYYY-MM-DD → ISO date."""
    s = (raw or "").strip().replace("/", "").replace("-", "")
    if len(s) == 7 and s.isdigit():
        y = int(s[:3]) + 1911
        return f"{y:04d}-{s[3:5]}-{s[5:7]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raise ValueError(f"bad TDCC date: {raw!r}")


def parse_tier(raw: str) -> int | None:
    """持股分級 → 1–15;合計／非數字 → None(略過)."""
    t = (raw or "").strip()
    if not t or "合計" in t or "總計" in t:
        return None
    m = _TIER_RE.search(t)
    if not m:
        return None
    n = int(m.group(1))
    if 1 <= n <= 15:
        return n
    return None


def _to_int(v: str) -> int:
    s = (v or "").strip().replace(",", "").replace("%", "")
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _to_float(v: str) -> float:
    s = (v or "").strip().replace(",", "").replace("%", "")
    if not s or s == "-":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _is_header(row: list[str]) -> bool:
    joined = ",".join(row)
    return "證券" in joined or "分級" in joined or "資料日期" in joined


def _header_index(header: list[str]) -> dict[str, int]:
    idx = {c.strip(): i for i, c in enumerate(header)}
    # aliases
    mapping = {
        "date": next((idx[k] for k in idx if "日期" in k), 0),
        "code": next((idx[k] for k in idx if "代號" in k or "代碼" in k), 1),
        "tier": next((idx[k] for k in idx if "分級" in k), 2),
        "holders": next((idx[k] for k in idx if "人數" in k), 3),
        "shares": next((idx[k] for k in idx if "股數" in k), 4),
        "pct": next((idx[k] for k in idx if "比例" in k or "%" in k or "％" in k), 5),
    }
    return mapping


def parse_tdcc_csv(text: str) -> list[ShareholdingRow]:
    """Parse TDCC CSV text into tier rows (合計略過)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    reader = csv.reader(io.StringIO(text))
    rows_out: list[ShareholdingRow] = []
    colmap: dict[str, int] | None = None

    for row in reader:
        if not row or all(not (c or "").strip() for c in row):
            continue
        if colmap is None:
            if _is_header(row):
                colmap = _header_index(row)
                continue
            colmap = {"date": 0, "code": 1, "tier": 2, "holders": 3, "shares": 4, "pct": 5}

        need = max(colmap.values())
        if len(row) <= need:
            continue
        tier = parse_tier(row[colmap["tier"]])
        if tier is None:
            continue
        code = (row[colmap["code"]] or "").strip()
        if not code or not code[0].isdigit():
            continue
        try:
            as_of = parse_tdcc_date(row[colmap["date"]])
        except ValueError:
            continue
        rows_out.append(
            ShareholdingRow(
                stock_id=code,
                as_of=as_of,
                tier=tier,
                holders=_to_int(row[colmap["holders"]]),
                shares=_to_int(row[colmap["shares"]]),
                pct=_to_float(row[colmap["pct"]]),
            )
        )
    return rows_out


def fetch_tdcc_shareholding() -> list[ShareholdingRow]:
    """Download latest full-market TDCC CSV and parse."""
    r = _get(TDCC_URL, throttle=0.5)
    raw = r.content
    text = None
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    rows = parse_tdcc_csv(text)
    if not rows:
        raise RuntimeError("tdcc shareholding: empty parse")
    return rows
