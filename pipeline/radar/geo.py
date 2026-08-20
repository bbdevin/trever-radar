"""docs/27 G1:地址縣市/行政區抽取與分點名稱正規化(純函式,供匯入與之後 G2 共用)。"""
from __future__ import annotations

import re

CITIES = (
    "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣",
    "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣",
)
_CITY_RE = re.compile("^(" + "|".join(CITIES) + ")")
_DIST_RE = re.compile(r"^([\u4e00-\u9fff]{1,3}(?:區|鄉|鎮|市))")

# 園區地址常不含縣市(G0:2330=新竹科學園區力行六路8號)
_PARK_CITY = (
    (re.compile(r"新竹科學"), "新竹市"),
    (re.compile(r"南部科學|台南科學|南科"), "台南市"),
    (re.compile(r"中部科學|中科"), "台中市"),
    (re.compile(r"高雄科學|橋頭科學"), "高雄市"),
    (re.compile(r"屏東農業"), "屏東縣"),
)

_FOREIGN_RE = re.compile(
    r"美商|高盛|摩根|瑞銀|美林|花旗|野村|新加坡商|香港上海|瑞士信貸|德意志"
)


def fold_tai(s: str) -> str:
    return (s or "").replace("臺", "台")


def normalize_branch_name(name: str) -> str:
    """去空白/全形空白、台臺、各式連字號 → 與 branch_trades.branch_name join。"""
    s = fold_tai(name).strip()
    s = s.replace("\u3000", " ").replace("－", "-").replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", "", s)
    return s


def parse_city_district(address: str | None) -> tuple[str | None, str | None]:
    """回傳 (city, district)。抽不到縣市則兩者皆 None(G1 fail-safe:不判地緣)。"""
    if not address:
        return None, None
    raw = fold_tai(address).strip()
    prefixed = raw
    for pat, city in _PARK_CITY:
        if pat.search(raw) and not _CITY_RE.search(raw):
            prefixed = city + raw
            break
    m = _CITY_RE.search(prefixed)
    if not m:
        return None, None
    city = m.group(1)
    rest = prefixed[m.end():]
    d = _DIST_RE.match(rest)
    district = d.group(1) if d else None
    if district == "市":
        district = None
    return city, district


def classify_broker_kind(name: str, *, is_hq: bool = False) -> str:
    """branch / hq / foreign。總公司與外資進排除集(G2 不當地緣)。"""
    if is_hq:
        return "hq"
    key = normalize_branch_name(name)
    if _FOREIGN_RE.search(key):
        return "foreign"
    if "-" not in key:
        return "hq"
    return "branch"
