"""TAIFEX 結算日曆(docs/38 §2 R4)。純算術與注入式日曆,這裡不碰資料庫。

為什麼是獨立模組
----------------
R4 要的東西有兩半,而兩半的依賴完全不同:

* **「該月第三個星期三」** 只需要一本月曆,任何時候、任何機器上都算得出同一個
  答案,不需要資料、不需要連線;
* **「若非市場日則順延」與「其前 3 個市場日」** 需要知道哪些日子是市場日,而
  市場日在本專案的定義是 ``daily_prices`` 裡出現過的日期。

把兩半寫在一起,就只剩下一個必須開資料庫才能執行的函式,連「第三個星期三算對了
沒有」都要準備一份 fixture 才問得出口。所以這裡把**日曆本身當成參數**傳進來:
呼叫端負責從 ``daily_prices`` 取出那串日期,本模組只負責在那串日期上做算術。
單元測試因此用的是手算出來的固定日期,一列資料都不需要。

日曆參數
--------
``market_days`` 是**遞增排序、無重複**的 ``YYYY-MM-DD`` 字串序列。ISO 日期的字典
序與時間序一致,所以這裡一路用字串比較與 :mod:`bisect`,不做 parse。
"""
from __future__ import annotations

from bisect import bisect_left
from calendar import WEDNESDAY
from datetime import date as date_cls, timedelta
from typing import Sequence

# R4:結算日本身 + 其前 3 個市場日。3 是 docs/38 §2 R4 事前訂下的取捨(排太少
# 漏掉轉倉高峰 vs 每月排掉四分之一交易日),不是推導出來的,也不得事後調整。
EXCLUSION_MARKET_DAYS_BEFORE = 3

# 第三個星期三:第一個星期三 + 14 天。
_WEEKS_TO_THIRD = 2


def third_wednesday(year: int, month: int) -> date_cls:
    """該月第三個星期三。**純月曆算術**,與市場日、資料庫無關。

    這是結算日的「名目」日期;它有沒有開市是下一個函式的事。
    """
    first = date_cls(year, month, 1)
    first_wednesday = 1 + (WEDNESDAY - first.weekday()) % 7
    return date_cls(year, month, first_wednesday + 7 * _WEEKS_TO_THIRD)


def settlement_date(*, year: int, month: int, market_days: Sequence[str]) -> str | None:
    """該月結算日:第三個星期三,非市場日則**順延**至次一市場日(TAIFEX 規則)。

    回傳 ``None`` 代表這本日曆回答不了,有兩種情況,都**不外推**:名目日晚於日曆
    最後一天(問的是未來的月份),或名目日早於日曆第一天(那個月整個在日曆之前,
    順延規則會把它一路推到日曆開頭那天,憑空造出一個結算日)。沒有日曆就沒有答案。
    順延永遠往後,不會往前:第三個星期三放假時 TAIFEX 結算的是次一交易日。
    """
    nominal = third_wednesday(year, month).isoformat()
    if not market_days or nominal < market_days[0]:
        return None
    index = bisect_left(market_days, nominal)
    if index >= len(market_days):
        return None
    return market_days[index]


def settlement_exclusion_days(
    *, year: int, month: int, market_days: Sequence[str],
) -> list[str]:
    """該月的 R4 排除日:結算日 + 其前 ``3`` 個市場日,由舊到新。

    「市場日」不是日曆日:正常週給出的是週五、週一、週二 + 週三,遇到連假則往前
    跨過整段連假。日曆前緣不足 3 天時回傳能給的那幾天(排除集合少幾天只會讓更多
    日子有資格上榜,而那些日子本來就會被 R1 的 60 日歷史擋掉),**不補、不外推**。

    回傳空清單代表該月沒有結算日可定位(見 :func:`settlement_date`)。
    """
    settlement = settlement_date(year=year, month=month, market_days=market_days)
    if settlement is None:
        return []
    index = bisect_left(market_days, settlement)
    start = max(0, index - EXCLUSION_MARKET_DAYS_BEFORE)
    return list(market_days[start:index + 1])


def settlement_is_determinable(*, candidate: str, market_days: Sequence[str]) -> bool:
    """候選日的 R4 排除窗口**算得出來嗎**(docs/38 §7.13)。

    :func:`settlement_exclusion_days` 在定位不到結算日的時候回傳空清單,而空清單
    在集合聯集裡與「這個月沒有排除日」**看起來一模一樣**。battery 是帶著事後日曆
    跑的,任何一天的下個結算日都已經在日曆裡,所以那個塌陷在檢定裡永遠不會發生;
    export 永遠坐在日曆的尾巴上,它會發生,而且方向是**把該排除的日子放上榜**——
    上線的規則於是與被檢定過的規則在邊緣不同。

    這裡把那個塌陷變成一個問句:**答不出來就不要主張**(§7.13)。

    答得出來的兩種情形:

    * 該月的結算日落在已知日曆之內 → :func:`settlement_date` 給得出答案,窗口是
      完整的已知市場日,照 R4 判就好;
    * 名目日(第三個星期三)還在已知日曆之後,**但它離候選日夠遠**——遠到不論
      中間開不開市,候選日都不可能是結算日之前的 3 個市場日之一。

    「夠遠」怎麼數:已知日曆之內用真的市場日,已知日曆之後**把每一個平日當成
    市場日**。後者是一個外推,而且它可能錯——候選日與名目結算日之間若整段連假,
    真正的市場日會比平日少。那個錯誤的方向與**現在的行為完全相同**(把一個該排
    除的日子放行),所以這個函式在任何一天都不會比現況更差,而在正常的日曆上它
    把真正的邊緣案例(結算日前 1–3 個市場日)擋下來。用日曆日或月份去近似都不
    行:前者把整個月上半段誤判成不可判定,後者更甚。
    """
    day = date_cls.fromisoformat(candidate)
    if settlement_date(
        year=day.year, month=day.month, market_days=market_days,
    ) is not None:
        return True
    # 名目日不在候選日之後、卻還是定位不到結算日(例如名目日早於日曆第一天,
    # 或日曆是空的)→ 下面的區間是空的,天數 0,照樣答「不可判定」。不另寫一個
    # 分支:那個分支與這一行永遠給同一個答案,只會多一條沒有人測得到的路。
    nominal = third_wednesday(day.year, day.month).isoformat()
    return _trading_days_between(
        after=candidate, before=nominal, market_days=market_days,
    ) >= EXCLUSION_MARKET_DAYS_BEFORE


def _trading_days_between(
    *, after: str, before: str, market_days: Sequence[str],
) -> int:
    """``(after, before)`` 開區間內的市場日數;已知日曆之後的平日一律算一天。"""
    known = [day for day in market_days if after < day < before]
    count = len(known)
    tail = max(after, market_days[-1]) if market_days else after
    cursor = date_cls.fromisoformat(tail) + timedelta(days=1)
    end = date_cls.fromisoformat(before)
    while cursor < end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def settlement_exclusion_set(
    *, date_from: str, date_to: str, market_days: Sequence[str],
) -> set[str]:
    """``[date_from, date_to]`` 這段期間內每一個月的 R4 排除日聯集。

    **每個月都有結算日,不只季月**(R4 明文)。往前後各多取一個月,是因為一段期間
    的第一天可能落在上個月結算窗口的中間、最後一天同理;多算出來的日子落在區間外,
    由呼叫端自己的區間判斷吸收。
    """
    if date_from > date_to:
        return set()
    start = date_cls.fromisoformat(date_from)
    end = date_cls.fromisoformat(date_to)
    # 以「月序號」走訪,跨年就只是加一,不必在迴圈裡處理 12 → 1 的進位。
    first_index = 12 * start.year + (start.month - 1) - 1
    last_index = 12 * end.year + (end.month - 1) + 1
    excluded: set[str] = set()
    for index in range(first_index, last_index + 1):
        year, month = divmod(index, 12)
        excluded.update(
            settlement_exclusion_days(year=year, month=month + 1, market_days=market_days)
        )
    return excluded
