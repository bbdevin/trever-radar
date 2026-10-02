"""前端文案的機械性檢查(2026-10-02)。

拿掉權證分頁的認購／認售切換時,`${kindLabel}權證…` 被替換成 `$權證…`,畫面上
直接出現「$權證買超金額最多券商」——型別檢查與 build 都不會抓,因為那仍是合法
字串。這裡掃整個 web 原始碼:`$` 後面緊接中文字,幾乎必然是模板字串的殘骸。
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
STRAY = re.compile(r"\$[一-鿿]")


class WebCopyHygieneTests(unittest.TestCase):
    def test_no_template_leftovers_in_user_facing_copy(self):
        offenders = []
        for path in [*(WEB / "app").rglob("*.tsx"), *(WEB / "components").rglob("*.tsx"),
                     *(WEB / "lib").glob("*.ts")]:
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if STRAY.search(line):
                    offenders.append(f"{path.relative_to(WEB).as_posix()}:{no}: {line.strip()}")
        self.assertEqual(offenders, [])

    def test_the_check_is_not_vacuous(self):
        self.assertTrue(STRAY.search("title={`$權證買超金額最多券商`}"))
        self.assertFalse(STRAY.search("`${label}權證`"))


if __name__ == "__main__":
    unittest.main()
