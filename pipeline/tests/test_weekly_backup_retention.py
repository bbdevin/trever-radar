"""週備份保留策略(vps/scripts/backup_retention.py)與腳本順序。

背景(2026-09-30):09-26 的週備份因使用者個人 Drive 配額滿而沒上傳,本機留著
那一週唯一的一份。舊腳本上傳之後才清舊檔(空間不夠時走不到),而刪檔進垃圾桶
照樣佔配額。fixture 的大小是發明的整數,答案可以手算。
"""
import importlib.util
import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "vps" / "scripts" / "weekly-backup.sh"
spec = importlib.util.spec_from_file_location(
    "backup_retention", REPO / "vps" / "scripts" / "backup_retention.py")
br = importlib.util.module_from_spec(spec)
spec.loader.exec_module(br)

GB = 1_000_000_000


def f(name, size=GB):
    return {"Name": name, "Size": size}


# 2026-09-30 正式 Drive 的形狀(大小取整)
DRIVE = [f("radar-20260926.db.gz"), f("radar-20260919.db.gz"), f("radar-20260912.db.gz"),
         f("radar-20260829.db.gz"), f("radar-20260725.db.gz")]


class PlanTests(unittest.TestCase):
    def test_new_snapshot_counts_as_one_of_the_two_weeklies(self):
        """10-03 上傳前:保留 09-26(最新既有週)+ 每月最新;09-12 與 09-19 同月,刪較舊的。"""
        victims, fits = br.plan(DRIVE, new_name="radar-20261003.db.gz", need=GB, free=2 * GB)
        self.assertEqual(victims, ["radar-20260912.db.gz"])
        self.assertTrue(fits)

    def test_room_is_made_from_the_oldest_monthly_first(self):
        victims, fits = br.plan(DRIVE, new_name="radar-20261003.db.gz",
                                need=3 * GB, free=GB)
        # 策略刪 09-12 → 2 GB;還差 → 刪最舊的月快照 07-25 → 3 GB,放得下。
        self.assertEqual(victims, ["radar-20260912.db.gz", "radar-20260725.db.gz"])
        self.assertTrue(fits)

    def test_the_newest_existing_weekly_is_never_deleted(self):
        victims, fits = br.plan(DRIVE, new_name="radar-20261003.db.gz",
                                need=100 * GB, free=0)
        self.assertNotIn("radar-20260926.db.gz", victims)
        self.assertFalse(fits)

    def test_if_it_cannot_fit_no_monthly_is_sacrificed_for_nothing(self):
        """刪光月快照也放不下 → 月快照一份都不刪(刪了也上傳不了)。"""
        victims, fits = br.plan(DRIVE, new_name="radar-20261003.db.gz",
                                need=100 * GB, free=0)
        self.assertEqual(victims, ["radar-20260912.db.gz"])   # 只有策略內的
        self.assertFalse(fits)

    def test_foreign_files_are_never_touched(self):
        files = DRIVE + [f("IMG_2698.HEIC"), f("notes.docx"), f("radar-backup-old.zip")]
        victims, _ = br.plan(files, new_name="radar-20261003.db.gz", need=100 * GB, free=0)
        for name in victims:
            self.assertRegex(name, r"^radar-\d{8}\.db\.gz$")

    def test_a_rerun_after_upload_does_not_count_the_new_file_twice(self):
        victims, _ = br.plan(DRIVE + [f("radar-20261003.db.gz")],
                             new_name="radar-20261003.db.gz", need=GB, free=2 * GB)
        self.assertNotIn("radar-20261003.db.gz", victims)
        self.assertNotIn("radar-20260926.db.gz", victims)


class CliTests(unittest.TestCase):
    def run_cli(self, args, files):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(files))), redirect_stdout(out):
            rc = br.main(args)
        return rc, out.getvalue().split()

    def test_exit_codes_carry_the_decision(self):
        rc, names = self.run_cli(["--new", "radar-20261003.db.gz", "--need", str(GB),
                                  "--free", str(2 * GB)], DRIVE)
        self.assertEqual((rc, names), (0, ["radar-20260912.db.gz"]))
        rc, _ = self.run_cli(["--new", "radar-20261003.db.gz", "--need", str(100 * GB),
                              "--free", "0"], DRIVE)
        self.assertEqual(rc, 3)
        rc, _ = self.run_cli(["--new", "evil.gz", "--need", "1", "--free", "1"], DRIVE)
        self.assertEqual(rc, 2)


class ScriptOrderTests(unittest.TestCase):
    code = SCRIPT.read_text(encoding="utf-8")

    def idx(self, needle):
        i = self.code.find(needle)
        self.assertNotEqual(i, -1, needle)
        return i

    def test_retention_runs_before_upload(self):
        self.assertLess(self.idx("backup_retention.py"), self.idx("rclone copyto"))
        self.assertLess(self.idx("rclone deletefile"), self.idx("rclone copyto"))

    def test_deletes_bypass_the_drive_trash(self):
        """垃圾桶照樣佔配額:保留策略刪的 3 份在裡面佔了 2.31 GiB。"""
        commands = [ln for ln in self.code.splitlines() if not ln.lstrip().startswith("#")]
        self.assertTrue(any("rclone deletefile" in ln for ln in commands))
        for line in commands:
            if "rclone deletefile" in line or re.search(r"rclone delete\b", line):
                self.assertIn("--drive-use-trash=false", line, line)

    def test_local_copy_is_removed_only_after_size_verification(self):
        self.assertLess(self.idx("REMOTE_SIZE"), self.idx("rm -f data/radar-"))
        self.assertLess(self.idx("rclone copyto"), self.idx("rm -f data/radar-"))

    def test_no_room_is_a_specific_high_alert_that_keeps_the_local_copy(self):
        block = self.code[self.idx('if [ "$PLAN_RC" -eq 3 ]'):self.idx("rclone copyto")]
        self.assertIn("空間不足", block)
        self.assertIn("本機保留", block)
        self.assertIn("high", block)
        self.assertIn("exit 3", block)

    def test_shell_branches_on_exit_codes_not_on_printed_text(self):
        self.assertIn("PLAN_RC=$?", self.code)
        self.assertNotRegex(self.code, r'grep[^\n]*"?FITS')

    def test_integrity_check_still_gates_the_snapshot(self):
        self.assertLess(self.idx("integrity_check"), self.idx("gzip -c"))


if __name__ == "__main__":
    unittest.main()
