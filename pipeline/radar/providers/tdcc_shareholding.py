"""TDCC 集保戶股權分散表(docs/34 B1)。

來源:https://opendata.tdcc.com.tw/getOD.ashx?id=1-5 （僅最新一週）
歷史回補:wirelessr/tdcc-opendata-archive（官方每週覆寫,社群週快照）
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date

from ..http import _get

TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
ARCHIVE_API = (
    "https://api.github.com/repos/wirelessr/tdcc-opendata-archive/contents/snapshots/{year}"
)
ARCHIVE_RAW = (
    "https://raw.githubusercontent.com/wirelessr/tdcc-opendata-archive/main/snapshots/{year}/{ymd}.csv"
)
_TIER_RE = re.compile(r"(\d+)")
_YMD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")


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


def decode_tdcc_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "big5", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_tdcc_shareholding() -> list[ShareholdingRow]:
    """Download latest full-market TDCC CSV and parse."""
    r = _get(TDCC_URL, throttle=0.5)
    rows = parse_tdcc_csv(decode_tdcc_bytes(r.content))
    if not rows:
        raise RuntimeError("tdcc shareholding: empty parse")
    return rows


def list_archive_weeks(year: int) -> list[str]:
    """List YYYY-MM-DD weeks available in wirelessr archive for a calendar year."""
    url = ARCHIVE_API.format(year=year)
    r = _get(url, throttle=0.3)
    try:
        items = r.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"tdcc archive list parse failed: {e}") from e
    if not isinstance(items, list):
        # GitHub API error payload
        raise RuntimeError(f"tdcc archive list unexpected: {json.dumps(items)[:200]}")
    out: list[str] = []
    for it in items:
        name = (it or {}).get("name") or ""
        m = _YMD_RE.match(name)
        if m:
            out.append(m.group(1))
    out.sort()
    return out


def list_archive_weeks_in_range(date_from: str, date_to: str) -> list[str]:
    """Inclusive ISO date range → archive week dates (multi-year OK)."""
    d0 = date.fromisoformat(date_from)
    d1 = date.fromisoformat(date_to)
    if d1 < d0:
        raise ValueError(f"date_to {date_to} < date_from {date_from}")
    weeks: list[str] = []
    for y in range(d0.year, d1.year + 1):
        for w in list_archive_weeks(y):
            wd = date.fromisoformat(w)
            if d0 <= wd <= d1:
                weeks.append(w)
    return weeks


def fetch_archive_week(ymd: str) -> list[ShareholdingRow]:
    """Download one archived weekly CSV (YYYY-MM-DD)."""
    y = ymd[:4]
    url = ARCHIVE_RAW.format(year=y, ymd=ymd)
    r = _get(url, throttle=0.4)
    rows = parse_tdcc_csv(decode_tdcc_bytes(r.content))
    if not rows:
        raise RuntimeError(f"tdcc archive {ymd}: empty parse")
    return rows
