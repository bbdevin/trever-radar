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


def _script(args, fn="minutes_until_quiet_window"):
    return (
        f'source "{LIB_FOR_BASH}"\n'
        f'{fn} {args}\n'
    )


def _run(args="", fn="minutes_until_quiet_window"):
    return subprocess.run(
        [BASH, "-c", _script(args, fn)], capture_output=True, text=True, timeout=120,
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


def _minutes(fn, dow=None, hhmm=None):
    proc = _run("" if dow is None else f"{int(dow)} {int(hhmm)}", fn)
    assert proc.returncode == 0, f"shell call failed: {proc.stderr}"
    out = proc.stdout.strip()
    assert out.isdigit(), f"expected a whole number of minutes, got {out!r} ({proc.stderr})"
    return int(out)


def minutes_until(dow=None, hhmm=None):
    return _minutes("minutes_until_quiet_window", dow, hhmm)


def minutes_until_writer(dow=None, hhmm=None):
    return _minutes("minutes_until_next_scheduled_writer", dow, hhmm)


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
        # 03:20 已出 mid 區間,下一個是 09:00 → (9*60) - (3*60+20) = 340
        self.assertEqual(minutes_until_writer(1, 320), 340)

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

    def test_mid_publish_applies_on_weekends_too(self):
        # crontab 是 `0 3,9,12,20 * * *`——每天,與 dow 無關。
        # 週六 08:00 只問安靜窗要等到週日 00:55(1015 分),但 09:00 那輪先到。
        self.assertEqual(minutes_until(6, 800), 1015)
        self.assertEqual(minutes_until_writer(6, 800), 60)


class DriverSanityTest(unittest.TestCase):
    def test_bash_is_available_or_we_are_on_a_host_without_it(self):
        # 這條的用意是:若某天 CI 換了環境讓 bash 不見,上面整組會被 skip 而靜默
        # 通過;至少在非 Windows 的 POSIX 主機上要求 bash 一定在。
        if os.name != "nt":
            self.assertTrue(BASH_OK, "bash must be available on a POSIX host")


if __name__ == "__main__":
    unittest.main()
