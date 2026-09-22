"""TAIFEX 結算日曆(docs/38 §2 R4)。

這支測試**完全不碰資料庫**,期望值全是從月曆手算出來、寫死在檔案裡的日期。
這正是把「第三個星期三」(純算術)與「順延／前 3 個市場日」(需要日曆)拆開的
理由:日曆是參數,測試自己造一本,於是每一條規則都在固定日期上問得出口。

fixture 用的假日是**為了測試而發明的**,不代表任何一年的真實休市表;測的是
「遇到連假時窗口會不會往前跨過去」這個行為,不是哪一天放假。
"""
import unittest
from datetime import date, timedelta

from radar.compute.settlement_calendar import (
    EXCLUSION_MARKET_DAYS_BEFORE,
    settlement_date,
    settlement_exclusion_days,
    settlement_exclusion_set,
    settlement_is_determinable,
    third_wednesday,
)


def _weekday_calendar(
    start: date, end: date, holidays: tuple[str, ...] = (),
) -> list[str]:
    """週一至週五扣掉 ``holidays`` 的日期串,遞增排序。"""
    days: list[str] = []
    current = start
    while current <= end:
        iso = current.isoformat()
        if current.weekday() < 5 and iso not in holidays:
            days.append(iso)
        current += timedelta(days=1)
    return days


class ThirdWednesdayTests(unittest.TestCase):
    """純月曆算術:沒有日曆參數,沒有資料庫,只有手算的日期。"""

    def test_third_wednesday_of_hand_checked_months(self):
        self.assertEqual(third_wednesday(2026, 1), date(2026, 1, 21))
        self.assertEqual(third_wednesday(2026, 2), date(2026, 2, 18))
        self.assertEqual(third_wednesday(2026, 4), date(2026, 4, 15))
        self.assertEqual(third_wednesday(2026, 9), date(2026, 9, 16))
        self.assertEqual(third_wednesday(2026, 12), date(2026, 12, 16))
        self.assertEqual(third_wednesday(2027, 1), date(2027, 1, 20))

    def test_a_month_whose_first_day_is_itself_a_wednesday(self):
        # 2026-04-01 是星期三,所以第一個星期三就是 1 號,第三個是 15 號——
        # 「第一個星期三 = 1 + (2 - weekday) % 7」這條式子的邊界。
        self.assertEqual(date(2026, 4, 1).weekday(), 2)
        self.assertEqual(third_wednesday(2026, 4), date(2026, 4, 15))

    def test_every_month_has_one_and_it_is_always_a_wednesday(self):
        # R4 明文:**每個月都有結算日,不只季月**。
        for month in range(1, 13):
            with self.subTest(month=month):
                day = third_wednesday(2026, month)
                self.assertEqual(day.weekday(), 2)
                self.assertEqual(day.month, month)
                self.assertTrue(15 <= day.day <= 21)


class SettlementDateTests(unittest.TestCase):
    def test_normal_month_settles_on_the_third_wednesday_itself(self):
        days = _weekday_calendar(date(2025, 12, 1), date(2026, 3, 31))
        self.assertEqual(
            settlement_date(year=2026, month=1, market_days=days), "2026-01-21",
        )

    def test_a_closed_third_wednesday_rolls_forward_one_market_day(self):
        days = _weekday_calendar(
            date(2026, 3, 1), date(2026, 5, 31), holidays=("2026-04-15",),
        )
        self.assertNotIn("2026-04-15", days)
        self.assertEqual(
            settlement_date(year=2026, month=4, market_days=days), "2026-04-16",
        )

    def test_a_multi_day_holiday_rolls_forward_across_the_whole_break(self):
        # 2026-02-18(第三個星期三)落在一段發明出來的五天連假裡,次一市場日是
        # 再下一個星期一 2026-02-23。順延永遠往後,不會退回連假之前。
        days = _weekday_calendar(
            date(2026, 1, 1), date(2026, 3, 31),
            holidays=("2026-02-16", "2026-02-17", "2026-02-18",
                      "2026-02-19", "2026-02-20"),
        )
        self.assertEqual(
            settlement_date(year=2026, month=2, market_days=days), "2026-02-23",
        )

    def test_a_calendar_that_stops_before_the_nominal_day_answers_none(self):
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 1, 9))
        self.assertIsNone(settlement_date(year=2026, month=1, market_days=days))
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=1, market_days=days), [],
        )

    def test_a_month_entirely_before_the_calendar_answers_none_not_day_one(self):
        # 日曆自 2026-01-05 起。2025-12 的結算日是 2025-12-17,不在這本日曆上;
        # 「順延至次一市場日」若照字面套用,會把它推成 2026-01-05,憑空替一個
        # 本模組根本不認識的月份造出一個結算日,並把開頭那天誤排除。
        days = _weekday_calendar(date(2026, 1, 5), date(2026, 3, 31))
        self.assertEqual(third_wednesday(2025, 12), date(2025, 12, 17))
        self.assertIsNone(settlement_date(year=2025, month=12, market_days=days))
        self.assertNotIn(
            "2026-01-05",
            settlement_exclusion_set(
                date_from="2026-01-05", date_to="2026-03-31", market_days=days,
            ),
        )

    def test_an_empty_calendar_answers_none(self):
        self.assertIsNone(settlement_date(year=2026, month=1, market_days=[]))
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=1, market_days=[]), [],
        )


class ExclusionDaysTests(unittest.TestCase):
    def test_a_normal_week_gives_friday_monday_tuesday_and_wednesday(self):
        days = _weekday_calendar(date(2025, 12, 1), date(2026, 3, 31))
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=1, market_days=days),
            ["2026-01-16", "2026-01-19", "2026-01-20", "2026-01-21"],
        )

    def test_exclusion_days_after_a_one_day_roll_forward(self):
        days = _weekday_calendar(
            date(2026, 3, 1), date(2026, 5, 31), holidays=("2026-04-15",),
        )
        # 結算日順延到 04-16(四),其前 3 個市場日仍是 04-10(五)、04-13(一)、
        # 04-14(二)——04-15 放假,不算市場日,所以窗口往前多跨一天。
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=4, market_days=days),
            ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-16"],
        )

    def test_the_three_preceding_market_days_cross_a_multi_day_holiday(self):
        days = _weekday_calendar(
            date(2026, 1, 1), date(2026, 3, 31),
            holidays=("2026-02-16", "2026-02-17", "2026-02-18",
                      "2026-02-19", "2026-02-20"),
        )
        # 結算日 02-23(一);其前 3 個市場日要跨過整段連假,落到 02-11、02-12、
        # 02-13。用日曆天回推會錯得很安靜(會給出放假中的 02-20、02-19、02-18)。
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=2, market_days=days),
            ["2026-02-11", "2026-02-12", "2026-02-13", "2026-02-23"],
        )

    def test_december_and_january_boundaries(self):
        days = _weekday_calendar(date(2026, 11, 1), date(2027, 2, 28))
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=12, market_days=days),
            ["2026-12-11", "2026-12-14", "2026-12-15", "2026-12-16"],
        )
        self.assertEqual(
            settlement_exclusion_days(year=2027, month=1, market_days=days),
            ["2027-01-15", "2027-01-18", "2027-01-19", "2027-01-20"],
        )

    def test_a_calendar_front_edge_shorter_than_three_days_gives_what_exists(self):
        days = _weekday_calendar(date(2026, 1, 20), date(2026, 1, 31))
        self.assertEqual(
            settlement_exclusion_days(year=2026, month=1, market_days=days),
            ["2026-01-20", "2026-01-21"],
        )

    def test_exclusion_days_are_one_settlement_plus_three(self):
        days = _weekday_calendar(date(2025, 12, 1), date(2026, 12, 31))
        for month in range(1, 13):
            with self.subTest(month=month):
                excluded = settlement_exclusion_days(
                    year=2026, month=month, market_days=days,
                )
                self.assertEqual(len(excluded), EXCLUSION_MARKET_DAYS_BEFORE + 1)
                self.assertEqual(excluded, sorted(excluded))
                self.assertTrue(set(excluded).issubset(days))


class ExclusionSetTests(unittest.TestCase):
    def test_the_set_spans_the_year_boundary_and_covers_every_month(self):
        days = _weekday_calendar(date(2026, 10, 1), date(2027, 3, 31))
        excluded = settlement_exclusion_set(
            date_from="2026-12-01", date_to="2027-01-31", market_days=days,
        )
        for day in ("2026-12-11", "2026-12-14", "2026-12-15", "2026-12-16",
                    "2027-01-15", "2027-01-18", "2027-01-19", "2027-01-20"):
            self.assertIn(day, excluded)

    def test_a_window_inside_one_month_still_sees_its_neighbours(self):
        # 區間首日可能落在**上個月**排除窗口的中間,所以前後各多算一個月。
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 4, 30))
        excluded = settlement_exclusion_set(
            date_from="2026-02-20", date_to="2026-02-25", market_days=days,
        )
        self.assertIn("2026-02-18", excluded)   # 該月本身
        self.assertIn("2026-01-21", excluded)   # 前一個月
        self.assertIn("2026-03-18", excluded)   # 後一個月

    def test_reversed_range_is_empty_not_an_error(self):
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 3, 31))
        self.assertEqual(
            settlement_exclusion_set(
                date_from="2026-03-01", date_to="2026-01-01", market_days=days,
            ),
            set(),
        )


class DeterminabilityTests(unittest.TestCase):
    """「這本日曆答得出候選日的 R4 窗口嗎」(docs/38 §7.13)。

    battery 帶著事後日曆跑,任何一天的下個結算日都已經在日曆裡,所以這個問題
    在檢定裡永遠是「答得出來」。export 永遠坐在日曆的尾巴上,它會答不出來,
    而舊行為把「答不出來」當成「沒有被排除」——上線的規則因此在日曆邊緣比
    被檢定過的規則寬鬆。這裡把那條界線鎖住:**答不出來就不主張**。
    """

    def test_a_calendar_that_reaches_the_settlement_answers_yes(self):
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 6, 30))
        self.assertTrue(settlement_is_determinable(
            candidate="2026-06-15", market_days=days))

    def test_the_three_market_days_before_an_unreachable_settlement_answer_no(self):
        # 六月結算日 06-17;日曆只到 06-16,所以 06-15 到底該不該排除是答不出來的。
        # 舊行為在這裡回「沒有被排除」,於是 06-15 可以上榜——而帶著日曆重跑,
        # 它是排除窗口裡的一天。
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 6, 16))
        self.assertIsNone(settlement_date(year=2026, month=6, market_days=days))
        for candidate in ("2026-06-12", "2026-06-15", "2026-06-16"):
            self.assertFalse(
                settlement_is_determinable(candidate=candidate, market_days=days),
                candidate,
            )

    def test_a_candidate_far_enough_from_the_nominal_day_answers_yes(self):
        """月初的候選日不受影響:名目結算日還很遠,遠到不可能在它的窗口裡。

        這條是這個函式的整個難點。若把「定位不到結算日」一律當成不可判定,
        每個月從 1 號到第三個星期三的每一天都會停止主張——整整半個月的功能
        因為一條保守規則而消失,那不是保守,那是關掉。
        """
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 6, 5))
        self.assertIsNone(settlement_date(year=2026, month=6, market_days=days))
        self.assertTrue(settlement_is_determinable(
            candidate="2026-06-05", market_days=days))

    def test_the_boundary_is_exactly_the_exclusion_width(self):
        """邊界剛好落在 R4 的那個 3:排除窗口的第一天開始答不出來,前一天還答得出來。

        06-17 是名目結算日,它之前的三個市場日 06-12 / 15 / 16 就是排除窗口的
        另外三天。所以候選日 06-11 與結算日之間有 3 個市場日 → 它不可能在窗口裡,
        答得出來;06-12 之間只剩 2 個 → 它就是窗口裡那一天,而日曆答不出來。
        """
        days = _weekday_calendar(date(2026, 1, 1), date(2026, 6, 11))
        self.assertTrue(settlement_is_determinable(
            candidate="2026-06-11", market_days=days))
        days_later = _weekday_calendar(date(2026, 1, 1), date(2026, 6, 12))
        self.assertFalse(settlement_is_determinable(
            candidate="2026-06-12", market_days=days_later))
        self.assertEqual(EXCLUSION_MARKET_DAYS_BEFORE, 3)

    def test_a_candidate_the_calendar_does_not_cover_answers_no(self):
        """名目日不在候選日之後、卻仍定位不到結算日 = 這本日曆不涵蓋那一段。"""
        days = _weekday_calendar(date(2026, 8, 1), date(2026, 8, 31))
        self.assertFalse(settlement_is_determinable(
            candidate="2026-06-19", market_days=days))
        self.assertFalse(settlement_is_determinable(
            candidate="2026-06-19", market_days=[]))


if __name__ == "__main__":
    unittest.main()
