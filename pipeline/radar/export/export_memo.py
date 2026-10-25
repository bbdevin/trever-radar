"""export-json 個股迴圈的「同輸入不重算」記憶(docs/44 §3.7,2026-10-25)。

晚上分點輪一輪跑兩次 export(第一段上線、權證＋排行統計之後第二段),兩次之間現股分點列與
日 K 不變,但個股迴圈裡最貴的幾段純計算每次都從頭算:分點日史編碼(``branch_days``)、
區間損益(``branch_pnl_est``)、分位計數(``branch_pctile_counts``)、價格位置(``price_levels``)。

做法(**輸入照讀,只省計算**):每一段的輸入每次照舊從 DB 讀出來,算一個摘要(blake2b,
``marshal`` 版本 2 序列化——同值同型別就同位元組,沒有參照/駐留旗標),與上一次 export 記下的
摘要相同,就直接拿上一次的輸出;不同(或沒有記錄、程式改過)就照舊算。
所以「哪些輸入變了」不必靠任何寫者自律或表層指紋——讀到的列本身就是指紋,寫漏依賴的
風險只剩「這段計算讀了摘要以外的東西」,那份清單寫在下面並有測試:

  段                  摘要涵蓋的輸入(每一段另加:整個 radar 套件原始碼與 Python 版本)
  branch_days         資料日 d + branch_trades_raw 主鍵範圍的原始列 (date, branch_id, buy, sell, net)
                      + 分點名查表(上一次的 id→名稱 必須在這一次原封不動;見下)
  branch_pnl_est      同上 + 該檔 K 線全欄位
  branch_pctile_counts branch_stock_pctile_counts 該檔的列(全欄位,讀取順序)+ 快照中繼資料 + 表在不在
                      (這段計算不看 d)
  price_levels        d + 該檔 K 線全欄位

上一次的輸出從哪裡拿:``branch_days``/``branch_pnl_est``/``branch_pctile_counts`` 就在上一次寫的
``stocks/chips/{id}.json`` 裡——記憶檔只記那份文字的雜湊與各段的位置,讀回來雜湊對得上才用
(另一個並行 export 改寫過、被截斷、被刪,一律當沒有記錄)。沿用的段**不解析**:直接切下那段
文字(``stock_parts.RawJSON``)原樣拼進這一次的 chips 檔(``compose_chips``,與整份 dumps 逐位元
相同);``branch_tags`` 要的分點名表只解析 ``names`` 那一小段。``price_levels`` 很小,直接存在
記憶檔(JSON 往返:鍵序保留、float 以 repr 往返,輸出逐位元相同)。

分點名:迴圈內只要發生過一次 ``_BranchNames`` 重讀(有查不到的 id),這一輪之後的分點段一律
不命中、記憶檔也不寫(重讀可能改了先前用過的名字);上一次記下的 id→名稱 在這一次開頭的
查表裡有任何一個不同或不見,分點段全部不命中。沒重讀 ⇒ 上一次每一列的 id 都在上一次的
查表裡 ⇒ 原始列相同時名字也相同,不會有「上一次是孤兒、這一次查得到」的列。

記憶檔:``config.DATA_DIR/export-memo/<輸出目錄路徑雜湊>.json``(一個輸出目錄一份,每次整份
覆寫,~數 MB;超過 7 天沒更新的別份順手刪掉)。``RADAR_EXPORT_MEMO=0`` 關掉(照舊全算,也不寫)。
"""
from __future__ import annotations

import hashlib
import json
import marshal
import os
import sys
import time
from pathlib import Path

from .. import config

MEMO_VERSION = 1
ENV_FLAG = "RADAR_EXPORT_MEMO"
STALE_SECONDS = 7 * 24 * 3600
_PKG_ROOT = Path(__file__).resolve().parents[1]   # radar/


def memo_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "1").strip() != "0"


_SALT: str | None = None


def code_salt() -> str:
    """整個 radar 套件的原始碼 + Python 版本 + MEMO_VERSION:程式改了(含任何常數)就全部不命中。"""
    global _SALT
    if _SALT is None:
        h = hashlib.blake2b(digest_size=16)
        h.update(f"{MEMO_VERSION}|{sys.version}".encode())
        for p in sorted(_PKG_ROOT.rglob("*.py")):
            h.update(p.relative_to(_PKG_ROOT).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
        _SALT = h.hexdigest()
    return _SALT


def digest(*parts) -> str:
    """parts 只能是 marshal 能序列化的值(tuple/list/dict/str/int/float/bool/None/bytes)。
    版本 2:同值同型別 → 同位元組(版本 3 起有參照與駐留旗標,同值可能不同位元組)。"""
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        b = marshal.dumps(part, 2)
        h.update(len(b).to_bytes(8, "little"))
        h.update(b)
    return h.hexdigest()


def text_digest(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


def memo_path(out: Path) -> Path:
    key = hashlib.blake2b(str(Path(out).resolve()).encode("utf-8"), digest_size=8).hexdigest()
    return Path(config.DATA_DIR) / "export-memo" / f"{key}.json"


class ExportMemo:
    """一次 export 的記憶:開頭載入上一次的(``old``),迴圈裡記這一次的(``new``),收尾 ``save``。

    entry(每檔一筆,JSON):``b`` 分點原始列摘要、``c`` K 線摘要、``p`` 分位列摘要、
    ``x`` 這一次寫出的 chips 文字摘要、``l`` price_levels 輸出。
    """

    def __init__(self, out: Path, *, d: str, names: dict[int, str], enabled: bool | None = None):
        self.enabled = memo_enabled() if enabled is None else enabled
        self.path = memo_path(out)
        self.d = d
        self.salt = code_salt() if self.enabled else ""
        self._names = dict(names)          # 這一次開頭的查表(收尾存成下一次的基準)
        self.old: dict[str, dict] = {}
        self.new: dict[str, dict] = {}
        self.names_ok = False
        self.stats = {"loaded": 0, "branch": 0, "pnl": 0, "pctile": 0, "levels": 0,
                      "chips_bad": 0, "load_secs": 0.0}
        if self.enabled:
            t0 = time.perf_counter()
            self._load(names)
            self.stats["load_secs"] = time.perf_counter() - t0

    def _load(self, names: dict[int, str]) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        # 資料日不同不整份作廢:分點/K 線/損益/價格位置的摘要本身含 d(換日一定不命中),
        # 分位計數不依賴 d(那張表 00:05 才換),14:05 換日那一輪照樣沿用。
        if (not isinstance(raw, dict) or raw.get("version") != MEMO_VERSION
                or raw.get("salt") != self.salt):
            return
        old_names = raw.get("names") or {}
        self.names_ok = all(names.get(int(k)) == v for k, v in old_names.items())
        self.old = raw.get("entries") or {}
        self.stats["loaded"] = len(self.old)

    def get(self, sid: str) -> dict | None:
        return self.old.get(sid) if self.enabled else None

    def record(self, sid: str, entry: dict) -> None:
        if self.enabled:
            self.new[sid] = entry

    def save(self, *, reloaded: bool) -> None:
        """整份覆寫(tmp + rename)。這一輪分點名重讀過 → 不寫、刪掉舊檔(下一次全算)。"""
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reloaded:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        doc = {"version": MEMO_VERSION, "salt": self.salt, "d": self.d,
               "names": {str(k): v for k, v in self._names.items()}, "entries": self.new}
        tmp = self.path.with_name(f"{self.path.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, self.path)
        now = time.time()
        for p in self.path.parent.iterdir():
            if p == self.path:
                continue
            try:
                if now - p.stat().st_mtime > STALE_SECONDS:
                    p.unlink()
            except OSError:
                pass


def read_chips_text(stock_dir: Path, sid: str, expected: str | None) -> str | None:
    """上一次寫的 chips 檔文字;內容摘要 ≠ ``expected``(或讀不到)→ None。"""
    if not expected:
        return None
    try:
        text = (stock_dir / "chips" / f"{sid}.json").read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return text if text_digest(text) == expected else None
