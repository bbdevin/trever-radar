"""Versioned, reviewable company-group mapping used only by JSON export (docs/37 D)."""
import json
import re
from datetime import date
from pathlib import Path


MAPPING_PATH = Path(__file__).with_name("data") / "company_groups.json"
REQUIRED_FIELDS = {
    "group_id", "group_name", "stock_id", "effective_from", "effective_to",
    "source", "source_updated_at", "observed_at",
}


def load_company_groups(path: Path = MAPPING_PATH) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("mappings"), list):
        raise ValueError("company_groups mapping must declare version=1 and a mappings array")
    return payload["mappings"]


def validate_company_groups(
    mappings: list[dict], known_stock_ids: set[str], *, allow_missing_stocks: bool = False
) -> None:
    """Reject unverifiable mappings before they can become frontend data."""
    if not mappings:
        raise ValueError("company_groups mapping must not be empty")
    seen: set[tuple[str, str]] = set()
    group_metadata: dict[str, tuple[str, str, str | None, str]] = {}
    for item in mappings:
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ValueError(f"company_groups mapping missing fields: {sorted(missing)}")
        group_id, stock_id = item["group_id"], item["stock_id"]
        if not isinstance(group_id, str) or not group_id.strip() or not isinstance(item["group_name"], str) or not item["group_name"].strip():
            raise ValueError("company_groups group_id and group_name must be non-empty strings")
        if not isinstance(stock_id, str) or not re.fullmatch(r"\d{4,6}", stock_id):
            raise ValueError("company_groups stock_id must be a 4-6 digit string")
        if stock_id not in known_stock_ids and not allow_missing_stocks:
            raise ValueError(f"company_groups references unknown stock_id: {stock_id}")
        pair = (group_id, stock_id)
        if pair in seen:
            raise ValueError(f"company_groups duplicates group/member pair: {group_id}/{stock_id}")
        seen.add(pair)
        for field in ("effective_from", "effective_to", "source_updated_at", "observed_at"):
            value = item[field]
            if field == "observed_at" and value is None:
                raise ValueError("company_groups observed_at must be a non-null ISO date")
            if value is not None:
                try:
                    date.fromisoformat(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"company_groups {field} must be ISO date or null") from exc
        if item["effective_from"] and item["effective_to"] and item["effective_from"] > item["effective_to"]:
            raise ValueError(f"company_groups invalid effective range: {group_id}/{stock_id}")
        if not isinstance(item["source"], str) or not item["source"].startswith("https://"):
            raise ValueError(f"company_groups source must be an https URL: {group_id}/{stock_id}")
        metadata = (item["group_name"], item["source"], item["source_updated_at"], item["observed_at"])
        if group_id in group_metadata and group_metadata[group_id] != metadata:
            raise ValueError(f"company_groups group metadata must be consistent: {group_id}")
        group_metadata[group_id] = metadata


def is_effective(item: dict, as_of: str) -> bool:
    return item["observed_at"] <= as_of and (
        not item["effective_from"] or item["effective_from"] <= as_of
    ) and (
        not item["effective_to"] or item["effective_to"] >= as_of
    )
