class NoDataError(Exception):
    """The exchange has not published this dataset for the requested date (yet)."""


def clean(s):
    """Normalize a cell: strip, drop thousand separators; None for placeholder values."""
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if s in ("", "--", "---", "----", "X", "除權息", "N/A"):
        return None
    return s


def to_float(s) -> float | None:
    s = clean(s)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s) -> int | None:
    f = to_float(s)
    return None if f is None else int(f)
