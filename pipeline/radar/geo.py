"""docs/27 G1:地址縣市/行政區抽取與分點名稱正規化(純函式,供匯入與之後 G2 共用)。"""
from __future__ import annotations

import html
import re
import unicodedata

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


# 開頭郵遞區號:'71001'、'(104)'、'320 '、'(806011)'、全形括號
_POSTAL_RE = re.compile(r"^[(（]?\s*(\d{3,6})\s*[)）]?\s*")
_COUNTRY_RE = re.compile(r"^(?:中華民國)?(?:台灣省?)?")
_INNER_POSTAL_RE = re.compile(r"^\d{3,6}(?![\d號之巷弄樓-])")  # '台北市104中山區…';'台北市104號' 是門牌
_ANY_CITY_RE = re.compile("|".join(CITIES))

# 2010 縣市合併前的舊縣:後接鄉鎮市 → 新直轄市 + 區(新市鄉→新市區,故名稱至少取 2 字)
_OLD_COUNTY_RE = re.compile(
    r"^(台北|台中|台南|高雄|桃園)縣(?:([一-鿿]{2,3}?)(?:市|鎮|鄉))?"
)
_OLD_COUNTY_CITY = {
    "台北": "新北市", "台中": "台中市", "台南": "台南市", "高雄": "高雄市", "桃園": "桃園市",
}

# 縣轄市省略縣名('彰化市中山路…')。新竹市/嘉義市/基隆市本身是市,已在 CITIES,不在此表。
_COUNTY_SEAT = {
    "彰化市": "彰化縣", "員林市": "彰化縣",
    "南投市": "南投縣",
    "苗栗市": "苗栗縣", "頭份市": "苗栗縣",
    "屏東市": "屏東縣",
    "宜蘭市": "宜蘭縣",
    "台東市": "台東縣",
    "花蓮市": "花蓮縣",
    "斗六市": "雲林縣",
    "太保市": "嘉義縣", "朴子市": "嘉義縣",
    "竹北市": "新竹縣",
    "馬公市": "澎湖縣",
}

# 簡寫:'北市南京東路…'、'南市東區…'(僅限開頭,且後面不是「市」)
_ABBR_RE = re.compile(r"^(北|南)市(?!市)")
_ABBR_CITY = {"北": "台北市", "南": "台南市"}

# 雙北 3 碼郵遞區號 → 區(文字未寫區時補;郵遞區號所屬市須與抽到的市一致)
_POSTAL_DISTRICT = {
    "台北市": {
        "100": "中正區", "103": "大同區", "104": "中山區", "105": "松山區",
        "106": "大安區", "108": "萬華區", "110": "信義區", "111": "士林區",
        "112": "北投區", "114": "內湖區", "115": "南港區", "116": "文山區",
    },
    "新北市": {
        "207": "萬里區", "208": "金山區", "220": "板橋區", "221": "汐止區",
        "222": "深坑區", "223": "石碇區", "224": "瑞芳區", "226": "平溪區",
        "227": "雙溪區", "228": "貢寮區", "231": "新店區", "232": "坪林區",
        "233": "烏來區", "234": "永和區", "235": "中和區", "236": "土城區",
        "237": "三峽區", "238": "樹林區", "239": "鶯歌區", "241": "三重區",
        "242": "新莊區", "243": "泰山區", "244": "林口區", "247": "蘆洲區",
        "248": "五股區", "249": "八里區", "251": "淡水區", "252": "三芝區",
        "253": "石門區",
    },
}


def _normalize_address(address: str) -> tuple[str, str | None]:
    """台臺/巿市/空白正規化、剝郵遞區號與國名,舊縣與簡寫改寫成現行縣市。回傳 (地址, 3 碼郵遞區號)。"""
    s = fold_tai(address).replace("巿", "市")
    s = re.sub(r"[\s　]+", " ", s).strip()
    postal = None
    m = _POSTAL_RE.match(s)
    if m:
        postal = m.group(1)[:3]
        s = s[m.end():]
    s = _COUNTRY_RE.sub("", s).strip()
    m = _POSTAL_RE.match(s)  # '台灣 104台北市…'
    if m and postal is None:
        postal = m.group(1)[:3]
        s = s[m.end():]
    s = s.replace(" ", "")

    m = _OLD_COUNTY_RE.match(s)
    if m:
        town = m.group(2)
        s = _OLD_COUNTY_CITY[m.group(1)] + (town + "區" if town else "") + s[m.end():]
        return s, postal
    m = _ABBR_RE.match(s)
    if m:
        return _ABBR_CITY[m.group(1)] + s[m.end():], postal
    for seat, county in _COUNTY_SEAT.items():
        if s.startswith(seat):
            return county + s, postal
    return s, postal


def parse_city_district(address: str | None) -> tuple[str | None, str | None]:
    """回傳 (city, district)。抽不到縣市則兩者皆 None(G1 fail-safe:不判地緣)。"""
    if not address:
        return None, None
    raw, postal = _normalize_address(address)
    prefixed = raw
    for pat, city in _PARK_CITY:
        if pat.search(raw) and not _CITY_RE.search(raw):
            # 園區名後面若另寫縣市('新竹科學園區苗栗縣竹南鎮…'),以寫明的縣市為準
            later = _ANY_CITY_RE.search(raw)
            prefixed = raw[later.start():] if later else city + raw
            break
    m = _CITY_RE.search(prefixed)
    if not m:
        return None, None
    city = m.group(1)
    rest = prefixed[m.end():]
    pm = _INNER_POSTAL_RE.match(rest)
    if pm:
        postal = postal or pm.group(0)[:3]
        rest = rest[pm.end():]
    d = _DIST_RE.match(rest)
    district = d.group(1) if d else None
    if district == "市":
        district = None
    if district is None and postal:
        district = _POSTAL_DISTRICT.get(city, {}).get(postal)
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


# ---- 股代(docs/37 §3.1):公司登記的「股票過戶機構」是哪家券商 ----
# 官方欄位是自由文字,2026-10-04 實抓 1,987 家有 190 多種寫法:「元大證券股份有限公司」
# 「元大證券(股)公司股務代理部」「台新綜合證&#21173;股務代理部」「褔邦證券」「凱碁證券」……
# 只收「證券」字樣的機構;銀行代理部(中國信託商業銀行代理部等)與公司自辦一律不標。
_AGENT_TEXT_FIXES = (
    ("證劵", "證券"), ("証", "證"), ("褔邦", "福邦"), ("凱碁", "凱基"),
)
_AGENT_BANK_RE = re.compile(r"銀行|商銀|中信銀")
_CJK_NAME_RE = re.compile(r"[一-鿿]{2,6}")

# 同一家券商的簡寫 → 分點名稱裡總公司席位的名字(TWSE brokerList 簡稱:元大、凱基、
# 群益金鼎、永豐金、第一金、華南永昌、中國信託…)。股代欄與分點名兩邊都套用。
# 只寫名字不同的;每一筆只指向一家券商、一個總公司席位。
#   股代欄常寫「群益證券」「永豐證券」「第一證券」「華南證券」,省略「金鼎」「金」「永昌」。
#   中國信託綜合證券的簡稱是「中信」(json_export._ISSUER_TO_BROKER 同一筆:權證簡稱
#   「中信」對分點前綴「中國信託」);中國信託「銀行」代理部另由 _AGENT_BANK_RE 排除。
BROKER_ALIASES: dict[str, str] = {
    "群益": "群益金鼎",
    "永豐": "永豐金",
    "第一": "第一金",
    "華南": "華南永昌",
    "中信": "中國信託",
}

# 已併入他家的舊券商 → 存續券商。**只套用在股代欄**(官方表若還寫舊名,現在的股代
# 就是存續券商);不套用在分點名:合併前「大華」總公司席位是另一家公司,不是股代。
# 每一筆要有公開合併紀錄;沒有把握的不列(fail closed,寧可不標)。
#   凱基:2011 併台証證券、2012 併大華證券(存續名凱基)。
#   元大:2012 與寶來證券合併為元大寶來證券,2014 更名元大證券。
#   群益金鼎:2012 群益證券與金鼎證券合併。
MERGED_BROKERS: dict[str, str] = {
    "台證": "凱基", "大華": "凱基",
    "寶來": "元大", "元大寶來": "元大",
    "金鼎": "群益金鼎",
}


def transfer_agent_broker(agent: str | None) -> str | None:
    """股票過戶機構 → 券商(= 分點名稱裡總公司席位的名字,例「元大」「群益金鼎」);不是券商回 None。

    'X證券…' 取「證券」前的字、去掉「綜合」、套 BROKER_ALIASES 與 MERGED_BROKERS;
    銀行代理部、公司自辦、沒有「證券」字樣一律 None(不猜)。
    """
    if not agent:
        return None
    s = unicodedata.normalize("NFKC", html.unescape(agent))
    s = fold_tai(re.sub(r"\s+", "", s))
    for bad, good in _AGENT_TEXT_FIXES:
        s = s.replace(bad, good)
    if _AGENT_BANK_RE.search(s):
        return None
    head, sep, _ = s.partition("證券")
    if not sep:
        return None
    head = re.sub(r"綜合$", "", head)
    if not _CJK_NAME_RE.fullmatch(head):
        return None
    head = MERGED_BROKERS.get(head, head)
    return BROKER_ALIASES.get(head, head)


def hq_seat_broker(branch_name: str) -> str | None:
    """分點名稱若是券商總公司席位,回傳券商(套 BROKER_ALIASES);分公司回 None。

    分點來源(Fubon/MoneyDJ 鏡像)的總公司席位就是不帶「-」的券商名,有時多「證券」二字:
    「凱基」「元大證券」「永豐金證券」「台新」(9B00;舊 9B17「台新-營業部」是另一個據點,
    已由 branch_names.RENAMES 併入)。「元大-南京」是分公司;「元大期貨」是期貨子公司,
    名字不同,不會被當成元大總公司。外資席位(美商高盛…)名字對不到股代券商,自然不會中。
    只套 BROKER_ALIASES(同一家的簡寫),不套 MERGED_BROKERS(合併前是別家公司)。
    """
    key = normalize_branch_name(re.sub(r"^\(.*?\)", "", (branch_name or "").strip()))
    if not key or "-" in key:
        return None
    key = key.replace("証", "證")
    if key.endswith("證券") and len(key) > 2:
        key = key[:-2]
    return BROKER_ALIASES.get(key, key)


def is_agent_seat(branch_name: str, broker: str | None) -> bool:
    """這個分點是不是股代券商的總公司席位。

    2026-10-04 使用者定案:只標總公司,不標分公司(例:中探針股代=凱基 → 只有「凱基」標股代,
    「凱基-松山」不標)。整段名稱相等才算,所以元大≠元富、國泰≠國票、富邦≠福邦。
    """
    return bool(broker) and hq_seat_broker(branch_name) == broker


