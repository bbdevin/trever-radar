"""持有 `/tmp/radar-db.lock` 的腳本不得把 fd 9 洩漏給常駐子程序。

`flock` 鎖的是 **open file description**,不是程序。`acquire_db_lock`(`lib.sh`)
與少數腳本自己寫的 `exec 9>/tmp/radar-db.lock` 都把那個 description 開在 fd 9;
fork 出來的子程序會**共用同一個 description**,所以只要有任何一個子程序還活著,
鎖就還在——即使開鎖的那支腳本早就結束了。

`safe-branch-stats.sh` 與 `weekly-tdcc.sh` 在收尾時會用 `nohup ... &` 補起
`bf-cron-guard.sh` 與 `bf-supervisor.sh` 兩個**常駐** daemon(只在它們不在跑時才起)。
若在持鎖狀態下起,鎖就永久留在 daemon 身上,之後每一輪日更的 `acquire_db_lock`
都會 `flock -n` 失敗而 `exit 0`——整條日更靜默停擺;而 `bf-cron-guard.sh` 用
`fuser /tmp/radar-db.lock` 偵測寫入者時會看到自己,於是把回補容器永遠 pause 住。

正解是在起 daemon 之前 `exec 9>&-` 把 fd 關掉(此時 DB 工作已全部做完,放鎖安全)。
repo 內既有先例:`manual-catchup.sh` 在呼叫 `weekly-backup.sh`(它自己要拿同一把鎖)
之前就是這樣做的。

本檔直接解析腳本原始碼,不維護白名單:哪支腳本持鎖、哪支腳本起常駐子程序,
都由內容判定,所以新腳本一寫出來就自動納入檢查。
"""
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "vps" / "scripts"

# `acquire_db_lock`(呼叫,不是 lib.sh 裡的定義)或腳本自己開的 fd 9。
CALLS_ACQUIRE = re.compile(r"^\s*acquire_db_lock\s*$")
OPENS_FD9 = re.compile(r"^\s*exec\s+9>\s*/tmp/radar-db\.lock\s*$")
# 關掉 fd 9 → 釋放鎖。
CLOSES_FD9 = re.compile(r"^\s*exec\s+9>&-\s*$")
# `nohup ... &` = 刻意活過本腳本的子程序。行尾的 `&` 不能是 `2>&1` 的一部分,
# 故要求它是最後一個非空白字元且前面不是 `>`。
SPAWNS_PERSISTENT = re.compile(r"^\s*nohup\b.*[^>&]&\s*$")


def _script_files() -> list[Path]:
    # lib.sh 只定義 acquire_db_lock、自己不排程也不起 daemon,不是被檢查的對象。
    return sorted(p for p in SCRIPTS_DIR.glob("*.sh") if p.name != "lib.sh")


def _classify(path: Path) -> tuple[int | None, int | None, list[int]]:
    """回傳 (第一次持鎖的行號, 第一次起常駐子程序的行號, 所有關 fd 9 的行號)。

    行號為 1-based,對得上編輯器與 file:line 連結。
    """
    hold_line: int | None = None
    spawn_line: int | None = None
    close_lines: list[int] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.split("#", 1)[0]  # 註解裡提到不算
        if hold_line is None and (CALLS_ACQUIRE.match(stripped) or OPENS_FD9.match(stripped)):
            hold_line = i
        if CLOSES_FD9.match(stripped):
            close_lines.append(i)
        if spawn_line is None and SPAWNS_PERSISTENT.match(stripped):
            spawn_line = i
    return hold_line, spawn_line, close_lines


class TestVpsLockDiscipline(unittest.TestCase):
    def test_parser_is_not_vacuous(self):
        """解析器壞掉時不能靜悄悄地全部通過。"""
        scripts = _script_files()
        self.assertGreater(len(scripts), 5, "vps/scripts 下應該有多支腳本")

        holders = [p.name for p in scripts if _classify(p)[0] is not None]
        spawners = [p.name for p in scripts if _classify(p)[1] is not None]
        self.assertGreaterEqual(
            len(holders), 5,
            f"應該偵測到多支持鎖腳本,只找到 {holders}——解析器可能壞了",
        )
        self.assertGreaterEqual(
            len(spawners), 2,
            f"應該偵測到多支會起常駐 daemon 的腳本,只找到 {spawners}——解析器可能壞了",
        )
        # 這條檢查本身要有東西可查:必須真的存在「既持鎖又起 daemon」的腳本。
        both = [p.name for p in scripts
                if _classify(p)[0] is not None and _classify(p)[1] is not None]
        self.assertGreaterEqual(
            len(both), 1,
            "沒有任何腳本同時持鎖並起常駐子程序,這條規則就沒有在檢查任何東西",
        )

    def test_persistent_children_are_never_spawned_holding_the_lock(self):
        violations = []
        for path in _script_files():
            hold_line, spawn_line, close_lines = _classify(path)
            if hold_line is None or spawn_line is None:
                continue
            if spawn_line < hold_line:
                continue  # 先起 daemon 再拿鎖,子程序沒有繼承到
            released = [c for c in close_lines if hold_line < c < spawn_line]
            if not released:
                violations.append(
                    f"{path.name}:{spawn_line} 在持鎖狀態下起常駐子程序"
                    f"(鎖取得於 :{hold_line},其間沒有 `exec 9>&-`)——"
                    f"daemon 會繼承 fd 9 並讓 /tmp/radar-db.lock 永不釋放,"
                    f"之後每一輪 acquire_db_lock 都會失敗"
                )
        self.assertEqual([], violations, "\n" + "\n".join(violations))

    def test_the_known_offenders_carry_the_release(self):
        """兩支已知會補起 daemon 的腳本必須明確帶著 `exec 9>&-`。

        上一條規則是「不得違規」;這條是「這兩支確實走在被檢查的路徑上」,
        免得日後有人把 nohup 那段改寫成解析器認不得的形狀,規則就無聲失效。
        """
        for name in ("safe-branch-stats.sh", "weekly-tdcc.sh"):
            with self.subTest(script=name):
                hold_line, spawn_line, close_lines = _classify(SCRIPTS_DIR / name)
                self.assertIsNotNone(hold_line, f"{name} 應該持有 DB 鎖")
                self.assertIsNotNone(spawn_line, f"{name} 應該會補起常駐 daemon")
                self.assertTrue(
                    [c for c in close_lines if hold_line < c < spawn_line],
                    f"{name} 必須在 :{hold_line} 取鎖與 :{spawn_line} 起 daemon 之間"
                    f"放一行 `exec 9>&-`",
                )


if __name__ == "__main__":
    unittest.main()
