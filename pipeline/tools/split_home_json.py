"""把一份既有 export 目錄的 radar.json 用正式的 split_home 拆成 home/head.json + home/stocks.json。

    python tools/split_home_json.py DATA_DIR            # 在 DATA_DIR/home/ 寫兩檔,印大小
    python tools/split_home_json.py DATA_DIR --report-only

用途(docs/44 P2 驗證):沒有本機 radar.db 時,拿真實的 radar.json 當輸入,產生首頁拆檔;
再餵給 parity-snapshot.mjs(新舊佈局各跑一次,頁面文字 diff 應為空),並量 raw / brotli 大小。
接回(merge_home)必須與 home_projection(radar) 深度相等,這裡順手驗一次。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.export.home_split import (  # noqa: E402
    home_projection, merge_home, split_home, write_home,
)
from radar.export.stock_parts import dumps_compact  # noqa: E402


def _br(data: bytes, quality: int) -> int | None:
    try:
        import brotli  # type: ignore
    except ImportError:
        return None
    return len(brotli.compress(data, quality=quality))


def _row(label: str, data: bytes) -> str:
    b5, b11 = _br(data, 5), _br(data, 11)
    fmt = lambda n: "n/a" if n is None else f"{n / 1024:8.1f} KB"
    return f"{label:<22}{len(data) / 1024:8.1f} KB raw   br(q5) {fmt(b5)}   br(q11) {fmt(b11)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--report-only", action="store_true", help="measure only; write nothing")
    a = ap.parse_args()
    out = Path(a.data_dir)
    radar_text = (out / "radar.json").read_text(encoding="utf-8")
    radar = json.loads(radar_text)
    head, stocks_file = split_home(radar)
    merged = merge_home(head, stocks_file)
    if merged != home_projection(radar):
        print("merge_home(head, stocks) != home_projection(radar)", file=sys.stderr)
        return 1
    if not a.report_only:
        write_home(out, radar)
        print(f"wrote {out / 'home' / 'head.json'} and {out / 'home' / 'stocks.json'}")

    legacy = radar_text.encode("utf-8")
    legacy_compact = dumps_compact(radar).encode("utf-8")
    head_b = dumps_compact(head).encode("utf-8")
    stocks_b = dumps_compact(stocks_file).encode("utf-8")
    print(f"data_date={radar['data_date']} stocks={len(radar.get('stocks', []))}")
    print(_row("radar.json (as is)", legacy))
    print(_row("radar.json compact", legacy_compact))
    print(_row("home/head.json", head_b))
    print(_row("home/stocks.json", stocks_b))
    print(_row("head + stocks", head_b + stocks_b))
    # 每個頂層鍵與每檔欄位的 raw 佔比,看瘦身是從哪裡來的
    per_key = {k: len(dumps_compact(v).encode("utf-8")) for k, v in radar.items()}
    print("top-level raw bytes:", json.dumps(dict(sorted(per_key.items(), key=lambda kv: -kv[1]))))
    stock_keys: dict[str, int] = {}
    for s in radar.get("stocks", []):
        for k, v in s.items():
            stock_keys[k] = stock_keys.get(k, 0) + len(dumps_compact(v).encode("utf-8")) + len(k) + 3
    print("stocks[] field raw bytes:", json.dumps(dict(sorted(stock_keys.items(), key=lambda kv: -kv[1]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
