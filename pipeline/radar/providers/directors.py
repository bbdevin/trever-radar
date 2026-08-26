"""董監事持股餘額明細(docs/34 §4.6 D1)。

上市:https://openapi.twse.com.tw/v1/opendata/t187ap11_L
上櫃:https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O
僅最新申報月；月更。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..http import get_json

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap11_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"


@dataclass(frozen=True)
class DirectorRow:
    stock_id: str
    as_of_ym: str  # YYYY-MM
    title: str
    name: str
    shares: int
    shares_at_election: int
    pledged_shares: int
    pledged_pct: float | None
    related_shares: int
    market: str  # twse | tpex


def parse_roc_ym(raw: str) -> str:
    """民國 YYYMM 或西元 YYYYMM → YYYY-MM。例:11507 → 2026-07；202607 → 2026-07。"""
    s = (raw or "").strip().replace("/", "").replace("-", "")
    if len(s) == 6 and s.isdigit():
        y4 = int(s[:4])
        if 1911 <= y4 <= 2100:
            return f"{s[:4]}-{s[4:6]}"
    if len(s) >= 5 and s[:5].isdigit():
        yyy, mm = s[:3], s[3:5]
        return f"{int(yyy) + 1911:04d}-{mm}"
    raise ValueError(f"bad director ym: {raw!r}")


def _pick(row: dict, *needles: str) -> str:
    """Match key by exact or substring (API keys are Chinese)."""
    for n in needles:
        if n in row:
            return str(row[n] if row[n] is not None else "")
    for k, v in row.items():
        ks = str(k).strip()
        for n in needles:
            if n in ks:
                return str(v if v is not None else "")
    return ""


def _to_int(v: str) -> int:
    s = (v or "").strip().replace(",", "").replace("%", "")
    if not s or s == "-":
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _to_pct(v: str) -> float | None:
    s = (v or "").strip().replace(",", "").replace("%", "")
    if not s or s == "-":
        return None
    try:
        return round(float(s), 4)
    except ValueError:
        return None


def parse_director_rows(raw: list[dict], market: str) -> list[DirectorRow]:
    out: list[DirectorRow] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        code = _pick(row, "公司代號", "公司代碼").strip()
        if not code or not code[0].isdigit():
            continue
        ym_raw = _pick(row, "資料年月")
        try:
            as_of_ym = parse_roc_ym(ym_raw)
        except ValueError:
            continue
        title = _pick(row, "職稱").strip()
        name = _pick(row, "姓名").strip()
        if not name:
            continue
        # TWSE 選任時持股 key 偶有尾空白
        shares_el = _to_int(_pick(row, "選任時持股"))
        shares = _to_int(_pick(row, "目前持股"))
        pledged = _to_int(_pick(row, "設質股數"))
        pledged_pct = _to_pct(_pick(row, "設質股數佔持股比例", "設質比例"))
        related = _to_int(_pick(row, "內部人關係人目前持股合計"))
        out.append(
            DirectorRow(
                stock_id=code,
                as_of_ym=as_of_ym,
                title=title or "—",
                name=name,
                shares=shares,
                shares_at_election=shares_el,
                pledged_shares=pledged,
                pledged_pct=pledged_pct,
                related_shares=related,
                market=market,
            )
        )
    return out


def fetch_twse_directors() -> list[DirectorRow]:
    data = get_json(TWSE_URL)
    if not isinstance(data, list):
        raise RuntimeError(f"twse directors: unexpected {type(data)}")
    rows = parse_director_rows(data, "twse")
    if not rows:
        raise RuntimeError("twse directors: empty parse")
    return rows


def fetch_tpex_directors() -> list[DirectorRow]:
    data = get_json(TPEX_URL)
    if not isinstance(data, list):
        raise RuntimeError(f"tpex directors: unexpected {type(data)}")
    rows = parse_director_rows(data, "tpex")
    if not rows:
        raise RuntimeError("tpex directors: empty parse")
    return rows


def fetch_all_directors() -> list[DirectorRow]:
    return fetch_twse_directors() + fetch_tpex_directors()


def insider_numerator_shares(
    rows: list[tuple[str, int | None, int | None]],
) -> int:
    """內部人％分子（對齊籌碼類 App）。

    - 同一姓名兼職雙列（董事＋經理）只計一次（取目前持股較大列，關係人同列）。
    - 每人貢獻 = 目前持股 + 內部人關係人目前持股合計（關係人欄為關係人側，與本人相加）。
    """
    by_name: dict[str, tuple[int, int]] = {}
    for name, shares, related in rows:
        key = (name or "").strip()
        if not key:
            continue
        sh = int(shares or 0)
        rel = int(related or 0)
        prev = by_name.get(key)
        if prev is None or sh > prev[0] or (sh == prev[0] and rel > prev[1]):
            by_name[key] = (sh, rel)
    return sum(sh + rel for sh, rel in by_name.values())
