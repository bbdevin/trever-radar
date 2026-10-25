"""radar 套件。

`SOURCE_HASH`:本套件所有 .py 原始碼在**套件第一次被匯入時**的雜湊(export_memo 的程式鹽)。
必須在這裡、任何子模組載入之前算:正式機 $REPO/pipeline 是 bind mount,git pull 可能在行程
載入子模組的途中換掉原始碼。在這裡先記下,之後任何一次換檔都會讓存檔前的磁碟複查對不上 →
export_memo 不存(verifier 2026-10-25:原本在 export_memo 匯入時才算,json_export／branch_days
早已載入,兩者之間約 130 ms 的 pull 會讓舊程式的輸出被記成新程式的)。
"""
import hashlib as _hashlib
from pathlib import Path as _Path


def source_hash(root: "_Path | None" = None) -> str:
    root = _Path(root) if root is not None else _Path(__file__).resolve().parent
    h = _hashlib.blake2b(digest_size=16)
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


SOURCE_HASH: str = source_hash()
