#!/usr/bin/env python3
"""週備份的保留策略:決定上傳**之前**要從 Drive 刪哪些舊快照。

為什麼存在(2026-09-30):09-26 的週備份因 Drive 配額滿而沒上傳。根因兩層——
舊版腳本上傳**之後**才清舊檔,空間不夠時根本走不到清理;而它刪檔時 rclone 預設
移到垃圾桶,垃圾桶照樣佔配額,刪了等於沒刪(刪除端改用 --drive-use-trash=false,
在 weekly-backup.sh)。備份放在使用者**個人**的 Drive,與照片、文件共用 15 GiB。

策略(使用者 2026-09-30 核准):最近 2 份週快照 + 更舊者每月保留最新 1 份。
新快照算作那 2 份之一,所以上傳前只保留**最新 1 份**既有週快照。

若套完策略仍放不下新快照,依序刪**最舊的月快照**騰空間——最新那 1 份既有週快照
永遠不動。仍放不下 → 離開碼 3:shell 據此告警並保留本機檔,不上傳。

輸入:stdin 為 `rclone lsjson --files-only` 的 JSON。輸出:要刪的檔名,一行一個。
離開碼:0 = 刪完放得下;3 = 刪完仍放不下;2 = 參數錯誤。shell 只依離開碼分支,
不解析輸出文字(本專案的規則:shell 的控制流不接在 Python 印出的格式上)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys

NAME_RE = re.compile(r"^radar-(\d{8})\.db\.gz$")
KEEP_WEEKLY = 2          # 含這次要上傳的那一份
EXIT_FITS, EXIT_USAGE, EXIT_NO_ROOM = 0, 2, 3


def plan(files: list[dict], *, new_name: str, need: int, free: int) -> tuple[list[str], bool]:
    """回傳 (依序要刪的檔名, 刪完之後放不放得下)。

    ``files`` 是 rclone lsjson 的項目(至少有 Name、Size)。不符命名的檔一律不碰。
    """
    snaps = sorted(
        (f for f in files if NAME_RE.match(f["Name"]) and f["Name"] != new_name),
        key=lambda f: f["Name"], reverse=True,
    )
    # snaps[:KEEP_WEEKLY - 1] 是保留的既有週快照,永遠不進刪除名單。
    older = snaps[KEEP_WEEKLY - 1:]
    monthly: list[dict] = []
    victims: list[dict] = []
    seen_months: set[str] = set()
    for f in older:                      # 新到舊:每個月第一個看到的就是該月最新
        month = NAME_RE.match(f["Name"]).group(1)[:6]
        if month in seen_months:
            victims.append(f)
        else:
            seen_months.add(month)
            monthly.append(f)
    policy = [f["Name"] for f in victims]
    room = free + sum(int(f["Size"]) for f in victims)
    extra: list[str] = []
    for f in reversed(monthly):          # 放不下:從最舊的月快照開始刪
        if room >= need:
            break
        extra.append(f["Name"])
        room += int(f["Size"])
    if room < need:
        # 刪光月快照也放不下:那些月快照**一份都不刪**——刪了也上傳不了,只是白白
        # 少掉備份。策略內本來就該刪的照刪。
        return policy, False
    return policy + extra, True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--new", required=True, help="this run's snapshot name")
    p.add_argument("--need", type=int, required=True, help="bytes needed on Drive")
    p.add_argument("--free", type=int, required=True, help="bytes free on Drive now")
    try:
        args = p.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE
    if not NAME_RE.match(args.new):
        print(f"bad snapshot name: {args.new}", file=sys.stderr)
        return EXIT_USAGE
    victims, fits = plan(json.load(sys.stdin), new_name=args.new, need=args.need,
                         free=args.free)
    for name in victims:
        print(name)
    return EXIT_FITS if fits else EXIT_NO_ROOM


if __name__ == "__main__":
    sys.exit(main())
