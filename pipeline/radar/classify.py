"""Security code classification for TWSE/TPEx daily quote tables."""

_WARRANT_SUFFIX_KIND = {
    "P": "put",
    "C": "bull",
    "B": "bear",
    "X": "bull_ext",
    "Y": "bear_ext",
}


def classify(code: str) -> str:
    """stock / etf / etn / warrant / other."""
    c = code.strip().upper()
    if len(c) == 4 and c.isdigit():
        return "stock"                      # 普通股(含 TDR)
    if len(c) == 6 and c[0] == "0" and c[1] in "345678":
        return "warrant"                    # 上市權證 03xxxx–08xxxx
    if len(c) == 6 and c[0] == "7" and c[1].isdigit():
        return "warrant"                    # 上櫃權證 7xxxxx
    if c.startswith("00"):
        return "etf"                        # 0050 / 00878 / 00679B / 00400A / 006201
    if len(c) == 6 and c.startswith("02"):
        return "etn"
    return "other"                          # 特別股、受益證券等


def warrant_kind(code: str) -> str:
    last = code.strip().upper()[-1]
    if last.isdigit():
        return "call"
    return _WARRANT_SUFFIX_KIND.get(last, "call")
