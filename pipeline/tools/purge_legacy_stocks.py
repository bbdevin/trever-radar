"""一次性清理(docs/44 §3.2 步驟 ③):刪掉 export 目錄裡舊單一檔 ``stocks/{id}.json``。

    python3 pipeline/tools/purge_legacy_stocks.py web/public/data            # dry-run:只印
    python3 pipeline/tools/purge_legacy_stocks.py web/public/data --write    # 真的刪

2026-10-07 起 export-json 預設只寫拆檔(``stocks/core|chips|hist``),舊單一檔不再更新,
留在磁碟上只會被 ``wrangler deploy`` 繼續當資產上傳、而且內容一天比一天舊。刪掉之後,
下一次 ``deploy_data`` 就把它們從 Workers 資產移除。

規則(刻意保守):
  * 只看 ``<data>/stocks/`` **這一層**的 ``*.json`` 檔;``core/``、``chips/``、``hist/``
    (含 ``hist/index.json``)是子目錄,``glob`` 本來就不會下去,也不碰任何子目錄。
  * 預設 dry-run,印檔數與位元組;``--write`` 才刪。
  * ``stocks/core/`` 的檔數必須 ≥ 要刪的舊檔數,否則拒絕(exit 2)——新佈局沒到齊時
    (例:還沒有任何一輪跑過拆檔 export),刪舊檔等於讓個股頁 404。

只用標準函式庫,VPS 主機上的 python3 直接跑,不必進容器、不開資料庫。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def legacy_files(stocks_dir: Path) -> list[Path]:
    """``stocks/`` 這一層的 ``*.json`` 一般檔(不遞迴、不含子目錄)。"""
    return sorted(p for p in stocks_dir.glob("*.json") if p.is_file())


def core_count(stocks_dir: Path) -> int:
    core = stocks_dir / "core"
    if not core.is_dir():
        return 0
    return sum(1 for p in core.glob("*.json") if p.is_file())


def purge(data_dir: Path, *, write: bool) -> int:
    stocks_dir = data_dir / "stocks"
    if not stocks_dir.is_dir():
        print(f"purge-legacy-stocks: {stocks_dir} 不存在", file=sys.stderr)
        return 2
    files = legacy_files(stocks_dir)
    total = sum(p.stat().st_size for p in files)
    cores = core_count(stocks_dir)
    mode = "write" if write else "dry-run"
    print(f"purge-legacy-stocks: mode={mode} dir={stocks_dir} legacy_files={len(files)} "
          f"legacy_bytes={total} ({total / 1024 / 1024:.1f} MiB) core_files={cores}")
    if not files:
        print("purge-legacy-stocks: nothing to delete")
        return 0
    if cores < len(files):
        print(f"purge-legacy-stocks: REFUSED: stocks/core 只有 {cores} 檔,少於要刪的 "
              f"{len(files)} 個舊單一檔;新佈局尚未到齊,不刪", file=sys.stderr)
        return 2
    if not write:
        for p in files[:5]:
            print(f"  would delete {p.name}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")
        print("purge-legacy-stocks: dry-run only; re-run with --write to delete")
        return 0
    deleted = freed = 0
    for p in files:
        try:
            size = p.stat().st_size
            p.unlink()
        except FileNotFoundError:
            continue
        deleted += 1
        freed += size
    print(f"purge-legacy-stocks: deleted={deleted} freed_bytes={freed} "
          f"({freed / 1024 / 1024:.1f} MiB); next deploy_data removes them from Workers")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data_dir", help="export 目錄(VPS:~/trever-radar/web/public/data)")
    ap.add_argument("--write", action="store_true", help="真的刪除(預設只印 dry-run)")
    args = ap.parse_args(argv)
    return purge(Path(args.data_dir), write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
