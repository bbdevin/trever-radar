"""docs/46:後端產生的每一個理由/風險/口袋 code 都必須在前端多空分類表裡。

從 scores.py / indicators.py / pocket.py 抽出所有長得像 code 的字串常值,
對 web/lib/bullBear.ts 的 SIDE_BY_CODE 比對;新增 code 卻沒分類 → 這裡擋下
(否則它在多空摘要裡會默默落到「其他」)。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "pipeline" / "radar" / "compute" / "scores.py",
    ROOT / "pipeline" / "radar" / "compute" / "indicators.py",
    ROOT / "pipeline" / "radar" / "pocket.py",
]
BULL_BEAR = ROOT / "web" / "lib" / "bullBear.ts"
# 長得像 code、其實不是理由/風險的常值
NOT_CODES = {"ARMED_OR_CONC"}
CODE_RE = re.compile(r'"([A-Z][A-Z0-9]*_[A-Z0-9_]+)"')


def backend_codes() -> set[str]:
    out: set[str] = set()
    for p in SOURCES:
        out |= set(CODE_RE.findall(p.read_text(encoding="utf-8")))
    return out - NOT_CODES


def classified_codes() -> set[str]:
    src = BULL_BEAR.read_text(encoding="utf-8")
    block = src[src.index("export const SIDE_BY_CODE"):]
    block = block[: block.index("\n};")]
    return set(re.findall(r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]+):\s*[BRC]\(", block))


class BullBearCodeCoverage(unittest.TestCase):
    def test_every_backend_code_is_classified(self):
        codes = backend_codes()
        self.assertGreater(len(codes), 50)
        missing = sorted(codes - classified_codes())
        self.assertEqual(missing, [], f"web/lib/bullBear.ts SIDE_BY_CODE 缺少:{missing}")

    def test_known_risk_codes_present(self):
        for code in ("B_RISK_REVERSAL", "R_HOT5", "R_RSI_OVERHEAT", "G2_GEO_SELL", "S4_COMPRESSION_SETUP_V2"):
            self.assertIn(code, classified_codes())


if __name__ == "__main__":
    unittest.main()
