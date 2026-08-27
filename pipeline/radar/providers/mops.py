"""Official MOPS t35sc09 buyback-plan provider.

MOPS first returns a short-lived old-site URL.  This module deliberately
accepts only that official HTTPS redirect and parses the returned HTML with
the standard library; no browser or executable HTML is involved.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

import requests

from .. import config
from ..dto import BuybackRow

REDIRECT_URL = "https://mops.twse.com.tw/mops/api/redirectToOld"
SOURCE_URL = "https://mops.twse.com.tw/mops/web/t35sc09"
_OFFICIAL_HOSTS = frozenset({"mops.twse.com.tw", "mopsov.twse.com.tw"})
_MAX_HTML_CHARS = 2_000_000
_REPORT_DATE_RE = re.compile(r"(?:出表日(?:期)?|資料日期|列印日期)\s*[:：]?\s*([0-9]{3,4}(?:[/-][0-9]{1,2}){2}|[0-9]{7,8})")
_STOCK_ID_RE = re.compile(r"^[0-9A-Z]{4,8}$")
_NULLS = frozenset({"", "-", "--", "---", "----", "N/A"})
_REQUEST_HEADERS = {
    # MOPS verifies browser-like requests on both redirect and ephemeral result.
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": SOURCE_URL,
    "Accept": "application/json, text/plain, */*",
}


class MopsBuybackError(RuntimeError):
    """MOPS response did not satisfy the verified t35sc09 contract."""


class _TableCollector(HTMLParser):
    """Collect flat table rows while ignoring script/style text completely."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._ignored = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._ignored += 1
        elif tag == "table":
            self._table_stack.append([])
        elif self._table_stack and tag == "tr":
            self._row = []
        elif self._table_stack and tag in {"td", "th"} and self._row is not None:
            self._cell = []
        elif self._cell is not None and tag == "br":
            self._cell.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style"} and self._ignored:
            self._ignored -= 1
        elif tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table_stack:
            if self._cell is not None:
                self._row.append("".join(self._cell))
                self._cell = None
            self._table_stack[-1].append(self._row)
            self._row = None
        elif tag == "table" and self._table_stack:
            table = self._table_stack.pop()
            self.tables.append(table)

    def handle_data(self, data):
        if not self._ignored and self._cell is not None:
            self._cell.append(data)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.replace("\xa0", " ").split()).strip()
    return None if value in _NULLS else value


def _iso_date(value: str | None) -> str | None:
    value = _clean(value)
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    try:
        if len(digits) == 7:  # ROC YYYMMDD
            return date(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:])).isoformat()
        if len(digits) == 8:  # Gregorian YYYYMMDD
            return date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return None
    return None


def _number(value: str | None, *, integer: bool = False, percent: bool = False):
    value = _clean(value)
    if value is None:
        return None
    normalized = value.replace(",", "").replace("%", "").strip()
    try:
        number = float(normalized)
    except ValueError:
        return None
    return int(number) if integer else number


def _report_date(html: str) -> str | None:
    text = " ".join(html.replace("\xa0", " ").split())
    match = _REPORT_DATE_RE.search(text)
    return _iso_date(match.group(1)) if match else None


def _is_data_row(row: list[str]) -> bool:
    # Official t35sc09 has serial at 0 and stock id at 1.  Do not accept an
    # older/shifted layout merely because its first cell happens to look like an id.
    # A numeric serial is also a candidate: a blank/corrupt id must fail the
    # whole response, not be silently skipped while another plan is imported.
    serial = _clean(row[0]) if row else None
    stock_id = _clean(row[1]) if len(row) >= 2 else None
    return bool(serial and serial.isdigit()) or bool(stock_id and _STOCK_ID_RE.fullmatch(stock_id.upper()))


def _row_to_dto(row: list[str], market: str, report_date: str | None) -> BuybackRow:
    if len(row) != 20:
        raise MopsBuybackError(f"t35sc09 column drift: expected 20, got {len(row)}")
    cells = [_clean(value) for value in row]
    if not cells[0] or not cells[0].isdigit():
        raise MopsBuybackError("t35sc09 invalid serial column")
    stock_id = (cells[1] or "").upper()
    if not _STOCK_ID_RE.fullmatch(stock_id) or not cells[2]:
        raise MopsBuybackError("t35sc09 invalid stock identity")
    # Official 20-column order: serial, id, name, board date, purpose, amount
    # ceiling, planned shares, price range, period, flag, KB1 link, execution
    # facts, issued-share ratio, incomplete reason.  The serial/link are UI-only.
    # t35sc09 has no announcement date.  Do not invent one from board/report dates.
    return BuybackRow(
        stock_id=stock_id, name=cells[2], market=market,
        board_date=_iso_date(cells[3]), purpose=cells[4],
        total_amount_limit=_number(cells[5], integer=True),
        planned_shares=_number(cells[6], integer=True),
        price_min=_number(cells[7]), price_max=_number(cells[8]),
        start_date=_iso_date(cells[9]), end_date=_iso_date(cells[10]),
        completed_flag=cells[11], executed_shares=_number(cells[13], integer=True),
        transferred_shares=_number(cells[14], integer=True), execution_pct=_number(cells[15], percent=True),
        executed_amount=_number(cells[16], integer=True), avg_price=_number(cells[17]),
        share_ratio_pct=_number(cells[18], percent=True), incomplete_reason=cells[19],
        report_date=report_date, source_updated_at=report_date,
    )


def parse_buybacks_html(html: str, market: str) -> list[BuybackRow]:
    """Parse only a complete 20-column data table; malformed pages fail closed."""
    if market not in {"twse", "tpex"}:
        raise ValueError("market must be twse or tpex")
    if not html or len(html) > _MAX_HTML_CHARS:
        raise MopsBuybackError("t35sc09 HTML missing or exceeds safety limit")
    parser = _TableCollector()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # HTMLParser failures are not safe to partially accept
        raise MopsBuybackError(f"t35sc09 HTML parse failed: {exc}") from exc

    report_date = _report_date(html)
    if report_date is None:
        raise MopsBuybackError("t35sc09 report date is missing or invalid")
    rows: list[BuybackRow] = []
    seen: set[str] = set()
    found_data = False
    for table in parser.tables:
        for raw_row in table:
            if not _is_data_row(raw_row):
                continue  # headers and repeated header rows
            found_data = True
            dto = _row_to_dto(raw_row, market, report_date)
            if dto.plan_id not in seen:  # MOPS frequently repeats a bordered table
                rows.append(dto)
                seen.add(dto.plan_id)
    if not found_data or not rows:
        raise MopsBuybackError("t35sc09 contains no valid 20-column data table")
    return rows


def _roc_date(iso_day: str) -> str:
    try:
        parsed = date.fromisoformat(iso_day)
    except ValueError as exc:
        raise ValueError("dates must be ISO YYYY-MM-DD") from exc
    return f"{parsed.year - 1911:03d}{parsed.month:02d}{parsed.day:02d}"


def _validated_old_url(value: object) -> str:
    if not isinstance(value, str):
        raise MopsBuybackError("MOPS redirect missing result.url")
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
        raise MopsBuybackError("MOPS redirect URL is not an approved official HTTPS host")
    return value


def fetch_buybacks(date_from: str, date_to: str, market: str, *, session=None) -> list[BuybackRow]:
    """Fetch one market through the verified redirect contract, then parse HTML."""
    if market not in {"twse", "tpex"}:
        raise ValueError("market must be twse or tpex")
    start_roc, end_roc = _roc_date(date_from), _roc_date(date_to)
    client = session or requests.Session()
    payload = {
        "apiName": "ajax_t35sc09",
        "parameters": {
            "TYPEK": "sii" if market == "twse" else "otc",
            "d1": start_roc, "d2": end_roc, "RD": "1", "encodeURIComponent": "1",
            "step": "1", "firstin": "1", "off": "1",
        },
    }
    try:
        response = client.post(REDIRECT_URL, json=payload, headers=_REQUEST_HEADERS, timeout=config.HTTP_TIMEOUT)
        if response.status_code != 200:
            raise MopsBuybackError(f"MOPS redirect HTTP {response.status_code}")
        body = response.json()
        if body.get("code") != 200:
            raise MopsBuybackError(f"MOPS redirect code {body.get('code')!r}")
        old_url = _validated_old_url((body.get("result") or {}).get("url"))
        html_response = client.get(old_url, headers=_REQUEST_HEADERS, timeout=config.HTTP_TIMEOUT)
        if html_response.status_code != 200:
            raise MopsBuybackError(f"MOPS result HTTP {html_response.status_code}")
        return parse_buybacks_html(html_response.text, market)
    except MopsBuybackError:
        raise
    except Exception as exc:  # requests/JSON errors must not become a partial import
        raise MopsBuybackError(f"MOPS t35sc09 request failed: {exc}") from exc
