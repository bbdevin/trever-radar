# -*- coding: utf-8 -*-
"""首頁多方榜(docs/48 §1.1)接進 VPS 資料輪:export-json 之後、deploy_data 之前建置,
失敗只 warn、絕不擋上線。

兩層(手法同 test_poll_until_published.py):
* 原始碼解析:lib.sh 的 build_bull_board 有硬逾時、跑對的建置器與路徑、永遠 return 0;
  每一支「export-json 後 deploy_data」的腳本,在兩者之間都有一行裸的 build_bull_board
  (不包 run_step_or_fail、不接 `|| exit`),而且它緊跟在 export-json 之後——
  沒匯出(publish skipped)的路徑就不會建。
* bash 實跑(本機有 bash/WSL 才跑):source 真的 lib.sh,PATH 前面放一支假 node,
  驗失敗/逾時都回 0、ERR trap 不觸發、後續步驟照跑、warn 一則;成功時參數正確。
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "vps" / "scripts"
LIB = SCRIPTS / "lib.sh"

FULL_LINE_COMMENT = re.compile(r"^\s*#")
TRAILING_COMMENT = re.compile(r"(?<=\s)#.*$")

# 目前所有「匯出後上線」的腳本。新增一支卻沒接多方榜 → 下面的掃描會抓到;
# 這份清單另外守「不要有人把某一支的上線整段拿掉卻沒人發現」。
EXPECTED_PUBLISHERS = {
    "daily-market.sh",
    "daily-tpex-quotes.sh",
    "daily-insti.sh",
    "daily-branches.sh",
    "daily-margin.sh",
    "safe-branch-stats.sh",
    "manual-catchup.sh",
    "mid-backfill-publish.sh",
    "weekly-tdcc.sh",
    "monthly-directors.sh",
    "backfill-margin.sh",
    "backfill-tdcc.sh",
}


def _code_lines(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        out.append("" if FULL_LINE_COMMENT.match(line) else TRAILING_COMMENT.sub("", line).rstrip())
    return out


def _fn(name: str) -> str:
    m = re.search(rf"^{name}\(\)\s*\{{(.*?)^\}}", "\n".join(_code_lines(LIB)), re.S | re.M)
    assert m, f"lib.sh 裡找不到 {name}()"
    return m.group(1)


def _is_export(line: str) -> bool:
    return bool(re.search(r"\bradar export-json\b", line))


def _is_deploy_call(line: str) -> bool:
    return bool(re.search(r"(^|\s)deploy_data\s*$", line))


def _publishers() -> dict[str, list[str]]:
    found = {}
    for path in sorted(SCRIPTS.glob("*.sh")):
        if path.name == "lib.sh":
            continue
        lines = _code_lines(path)
        if any(_is_export(ln) for ln in lines) and any(_is_deploy_call(ln) for ln in lines):
            found[path.name] = lines
    return found


class BuildBullBoardSource(unittest.TestCase):
    def test_has_hard_timeout(self):
        body = _fn("build_bull_board")
        self.assertRegex(body, r"\btimeout\b[^\n]*BULL_BOARD_TIMEOUT_SECS")
        m = re.search(r'BULL_BOARD_TIMEOUT_SECS="\$\{BULL_BOARD_TIMEOUT_SECS:-(\d+)\}"',
                      LIB.read_text(encoding="utf-8"))
        self.assertIsNotNone(m, "要有預設逾時")
        self.assertTrue(60 <= int(m.group(1)) <= 900, "實測 33.5 s;上限不得小到誤殺、也不得無上限")

    def test_runs_the_builder_on_exported_json(self):
        body = _fn("build_bull_board")
        self.assertIn("node --experimental-strip-types --no-warnings", body)
        self.assertIn('"$REPO/web/scripts/build-bull-board.mjs"', body)
        self.assertIn('--data "$REPO/web/public/data"', body)
        self.assertIn('--log "$REPO/data/bull_board_log"', body)
        self.assertNotIn("radar", body, "只讀匯出的 JSON,不進容器、不碰 DB")

    def test_logs_a_step_line_and_never_aborts(self):
        body = _fn("build_bull_board")
        self.assertRegex(body, r'if run_step "bull-board" ', "計時 log 走 run_step,且包在 if 裡取碼")
        self.assertIn("notify_warn", body)
        self.assertNotRegex(body, r"\bexit\b", "不得中止本輪")
        self.assertNotRegex(body, r'return "\$rc"', "不得把失敗碼往上傳")
        self.assertEqual(body.strip().splitlines()[-1].strip(), "return 0")


class PublishersBuildTheBoard(unittest.TestCase):
    def test_publisher_set_is_known(self):
        self.assertEqual(set(_publishers()), EXPECTED_PUBLISHERS)

    def test_builder_sits_between_export_and_every_deploy(self):
        for name, lines in _publishers().items():
            with self.subTest(script=name):
                deploys = [i for i, ln in enumerate(lines) if _is_deploy_call(ln)]
                self.assertTrue(deploys)
                for d in deploys:
                    e = max((i for i in range(d) if _is_export(lines[i])), default=None)
                    self.assertIsNotNone(e, f"{name}:{d + 1} deploy_data 之前沒有 export-json")
                    between = [ln.strip() for ln in lines[e + 1:d]]
                    self.assertIn("build_bull_board", between,
                                  f"{name}: export-json(第 {e + 1} 行)與 deploy(第 {d + 1} 行)之間沒有建置多方榜")

    def test_builder_is_bare_and_follows_export(self):
        for name, lines in _publishers().items():
            with self.subTest(script=name):
                calls = [i for i, ln in enumerate(lines) if re.search(r"\bbuild_bull_board\b", ln)]
                self.assertTrue(calls)
                for i in calls:
                    self.assertEqual(lines[i].strip(), "build_bull_board",
                                     "必須裸呼叫:不包 run_step_or_fail/run_step,不接 || exit")
                    prev = next(ln for ln in reversed(lines[:i]) if ln.strip())
                    self.assertTrue(_is_export(prev),
                                    f"{name}:{i + 1} 要緊跟在 export-json 之後(沒匯出就不建)")

    def test_no_script_builds_without_publishing(self):
        for path in SCRIPTS.glob("*.sh"):
            if path.name == "lib.sh" or path.name in EXPECTED_PUBLISHERS:
                continue
            with self.subTest(script=path.name):
                self.assertFalse(any(re.search(r"\bbuild_bull_board\b", ln) for ln in _code_lines(path)))


def _bash_path(p: Path) -> str:
    if os.name == "nt":
        drive, rest = os.path.splitdrive(str(p))
        return "/mnt/" + drive[0].lower() + rest.replace("\\", "/")
    return str(p)


BASH = shutil.which("bash")


def _bash(script: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "smoke.sh"
        path.write_text(script, encoding="utf-8", newline="\n")
        return subprocess.run([BASH, _bash_path(path)], capture_output=True, text=True,
                              encoding="utf-8", timeout=120)


def _bash_ok() -> bool:
    if not BASH:
        return False
    try:
        r = _bash("command -v timeout >/dev/null && echo ok")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


# 假 node:$FAKE_NODE 決定行為(ok / fail / hang)。ERR trap 換成可觀察的版本,
# 其餘照真的 lib.sh(set -euo pipefail 由 lib.sh 自己開)。
_PRELUDE = r'''
TMPD="$(mktemp -d)"
mkdir -p "$TMPD/bin"
cat > "$TMPD/bin/node" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_NODE:-ok}" in
  ok) echo "ARGS $*"; exit 0 ;;
  fail) exit 3 ;;
  hang) sleep 30 ;;
esac
EOF
chmod +x "$TMPD/bin/node"
export PATH="$TMPD/bin:$PATH"
unset NTFY
source "@LIB@"
trap 'echo ERR_FIRED' ERR
notify_warn() { echo "WARN $1"; }
'''


@unittest.skipUnless(_bash_ok(), "需要 bash + timeout(Linux 或 WSL)")
class BuildBullBoardSmoke(unittest.TestCase):
    def _run(self, env: str):
        r = _bash(_PRELUDE.replace("@LIB@", _bash_path(LIB)) + env + "\nbuild_bull_board\necho AFTER rc=$?\n")
        return r.returncode, r.stdout

    def test_success_passes_the_right_paths(self):
        rc, out = self._run("export FAKE_NODE=ok")
        self.assertEqual(rc, 0, out)
        self.assertIn("step bull-board start", out)
        self.assertRegex(out, r"step bull-board done rc=0 elapsed=\d+s")
        self.assertRegex(out, r"ARGS --experimental-strip-types --no-warnings \S*/web/scripts/build-bull-board\.mjs "
                              r"--data \S*/web/public/data --log \S*/data/bull_board_log")
        self.assertNotIn("WARN", out)
        self.assertIn("AFTER rc=0", out)

    def test_failure_warns_and_the_round_continues(self):
        rc, out = self._run("export FAKE_NODE=fail")
        self.assertEqual(rc, 0, out)
        self.assertIn("step bull-board done rc=3", out)
        self.assertIn("WARN 多方榜建置失敗（碼 3）", out)
        self.assertNotIn("ERR_FIRED", out)
        self.assertIn("AFTER rc=0", out)

    def test_timeout_is_enforced_and_the_round_continues(self):
        rc, out = self._run("export FAKE_NODE=hang BULL_BOARD_TIMEOUT_SECS=1")
        self.assertEqual(rc, 0, out)
        self.assertIn("step bull-board done rc=124", out)
        self.assertIn("WARN 多方榜建置失敗（碼 124）", out)
        self.assertNotIn("ERR_FIRED", out)
        self.assertIn("AFTER rc=0", out)


if __name__ == "__main__":
    unittest.main()
