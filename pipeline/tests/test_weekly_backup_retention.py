"""週備份保留策略(vps/scripts/backup_retention.py)與腳本順序。

背景(2026-09-30):09-26 的週備份因使用者個人 Drive 配額滿而沒上傳,本機留著
那一週唯一的一份。舊腳本上傳之後才清舊檔(空間不夠時走不到),而刪檔進垃圾桶
照樣佔配額。fixture 的大小是發明的整數,答案可以手算。
"""
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
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
        self.assertIn("$(kept_note)", block)
        note = self.code[self.idx("kept_note() {"):]
        note = note[:note.index("\n}")]
        self.assertIn("本機保留", note)
        self.assertIn("MiB", note)
        self.assertIn("磁碟", note)
        self.assertIn("high", block)
        self.assertIn("exit 3", block)

    def test_shell_branches_on_exit_codes_not_on_printed_text(self):
        self.assertIn("PLAN_RC=$?", self.code)
        self.assertNotRegex(self.code, r'grep[^\n]*"?FITS')

    def test_integrity_check_still_gates_the_snapshot(self):
        self.assertLess(self.idx("integrity_check"), self.idx("gzip -c"))
        self.assertLess(self.idx("wal_checkpoint(TRUNCATE)"), self.idx("integrity_check;"))

    def test_db_lock_is_released_after_gzip_and_before_any_drive_io(self):
        """DB 鎖只保護 checkpoint/integrity/gzip;上傳與重試期間不能讓別的工作等。"""
        code = "\n".join(ln for ln in self.code.splitlines() if not ln.lstrip().startswith("#"))
        at = lambda s: code.index(s)
        release = at("exec 9>&-")
        self.assertLess(at("acquire_db_lock"), at("PRAGMA wal_checkpoint"))
        self.assertLess(at("gzip -c"), release)
        self.assertLess(at('SIZE="$(stat'), release)
        for needle in ('FREE="$(drive_free)"', "rclone lsjson", "rclone deletefile", "rclone copyto"):
            self.assertLess(release, at(needle), needle)

    def test_backup_has_its_own_lock_held_for_the_whole_run(self):
        self.assertLess(self.idx("flock -n 7"), self.idx("acquire_db_lock"))
        self.assertNotIn("exec 7>&-", self.code)


def _bash_path(p: Path) -> str:
    s = str(p)
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:\\", s):
        return "/mnt/" + s[0].lower() + s[2:].replace("\\", "/")
    return s


def _harness_ok() -> bool:
    if shutil.which("bash") is None:
        return False
    try:
        r = subprocess.run(["bash", "-c", "command -v flock && command -v python3 && command -v gzip"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# 假 docker:checkpoint 印 0、integrity_check 印 ok。
STUB_DOCKER = r"""#!/usr/bin/env bash
case "$*" in
  *integrity_check*) echo "${STUB_INTEGRITY:-ok}" ;;
  *) echo 0 ;;
esac
"""
# 假 rclone:Drive = $STUB_DIR/drive/ 目錄 + drive.json 既有清單。copyto 前 STUB_COPY_FAILS 次
# 回 10-24 事故那一行 403;每次 copyto 都記下 DB 鎖當時是否空著。
STUB_RCLONE = r"""#!/usr/bin/env bash
echo "$1" >> "$STUB_DIR/rclone_calls"
case "$1" in
  about) echo "{\"free\": ${STUB_FREE:-50000000000}}" ;;
  lsjson)
    case "$2" in
      */) cat "$STUB_DIR/drive.json" ;;
      *) name="${2##*/}"
         if [ -f "$STUB_DIR/drive/$name" ]; then
           printf '[{"Name":"%s","Size":%s}]\n' "$name" "$(stat -c %s "$STUB_DIR/drive/$name")"
         else
           echo '[]'
         fi ;;
    esac ;;
  deletefile) echo "${3##*/} $2" >> "$STUB_DIR/deleted" ;;
  copyto)
    if flock -n /tmp/radar-db.lock true; then echo free; else echo held; fi >> "$STUB_DIR/lock_at_upload"
    n=$(( $(cat "$STUB_DIR/copy_count" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB_DIR/copy_count"
    if [ "$n" -le "${STUB_COPY_FAILS:-0}" ]; then
      echo "ERROR : radar-x.db.gz: Failed to copy: googleapi: Error 403: The user's Drive storage quota has been exceeded., storageQuotaExceeded" >&2
      exit 1
    fi
    mkdir -p "$STUB_DIR/drive"
    cp "$2" "$STUB_DIR/drive/${3##*/}" ;;
  *) echo "unexpected rclone $*" >&2; exit 9 ;;
esac
"""
STUB_CURL = r"""#!/usr/bin/env bash
title=""; body=""
while [ $# -gt 0 ]; do
  case "$1" in
    -H) case "$2" in Title:*) title="${2#Title: }" ;; esac; shift 2 ;;
    -d) body="$2"; shift 2 ;;
    *) shift ;;
  esac
done
echo "${title} | ${body}" >> "$STUB_DIR/notify"
"""
STUB_SLEEP = r"""#!/usr/bin/env bash
echo "$1" >> "$STUB_DIR/sleeps"
"""
# 既有 Drive:09-26 是保留的最新週;09-12 與 09-19 同月 → 策略刪 09-12。
DRIVE_FIXTURE = [f("radar-20260926.db.gz", 100), f("radar-20260919.db.gz", 100),
                 f("radar-20260912.db.gz", 100)]


@unittest.skipUnless(_harness_ok(), "需要 bash + flock + python3 + gzip(Windows 上是 WSL)")
class WeeklyBackupUploadRetryHarness(unittest.TestCase):
    """真的跑 weekly-backup.sh + lib.sh + backup_retention.py(複製到暫存 repo,快照不落在
    真的 data/),只把 docker / rclone / curl / sleep 換成 stub。"""

    def run_script(self, **env):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            repo = tmp / "repo"
            scripts = repo / "vps" / "scripts"
            scripts.mkdir(parents=True)
            for name in ("lib.sh", "weekly-backup.sh", "backup_retention.py"):
                (scripts / name).write_bytes((SCRIPT.parent / name).read_bytes().replace(b"\r\n", b"\n"))
            (repo / "data").mkdir()
            (repo / "data" / "radar.db").write_bytes(b"SQLite format 3\x00" + bytes(range(256)) * 64)
            stub = tmp / "bin"
            stub.mkdir()
            for name, body in (("docker", STUB_DOCKER), ("rclone", STUB_RCLONE),
                               ("curl", STUB_CURL), ("sleep", STUB_SLEEP)):
                (stub / name).write_text(body, encoding="utf-8", newline="\n")
            (tmp / "drive.json").write_text(json.dumps(DRIVE_FIXTURE), encoding="utf-8")
            for name in ("rclone_calls", "notify", "sleeps", "lock_at_upload", "deleted"):
                (tmp / name).write_text("", encoding="utf-8")
            env_lines = "".join(f'export {k}="{v}"\n' for k, v in env.items())
            wrapper = tmp / "run.sh"
            wrapper.write_text(
                "set -u\n"
                f'export STUB_DIR="{_bash_path(tmp)}"\n'
                'export NTFY="test-topic"\n'
                f"{env_lines}"
                'chmod +x "$STUB_DIR/bin/"*\n'
                'export PATH="$STUB_DIR/bin:$PATH"\n'
                f'bash "{_bash_path(scripts / "weekly-backup.sh")}"\n',
                encoding="utf-8", newline="\n")
            r = subprocess.run(["bash", _bash_path(wrapper)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=120)
            read = lambda n: (tmp / n).read_text(encoding="utf-8").splitlines()
            out = {
                "calls": read("rclone_calls"), "notes": read("notify"), "sleeps": read("sleeps"),
                "lock": read("lock_at_upload"), "deleted": read("deleted"),
                "local": sorted(p.name for p in (repo / "data").glob("radar-*.db.gz")),
                "uploaded": sorted(p.name for p in (tmp / "drive").glob("*")) if (tmp / "drive").exists() else [],
            }
        return r, out

    def test_quota_403_twice_then_success_uploads_and_removes_local(self):
        r, o = self.run_script(STUB_COPY_FAILS="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(o["calls"].count("copyto"), 3)
        self.assertEqual(o["sleeps"], ["300", "600"])
        # 開頭一次 + 每次重試前一次
        self.assertEqual(o["calls"].count("about"), 3)
        self.assertIn("drive free before retry 2: 50000000000 bytes", r.stdout)
        self.assertIn("drive free before retry 3: 50000000000 bytes", r.stdout)
        self.assertIn("upload attempt 3/3 rc=0", r.stdout)
        self.assertEqual(o["lock"], ["free"] * 3, "上傳期間不得握 DB 鎖")
        self.assertEqual(o["deleted"], ["radar-20260912.db.gz --drive-use-trash=false"])
        self.assertEqual(len(o["uploaded"]), 1)
        self.assertEqual(o["local"], [], "大小比對通過才刪本機,而且要刪")
        self.assertEqual(len(o["notes"]), 1, o["notes"])
        self.assertIn("週備份 · 成功", o["notes"][0])

    def test_always_failing_upload_notifies_once_and_keeps_local(self):
        r, o = self.run_script(STUB_COPY_FAILS="99")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertEqual(o["calls"].count("copyto"), 3)
        self.assertEqual(o["sleeps"], ["300", "600"])
        self.assertEqual(o["uploaded"], [])
        self.assertEqual(len(o["local"]), 1, "上傳失敗時本機快照是這一週唯一的一份")
        self.assertEqual(len(o["notes"]), 1, o["notes"])
        note = o["notes"][0]
        self.assertIn("週備份 · 失敗", note)
        self.assertIn("storageQuotaExceeded", note)
        self.assertIn("試了 3 次", note)
        self.assertIn("本機保留 data/" + o["local"][0], note)
        self.assertRegex(note, r"（\d+ MiB）")
        self.assertRegex(note, r"VPS 磁碟因此只剩 \d+ MiB 可用")
        self.assertIn("radar-20260912.db.gz", note)

    def test_first_try_success_does_not_sleep(self):
        r, o = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(o["calls"].count("copyto"), 1)
        self.assertEqual(o["sleeps"], [])
        self.assertEqual(o["local"], [])

    def test_bad_integrity_uploads_nothing(self):
        r, o = self.run_script(STUB_INTEGRITY="corrupt")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(o["calls"], [])
        self.assertIn("完整性檢查失敗", o["notes"][0])


if __name__ == "__main__":
    unittest.main()
