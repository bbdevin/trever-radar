"""docs/46:後端產生的每一個理由/風險/口袋 code 都必須在前端多空分類表裡。

從 scores.py / indicators.py / pocket.py / futures_volume_anomaly.py 抽出所有長得像 code 的字串常值,
對 web/lib/bullBear.ts 的 SIDE_BY_CODE 比對;新增 code 卻沒分類 → 這裡擋下
(否則它在多空摘要裡會默默落到「其他」)。

docs/46 v2 另加一道鍵閘門:json_export 個股 payload 的每一個頂層鍵,都必須出現在
web/lib/facts/index.ts 的 STOCK_KEYS_USED ∪ STOCK_KEYS_NOT_FACTS——新增一個鍵卻沒決定
它要不要產多空事實 → 擋下。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "pipeline" / "radar" / "compute" / "scores.py",
    ROOT / "pipeline" / "radar" / "compute" / "indicators.py",
    ROOT / "pipeline" / "radar" / "pocket.py",
    ROOT / "pipeline" / "radar" / "compute" / "futures_volume_anomaly.py",
]
BULL_BEAR = ROOT / "web" / "lib" / "bullBear.ts"
FACTS_INDEX = ROOT / "web" / "lib" / "facts" / "index.ts"
JSON_EXPORT = ROOT / "pipeline" / "radar" / "export" / "json_export.py"
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


def stock_payload_keys() -> set[str]:
    """個股 payload 的頂層鍵:`payload = {` 字面量裡縮排 16 格那層的鍵,加上之後 `payload["x"] =` 補的鍵。"""
    src = JSON_EXPORT.read_text(encoding="utf-8")
    m = re.search(r"\n( +)payload = \{\n +\"id\": sid,", src)
    assert m, "找不到個股 payload 字面量"
    indent = m.group(1)
    start = m.start() + 1
    end = src.index(f"\n{indent}}}\n", start)
    write = src.index('(stock_dir / f"{sid}.json").write_text(', end)
    keys: set[str] = set()
    for line in src[start:end].splitlines()[1:]:
        if re.match(rf"^{indent} {{4}}\S", line):
            keys |= set(re.findall(r'"(\w+)":', line))
    keys |= set(re.findall(r'payload\["(\w+)"\]\s*=', src[end:write]))
    return keys


def facts_key_lists() -> tuple[set[str], set[str]]:
    src = FACTS_INDEX.read_text(encoding="utf-8")

    def block(name: str) -> set[str]:
        b = src[src.index(f"export const {name} = ["):]
        b = b[: b.index("] as const;")]
        return set(re.findall(r'"(\w+)"', b))

    return block("STOCK_KEYS_USED"), block("STOCK_KEYS_NOT_FACTS")


class BullBearCodeCoverage(unittest.TestCase):
    def test_every_stock_payload_key_is_decided(self):
        keys = stock_payload_keys()
        self.assertIn("price_levels", keys)
        self.assertIn("branch_pnl_est", keys)
        self.assertIn("futures", keys)
        used, not_facts = facts_key_lists()
        self.assertEqual(used & not_facts, set())
        missing = sorted(keys - used - not_facts)
        self.assertEqual(missing, [], f"web/lib/facts/index.ts 的 STOCK_KEYS_USED / STOCK_KEYS_NOT_FACTS 缺少:{missing}")
        stale = sorted((used | not_facts) - keys)
        self.assertEqual(stale, [], f"web/lib/facts/index.ts 列了 payload 沒有的鍵:{stale}")

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
