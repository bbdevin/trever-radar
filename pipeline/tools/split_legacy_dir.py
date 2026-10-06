"""把一份既有 export 目錄(舊單一檔 stocks/{id}.json)用正式的 split_stock_payload 拆成新佈局。

    python tools/split_legacy_dir.py SRC_DATA_DIR DST_DATA_DIR [--keep-legacy]

用途(docs/44 P1 §3.2 驗證):沒有本機 radar.db 時,拿真實的舊 JSON 當輸入,產生
core/hist/chips 三份;再用 web/scripts/verify-split-merge.mjs 以前端的 mergeStockParts
接回逐檔比對,並量 raw/brotli 大小。cut 與聯集都照 radar.json 的 data_date / stocks 決定,
與 export-json 同一條規則。DST 其餘檔案(radar.json、branches/…)原樣複製,方便直接餵給
parity-snapshot.mjs 當 out/data。

只讀 SRC,不寫 SRC。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.export.stock_parts import (  # noqa: E402
    StockPartsWriter, hist_cut, merge_stock_parts, split_stock_payload,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--keep-legacy", action="store_true",
                    help="also copy the legacy stocks/{id}.json files into DST (rollout layout)")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("stocks"))
    radar = json.loads((src / "radar.json").read_text(encoding="utf-8"))
    d = radar["data_date"]
    union = {s["id"] for s in radar.get("stocks", [])}
    cut = hist_cut(d)
    stock_dir = dst / "stocks"
    stock_dir.mkdir()
    writer = StockPartsWriter(stock_dir)
    n = split = 0
    for p in sorted((src / "stocks").glob("*.json")):
        payload = json.loads(p.read_text(encoding="utf-8"))
        sid = payload["id"]
        parts = split_stock_payload(payload, cut=cut if sid in union else None)
        if merge_stock_parts(parts["core"], parts["hist"], parts["chips"]) != payload:
            raise SystemExit(f"split/merge mismatch: {sid}")
        writer.write(parts)
        if a.keep_legacy:
            shutil.copy2(p, stock_dir / p.name)
        n += 1
        split += parts["hist"] is not None
    writer.finish()
    print(json.dumps({"data_date": d, "cut": cut, "stocks": n, "union": len(union),
                      "hist_files": split, "dst": str(dst)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
