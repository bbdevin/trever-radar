"""`minutes_until_quiet_window` 必須答對「距離下一輪排程還有多久」。

2026-09-03 事故的根因是守衛問錯問題:`in_radar_quiet_window` 只回答「現在在不在
窗內」,於是長工作改用絕對時刻上界(「17:00 以前都可以開跑」)當守衛,結果在
17:38 開了一個 20 分鐘的塊,兩分鐘後 17:40 的分點輪就撞上來。正確的守衛是
「剩餘時間 > 預估耗時」,而它需要一個能算出剩餘時間的函式。

本檔**直接呼叫 shell 函式本人**(`bash -c 'source lib.sh; minutes_until_quiet_window …'`),
不在 Python 這邊重寫一份窗口邏輯——重寫一份就等於製造第二個會漂移的副本,
那正是 `test_cron_quiet_window.py` 特地用 regex 解析原始碼要避免的事。

期望值全部是從 `lib.sh` 目前的範圍手算出來的,並在註解裡寫明算式,這樣範圍一旦
改動,失敗訊息就能直接告訴讀者「窗改了,順便檢查這些期望值」。
"""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


def _lib_path_for_bash():
    """`lib.sh` 在該 bash 眼中的路徑。

    Windows 上 PATH 的 `bash` 是 WSL 啟動器:它看不懂 `d:\\...`,而且實測
    (2026-09-04)它不會把 `bash -c <script> <name> <args>` 的位置參數傳進去,
    所以路徑與參數都必須直接內嵌進 script 文字裡,不能靠 `$1`。
    """
    if os.name == "nt":
        drive, rest = os.path.splitdrive(str(REPO_ROOT))
        return "/mnt/" + drive[0].lower() + rest.replace("\\", "/") + "/vps/scripts/lib.sh"
    return str(REPO_ROOT / "vps" / "scripts" / "lib.sh")


LIB_FOR_BASH = _lib_path_for_bash()


def _script(args, fn="minutes_until_quiet_window", env=None):
    # env 以「呼叫前綴」的形式內嵌(`VAR=… fn args`),和 adjust-incremental.sh 呼叫
    # 時一模一樣;理由同上:WSL 啟動器不保證把 Python 端的環境帶進去。
    prefix = "".join(f'{k}="{v}" ' for k, v in (env or {}).items())
    return (
        f'source "{LIB_FOR_BASH}"\n'
        f'{prefix}{fn} {args}\n'
    )


def _run(args="", fn="minutes_until_quiet_window", env=None):
    return subprocess.run(
        [BASH, "-c", _script(args, fn, env)], capture_output=True, text=True, timeout=120,
    )


def _bash_available():
    if not BASH:
        return False
    try:
        proc = _run()
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and proc.stdout.strip().isdigit()


BASH_OK = _bash_available()


def _minutes(fn, dow=None, hhmm=None, dom=None, env=None):
    if dow is None:
        args = ""
    elif dom is None:
        args = f"{int(dow)} {int(hhmm)}"
    else:
        args = f"{int(dow)} {int(hhmm)} {int(dom)}"
    proc = _run(args, fn, env)
    assert proc.returncode == 0, f"shell call failed: {proc.stderr}"
    out = proc.stdout.strip()
    assert out.isdigit(), f"expected a whole number of minutes, got {out!r} ({proc.stderr})"
    return int(out)


def minutes_until(dow=None, hhmm=None):
    return _minutes("minutes_until_quiet_window", dow, hhmm)


def minutes_until_writer(dow=None, hhmm=None, dom=None, env=None):
    return _minutes("minutes_until_next_scheduled_writer", dow, hhmm, dom, env)


@unittest.skipUnless(
    BASH_OK,
    "no usable bash (this test drives the real shell function; on Windows it needs WSL)",
)
class MinutesUntilQuietWindowTest(unittest.TestCase):
    # lib.sh 目前的範圍(HHMM,閉區間):
    #   平日 dow 1-5: 0055-0230, 1405-1545, 1605-1650, 1735-1930, 2115-2330
    #   週六 dow 6  : 0055-0230, 0450-0730
    #   週日 dow 7  : 0055-0400

    def test_inside_a_window_returns_zero(self):
        self.assertEqual(minutes_until(1, 1430), 0)   # 平日 14:30,在 1405-1545 內
        self.assertEqual(minutes_until(6, 500), 0)    # 週六 05:00,在 0450-0730 內
        self.assertEqual(minutes_until(7, 100), 0)    # 週日 01:00,在 0055-0400 內

    def test_window_boundaries_are_inclusive_at_both_ends(self):
        self.assertEqual(minutes_until(1, 1405), 0)
        self.assertEqual(minutes_until(1, 1545), 0)
        # 1546 已出窗,下一段 1605 → 19 分鐘
        self.assertEqual(minutes_until(1, 1546), 19)

    def test_shortly_before_a_window_returns_the_small_gap(self):
        self.assertEqual(minutes_until(1, 1400), 5)    # 14:00 → 14:05
        self.assertEqual(minutes_until(1, 1600), 5)    # 16:00 → 16:05(前一段 15:45 已結束)
        self.assertEqual(minutes_until(1, 1730), 5)    # 17:30 → 17:35
        # 這正是 2026-09-03 的情境:17:38 距離 17:40 只有 2 分鐘,絕對時刻上界
        # 看不出來,這個函式看得出來。
        self.assertEqual(minutes_until(1, 1733), 2)

    def test_the_long_weekday_gap_returns_a_large_number(self):
        # 平日 02:31(deep 輪剛結束)→ 14:05,唯一的長空檔:
        # 14*60+5 - (2*60+31) = 845 - 151 = 694
        self.assertEqual(minutes_until(1, 231), 694)
        # 這個空檔必須大到放得下一個有意義的塊(WARRANT_MAX_MINUTES 預設 240)。
        self.assertGreater(minutes_until(1, 231), 240)

    def test_rolls_across_midnight_into_the_same_kind_of_day(self):
        # 週一 23:40 → 週二 00:55:(1440-1420) + 55 = 75
        self.assertEqual(minutes_until(1, 2340), 75)

    def test_rolls_across_midnight_into_a_different_day_of_week(self):
        # 週五 23:40 → 週六 00:55(週六自己的第一段,數字剛好也是 55):75
        self.assertEqual(minutes_until(5, 2340), 75)
        # 週六 08:00 → 週六當天 07:30 之後沒有窗了,要滾到週日 00:55:
        # (1440-480) + 55 = 1015
        self.assertEqual(minutes_until(6, 800), 1015)
        # 週日 05:00 → 週日 04:00 之後沒有窗了,要滾到週一 00:55(平日那組範圍):
        # (1440-300) + 55 = 1195
        self.assertEqual(minutes_until(7, 500), 1195)

    def test_same_clock_time_answers_differently_per_day_of_week(self):
        # 04:00 這個時刻在三種日子的答案不同,證明它真的走的是各自的分支:
        self.assertEqual(minutes_until(7, 400), 0)     # 週日:窗尾就是 04:00,在窗內
        self.assertEqual(minutes_until(6, 400), 50)    # 週六:下一段 04:50
        self.assertEqual(minutes_until(1, 400), 605)   # 平日:要等到 14:05

    def test_never_exceeds_the_twenty_four_hour_scan_cap(self):
        for dow in range(1, 8):
            for hhmm in (0, 359, 800, 1200, 1959, 2359):
                with self.subTest(dow=dow, hhmm=hhmm):
                    self.assertLessEqual(minutes_until(dow, hhmm), 1440)

    def test_no_argument_form_uses_the_current_taipei_time(self):
        self.assertLessEqual(minutes_until(), 1440)


@unittest.skipUnless(
    BASH_OK,
    "no usable bash (this test drives the real shell function; on Windows it needs WSL)",
)
class MinutesUntilNextScheduledWriterTest(unittest.TestCase):
    """安靜窗不是排程的全部——mid-publish 的 03/09/12/20 四輪不在窗表裡。

    `quiet_window_at` 的註解自己寫著那四輪「由 mid flag 另擋」。用 flag 擋
    「不要同時開第二個 bf 寫者」是夠的,但擋不住相反方向的傷害:
    `mid-backfill-publish.sh` 開頭是 `fuser /tmp/radar-db.lock` → 略過,所以任何
    握著 DB 鎖跨過整點的長工作,都會讓那一輪靜默消失。只問安靜窗的守衛會允許
    02:31 開一個 240 分鐘的塊,一口氣吃掉 03:00 那輪。

    mid-publish 覆蓋區間取整點起 `MID_PUBLISH_RUN_MINUTES`(預設 20;實測耗時
    10:43–13:14 分)。
    """

    def test_mid_publish_slots_are_treated_as_scheduled_writers(self):
        # 03:00 起 20 分鐘內視為有寫入者在跑。
        self.assertEqual(minutes_until_writer(1, 300), 0)
        self.assertEqual(minutes_until_writer(1, 319), 0)
        # 03:20 已出 mid 區間。平日下一個是 08:00 的 morning-index(平日短輪,見下方
        # WeekdayShortJobsTest)→ (8*60) - (3*60+20) = 280。
        self.assertEqual(minutes_until_writer(1, 320), 280)
        # 週日沒有平日短輪:04:20(週日安靜窗 04:00 已結束)下一個就是 09:00 的 mid
        # → (9*60) - (4*60+20) = 280。
        self.assertEqual(minutes_until_writer(7, 420), 280)
        # 09:00 起 20 分鐘同樣在跑(平日、週日皆然)。
        self.assertEqual(minutes_until_writer(7, 900), 0)
        self.assertEqual(minutes_until_writer(7, 919), 0)

    def test_the_long_weekday_gap_is_cut_short_by_mid_publish(self):
        # 只問安靜窗:02:31 → 14:05 是 694 分鐘。
        self.assertEqual(minutes_until(1, 231), 694)
        # 問「下一個排程寫入者」:03:00 就到了,只剩 29 分鐘。
        # 這正是這個函式存在的理由——694 會讓守衛核准一個吃掉 03:00 那輪的塊。
        self.assertEqual(minutes_until_writer(1, 231), 29)

    def test_evening_gap_is_cut_short_by_the_20_00_round(self):
        # 只問安靜窗:19:31 → 21:15 是 104 分鐘。
        self.assertEqual(minutes_until(1, 1931), 104)
        # 實際上 20:00 那輪先到 → 29 分鐘。
        self.assertEqual(minutes_until_writer(1, 1931), 29)

    def test_never_later_than_the_quiet_window_answer(self):
        # 定義上它是兩者取先,所以任何時刻都不可能比只問安靜窗更晚。
        for dow in range(1, 8):
            for hhmm in (0, 231, 359, 800, 1200, 1331, 1931, 2359):
                with self.subTest(dow=dow, hhmm=hhmm):
                    self.assertLessEqual(
                        minutes_until_writer(dow, hhmm), minutes_until(dow, hhmm),
                        "加入 mid-publish 之後只可能更早,不可能更晚",
                    )

    def test_the_nightly_branch_stats_round_is_a_scheduled_writer(self):
        """2026-09-07 23:40 的實測反例:守衛回答 75,真正的答案是 25。

        `safe-branch-stats.sh` 是 `5 0 * * 2-6`,握著真鎖跑到約 01:35。它**不能**
        被加進 `quiet_window_at`——那會讓它判定自己在安靜窗裡而略過自己
        (2026-08-31 停擺的成因),`test_cron_quiet_window.py` 也直接斷言 cron
        時刻不得落在安靜窗內。所以它只存在於這層 overlay。
        """
        # 23:40 → 只問安靜窗是隔天 00:55(75 分);真正先到的是 00:05。
        self.assertEqual(minutes_until(1, 2340), 75)
        self.assertEqual(minutes_until_writer(1, 2340), 25)
        # 跨 day-of-week 也一樣(週五 23:40 → 週六 00:05)。
        self.assertEqual(minutes_until(5, 2340), 75)
        self.assertEqual(minutes_until_writer(5, 2340), 25)
        # 00:05–00:54 視為有寫入者在跑;00:55 起本來就已經在安靜窗裡。
        self.assertEqual(minutes_until_writer(3, 5), 0)
        self.assertEqual(minutes_until_writer(3, 30), 0)
        self.assertEqual(minutes_until_writer(3, 54), 0)
        self.assertEqual(minutes_until_writer(3, 55), 0)
        # 00:00 → 5 分鐘後開跑。
        self.assertEqual(minutes_until_writer(3, 0), 5)

    def test_monthly_directors_needs_a_day_of_month_and_only_fires_on_the_16th(self):
        """`0 7 16 * *` 是日期限定的,`<dow> <hhmm>` 這個簽章表達不了。

        因此掃描函式多吃一個可選的第三參數 <dom>。省略它 = 「無日期探測」,
        月排程一律不成立(而不是假裝每天都會發生);正式路徑不帶參數,
        會自己帶上台北當下的 day-of-month。
        """
        # 平日 06:00,無日期:下一個是 08:00 的 morning-index → 120 分。
        self.assertEqual(minutes_until_writer(1, 600), 120)
        # 同一時刻,但今天是 16 號:07:00 的董監輪先到 → 60 分。
        self.assertEqual(minutes_until_writer(1, 600, 16), 60)
        # 15 號沒有這一輪,答案回到 120。
        self.assertEqual(minutes_until_writer(1, 600, 15), 120)
        # 07:00–07:19 視為在跑;07:20 之後下一個是 08:00 → 40 分。
        self.assertEqual(minutes_until_writer(1, 700, 16), 0)
        self.assertEqual(minutes_until_writer(1, 719, 16), 0)
        self.assertEqual(minutes_until_writer(1, 720, 16), 40)
        # 它落在平日 02:31–14:05 那段唯一的長空檔裡,正是這個守衛最會核准長塊的地方。
        self.assertEqual(minutes_until_writer(1, 320, 16), 220)   # 03:20 → 07:00
        self.assertEqual(minutes_until_writer(1, 320), 280)       # 無日期:08:00
        # 週日沒有平日短輪,07:20 之後下一個仍是 09:00 → 100 分(董監這段不受平日短輪影響)。
        self.assertEqual(minutes_until_writer(7, 720, 16), 100)

    def test_mid_publish_applies_on_weekends_too(self):
        # crontab 是 `0 3,9,12,20 * * *`——每天,與 dow 無關。
        # 週六 08:00 只問安靜窗要等到週日 00:55(1015 分),但 09:00 那輪先到。
        self.assertEqual(minutes_until(6, 800), 1015)
        self.assertEqual(minutes_until_writer(6, 800), 60)


@unittest.skipUnless(
    BASH_OK,
    "no usable bash (this test drives the real shell function; on Windows it needs WSL)",
)
class WeekdayShortJobsTest(unittest.TestCase):
    """平日 08:00 morning-index 與 13:15 adjust-incremental 是排程寫入者(2026-10-15)。

    2026-10-14／15:warrant-backfill 06:36 開的塊握著 /tmp/radar-db.lock 跨過 08:00,
    morning-index 兩天都等鎖 300 s 逾時沒發布;10-14 的 13:15 adjust-incremental 也因
    鎖被占而略過。當時 overlay 不認得這兩輪。和 00:05 分點排行一樣,它們**只**加在
    overlay、不進 quiet_window_at(否則它們自己會判定在安靜窗裡;
    test_cron_quiet_window.py 直接斷言 cron 時刻不得落在安靜窗內)。

    warrant-backfill 在沒有 radar-bf-* 容器時會把 MID_PUBLISH_HOURS 清空(正式環境
    現況),所以這裡的「回補預算」情境都帶 MID_PUBLISH_HOURS="" 來量。
    """

    NO_MID = {"MID_PUBLISH_HOURS": ""}
    WARRANT_SAFETY = 15  # warrant-backfill.sh 的 WARRANT_SAFETY_MINUTES 預設

    def test_slots_are_scheduled_writers_on_weekdays(self):
        for dow in range(1, 6):
            with self.subTest(dow=dow):
                self.assertEqual(minutes_until_writer(dow, 800), 0)
                self.assertEqual(minutes_until_writer(dow, 845), 0)
                # 08:46 出槽,下一個是 09:00 的 mid → 14
                self.assertEqual(minutes_until_writer(dow, 846), 14)
                self.assertEqual(minutes_until_writer(dow, 1315), 0)
                self.assertEqual(minutes_until_writer(dow, 1335), 0)
                # 13:36 出槽,下一個是 14:05 的安靜窗 → 29
                self.assertEqual(minutes_until_writer(dow, 1336), 29)

    def test_quiet_window_itself_is_unchanged(self):
        # 只問安靜窗的函式不認得平日短輪(它們不能進 quiet_window_at)。
        self.assertEqual(minutes_until(1, 800), 365)    # 08:00 → 14:05
        self.assertEqual(minutes_until(1, 1315), 50)    # 13:15 → 14:05

    def test_weekday_06_36_chunk_ends_before_08_00(self):
        # 事故情境:平日 06:36,mid 已清空。舊版答 449(→ 14:05),預算封頂 240,
        # 塊一路握鎖到 10:36;新版答 84(→ 08:00)。
        until = minutes_until_writer(3, 636, env=self.NO_MID)
        self.assertEqual(until, 84)
        budget = until - self.WARRANT_SAFETY
        self.assertLessEqual(6 * 60 + 36 + budget, 8 * 60, "塊必須在 08:00 前收工")

    def test_weekday_12_20_chunk_ends_before_13_15(self):
        # 舊版答 105(→ 14:05),預算 90,塊握到 13:50 吃掉 13:15;新版答 55。
        until = minutes_until_writer(3, 1220, env=self.NO_MID)
        self.assertEqual(until, 55)
        self.assertLessEqual(12 * 60 + 20 + until - self.WARRANT_SAFETY, 13 * 60 + 15)

    def test_16_00_insti_and_20_45_margin_starts_are_writers(self):
        # 2026-10-21:cron 起點早於安靜窗(16:05、21:15)的兩輪補進 overlay,只補到窗起點。
        for dow in range(1, 6):
            with self.subTest(dow=dow):
                self.assertEqual(minutes_until_writer(dow, 1600, env=self.NO_MID), 0)
                self.assertEqual(minutes_until_writer(dow, 1604, env=self.NO_MID), 0)
                self.assertEqual(minutes_until_writer(dow, 2045, env=self.NO_MID), 0)
                self.assertEqual(minutes_until_writer(dow, 2114, env=self.NO_MID), 0)
                # 只問安靜窗的答案不變(quiet_window_at 沒動)。
                self.assertEqual(minutes_until(dow, 1600), 5)
                self.assertEqual(minutes_until(dow, 2045), 30)

    def test_weekday_19_55_chunk_ends_before_the_20_45_margin_round(self):
        # 2026-10-20 事故:19:55(mid 清空)舊版答 80(→ 21:15),預算 65,握鎖到 21:00,
        # 20:45 資券輪 21:02 才開工。新版答 50(→ 20:45),預算 35,20:30 收工。
        until = minutes_until_writer(2, 1955, env=self.NO_MID)
        self.assertEqual(until, 50)
        old = minutes_until_writer(
            2, 1955, env=dict(self.NO_MID, WEEKDAY_SHORT_JOBS="0800-0845 1315-1335"))
        self.assertEqual(old, 80)
        self.assertLessEqual(19 * 60 + 55 + until - self.WARRANT_SAFETY, 20 * 60 + 45)

    def test_weekday_15_40_is_inside_the_window_and_15_46_no_longer_gets_a_chunk(self):
        # 15:40 在 1405-1545 安靜窗內:warrant-backfill 先被 in_radar_quiet_window 擋,前後皆 0。
        self.assertEqual(minutes_until_writer(3, 1540, env=self.NO_MID), 0)
        # 15:46 出窗:舊版答 19(→ 16:05,預算 4,低於 MIN_CHUNK 20 已略過);
        # 新版答 14(→ 16:00)。行為一樣是略過,但答案對齊真正的 16:00 起點。
        self.assertEqual(minutes_until_writer(3, 1546, env=self.NO_MID), 14)
        old = minutes_until_writer(
            3, 1546, env=dict(self.NO_MID, WEEKDAY_SHORT_JOBS="0800-0845 1315-1335"))
        self.assertEqual(old, 19)

    def test_monday_11_00_refdata_is_a_writer_only_on_monday(self):
        # weekly-refdata `0 11 * * 1` 等鎖上限 30 分;週一 09:20(mid 清空)舊版答 235(→ 13:15),
        # 預算 220、握鎖到 13:00;新版答 100(→ 11:00),預算 85,10:45 收工。
        self.assertEqual(minutes_until_writer(1, 920, env=self.NO_MID), 100)
        self.assertEqual(minutes_until_writer(1, 1100, env=self.NO_MID), 0)
        self.assertEqual(minutes_until_writer(1, 1129, env=self.NO_MID), 0)
        # 11:30 出槽 → 13:15 adjust-incremental:105
        self.assertEqual(minutes_until_writer(1, 1130, env=self.NO_MID), 105)
        # 週二沒有這一輪:09:20 → 13:15 = 235
        self.assertEqual(minutes_until_writer(2, 920, env=self.NO_MID), 235)
        self.assertEqual(minutes_until(1, 1100), 185)  # 安靜窗表沒動:11:00 → 14:05

    def test_weekends_are_unaffected(self):
        # 週六 06:36 本來就在週六安靜窗 04:50–07:30 裡 → 0。
        self.assertEqual(minutes_until_writer(6, 636, env=self.NO_MID), 0)
        no_short = dict(self.NO_MID, WEEKDAY_SHORT_JOBS="")
        for dow in (6, 7):
            for hhmm in (636, 731, 800, 1100, 1200, 1315, 1600, 1955, 2045):
                with self.subTest(dow=dow, hhmm=hhmm):
                    self.assertEqual(
                        minutes_until_writer(dow, hhmm, env=self.NO_MID),
                        minutes_until_writer(dow, hhmm, env=no_short),
                    )
        # 週六 07:31 出安靜窗、mid 清空 → 一路到週日 00:05 的分點排行:(1440-451)+5 = 994
        self.assertEqual(minutes_until_writer(6, 731, env=self.NO_MID), 994)


_NON_DB_WRITERS = ("disk-cleanup.sh", "radar-worker", "bf-cron-guard.sh", "bf-supervisor.sh")


def _crontab_writer_starts():
    """crontab.example 每一條會寫 DB 的固定時刻排程 → [(dow, hhmm, dom, line)]。"""
    out = []
    text = (REPO_ROOT / "vps" / "scripts" / "crontab.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("@") or "=" in s.split()[0]:
            continue
        minute, hour, dom, _mon, dow = s.split()[:5]
        if any(n in s for n in _NON_DB_WRITERS) or not minute.isdigit():
            continue
        if dow == "*":
            dows = range(1, 8)
        elif "-" in dow:
            a, b = (int(x) for x in dow.split("-"))
            dows = range(a, b + 1)
        else:
            dows = [int(x) for x in dow.split(",")]
        for h in hour.split(","):
            for d in dows:
                out.append((7 if d == 0 else d, int(h) * 100 + int(minute),
                            int(dom) if dom.isdigit() else None, s))
    return out


@unittest.skipUnless(
    BASH_OK,
    "no usable bash (this test drives the real shell function; on Windows it needs WSL)",
)
class EveryCrontabWriterIsKnownTest(unittest.TestCase):
    """crontab.example 每條會寫 DB 的排程,起點那一分鐘都必須被 overlay ∪ 安靜窗認得。

    2026-10-20:20:45 daily-margin 起點早於 21:15 安靜窗、overlay 也沒有,warrant-backfill
    19:55 的塊握鎖到 21:00,資券輪晚 17 分。新增排程輪而忘了加 overlay,這條會失敗。
    """

    def test_every_writer_start_is_a_scheduled_writer_minute(self):
        starts = _crontab_writer_starts()
        self.assertGreater(len(starts), 10)
        for dow, hhmm, dom, line in starts:
            with self.subTest(dow=dow, hhmm=hhmm, line=line):
                args = {} if dom is None else {"dom": dom}
                self.assertEqual(minutes_until_writer(dow, hhmm, **args), 0)


class DriverSanityTest(unittest.TestCase):
    def test_bash_is_available_or_we_are_on_a_host_without_it(self):
        # 這條的用意是:若某天 CI 換了環境讓 bash 不見,上面整組會被 skip 而靜默
        # 通過;至少在非 Windows 的 POSIX 主機上要求 bash 一定在。
        if os.name != "nt":
            self.assertTrue(BASH_OK, "bash must be available on a POSIX host")


if __name__ == "__main__":
    unittest.main()
