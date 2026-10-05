"""個股 JSON 拆檔(docs/44 P1,§3.2):核心 + K 線歷史(雜湊檔名)+ 籌碼區段。

只換包裝,不改任何值。``split_stock_payload`` 把今天的單一 payload 拆成三份,
``merge_stock_parts`` 把三份接回;兩者互為反函式——接回來的 dict 必須與原 payload
深度相等(前端 ``web/lib/stockParts.ts`` 的 ``mergeStockParts`` 是同一條規則的 TS 版,
node 測試用這裡拆出來的真實資料驗它)。

這個模組刻意不碰資料庫,也不知道「聯集」是什麼:呼叫端決定要不要給 ``cut``。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

PARTS_VERSION = 1
HIST_VERSION = 1
CHIPS_VERSION = 1

# 從舊單一檔搬去 chips 檔的四個鍵。順序 = 舊 payload 裡的插入順序(branch_pnl_est 原本
# 就是最後才 setdefault 進去的),合併時照這個順序放回,舊檔與合併結果連鍵序都一樣。
CHIPS_KEYS: tuple[str, ...] = (
    "branch_history", "branch_pctile_counts", "branch_tags", "branch_pnl_est",
)

# 新檔一律緊湊序列化;舊單一檔維持 json_export 原本的 ``json.dumps(payload, ensure_ascii=False)``。
_COMPACT = {"ensure_ascii": False, "separators": (",", ":")}


def dumps_compact(obj: Any) -> str:
    return json.dumps(obj, **_COMPACT)


def hist_cut(d: str) -> str:
    """K 線歷史的切點:資料日前兩年的 1/1(含,cut 當天起留在核心)。

    為什麼是前兩年而不是前一年(docs/44 §3 草案):核心要裝得下 K 線分頁的「1 年」
    區間(240 根)再加年線的 240 根回看,否則 1 月初那幾週 1 年區間的年線會在 hist
    到之前斷掉。前兩年 1/1 起至少 ~490 根,剛好夠。
    """
    return f"{date.fromisoformat(d).year - 2}-01-01"


def hist_file_name(sid: str, hist_text: str) -> str:
    """``hist/{id}.{sha256 前 8 碼}.json``:內容不變 → 檔名不變 → 不重寫、可長快取。"""
    digest = hashlib.sha256(hist_text.encode("utf-8")).hexdigest()[:8]
    return f"hist/{sid}.{digest}.json"


def chips_file_name(sid: str) -> str:
    return f"chips/{sid}.json"


def split_stock_payload(payload: dict, *, cut: str | None) -> dict:
    """把一檔的完整 payload 拆成 core / hist / chips。

    ``cut`` 為 None 時不切 K 線(非聯集股:600 根滑動視窗,切了會天天換雜湊)。
    有 cut 但沒有任何一根早於 cut(新上市)→ 同樣沒有 hist。

    回傳 ``{"core", "hist", "hist_text", "hist_name", "chips"}``:hist 為 None 時
    ``hist_text``/``hist_name`` 也是 None。``hist_text`` 已序列化,呼叫端直接寫檔,
    檔名雜湊與寫入內容保證是同一份文字。
    """
    sid = payload["id"]
    core = {k: v for k, v in payload.items() if k not in CHIPS_KEYS}
    chips = {k: payload[k] for k in CHIPS_KEYS if k in payload}

    hist = hist_text = hist_name = None
    candles = payload.get("candles") or []
    if cut is not None and candles:
        idx = 0
        while idx < len(candles) and candles[idx]["t"] < cut:
            idx += 1
        if idx > 0:
            hist = {
                "version": HIST_VERSION, "id": sid, "cut": cut,
                "bars": idx, "candles": candles[:idx],
            }
            hist_text = dumps_compact(hist)
            hist_name = hist_file_name(sid, hist_text)
            core["candles"] = candles[idx:]

    core["parts"] = {
        "version": PARTS_VERSION,
        "hist": (
            {"file": hist_name, "bars": hist["bars"], "cut": cut,
             "first": hist["candles"][0]["t"]}
            if hist is not None else None
        ),
        "chips": {"file": chips_file_name(sid), "keys": list(chips.keys())},
    }
    return {"core": core, "hist": hist, "hist_text": hist_text,
            "hist_name": hist_name, "chips": chips}


def merge_stock_parts(core: dict, hist: dict | None, chips: dict | None) -> dict:
    """三份接回一份(Python 版,給 ``--verify-split`` 與測試用)。

    鍵序刻意與舊 payload 一致:core 的鍵照原序、chips 四鍵放到 ``branches`` 之後
    ``warrant`` 之前(branch_pnl_est 例外,它在舊檔裡排在 futures 之前)。深度相等
    不看鍵序,這只是讓 ``json.dumps`` 出來的文字也對得上,除錯時好 diff。
    """
    out: dict = {}
    chips = chips or {}
    for k, v in core.items():
        if k == "parts":
            continue
        if k == "candles" and hist is not None:
            v = list(hist["candles"]) + list(v)
        out[k] = v
        if k == "branches":
            for ck in ("branch_history", "branch_pctile_counts", "branch_tags"):
                if ck in chips:
                    out[ck] = chips[ck]
    if "branch_pnl_est" in chips:
        # 舊 payload:branch_pnl_est 在 directors_latest 之後、futures 之前。
        if "futures" in out:
            futures = out.pop("futures")
            out["branch_pnl_est"] = chips["branch_pnl_est"]
            out["futures"] = futures
        else:
            out["branch_pnl_est"] = chips["branch_pnl_est"]
    return out


def read_merged_stock(stock_dir: Path, sid: str) -> dict | None:
    """從磁碟讀一檔並接回(有新佈局讀新佈局,否則讀舊單一檔;都沒有回 None)。"""
    core_path = stock_dir / "core" / f"{sid}.json"
    if core_path.exists():
        core = json.loads(core_path.read_text(encoding="utf-8"))
        parts = core.get("parts") or {}
        hist = chips = None
        if parts.get("hist"):
            hist = json.loads((stock_dir / parts["hist"]["file"]).read_text(encoding="utf-8"))
        if parts.get("chips"):
            chips = json.loads((stock_dir / parts["chips"]["file"]).read_text(encoding="utf-8"))
        return merge_stock_parts(core, hist, chips)
    legacy = stock_dir / f"{sid}.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    return None


class StockPartsWriter:
    """export_json 個股迴圈用的寫檔器:core/chips 每檔都寫,hist 只在內容變了才寫,
    並在收尾時刪掉本輪沒寫到的 hist 檔、寫 ``hist/index.json``。"""

    def __init__(self, stock_dir: Path):
        self.stock_dir = stock_dir
        (stock_dir / "core").mkdir(exist_ok=True)
        (stock_dir / "chips").mkdir(exist_ok=True)
        (stock_dir / "hist").mkdir(exist_ok=True)
        self.index: dict[str, dict] = {}
        self.hist_written = 0
        self.hist_reused = 0

    def write(self, parts: dict) -> None:
        core = parts["core"]
        sid = core["id"]
        (self.stock_dir / "core" / f"{sid}.json").write_text(dumps_compact(core), encoding="utf-8")
        (self.stock_dir / "chips" / f"{sid}.json").write_text(
            dumps_compact({"version": CHIPS_VERSION, "id": sid, **parts["chips"]}), encoding="utf-8")
        if parts["hist"] is None:
            self._drop_hist(sid, keep=None)
            return
        name = parts["hist_name"]
        target = self.stock_dir / name
        if target.exists():
            self.hist_reused += 1
        else:
            target.write_text(parts["hist_text"], encoding="utf-8")
            self.hist_written += 1
        self._drop_hist(sid, keep=target.name)
        self.index[sid] = {
            "file": name, "hash": target.name.split(".")[1], "bars": parts["hist"]["bars"],
            "cut": parts["hist"]["cut"], "first": parts["hist"]["candles"][0]["t"],
        }

    def _drop_hist(self, sid: str, keep: str | None) -> None:
        for p in (self.stock_dir / "hist").glob(f"{sid}.*.json"):
            if p.name != keep:
                p.unlink()

    def finish(self) -> None:
        """退出聯集(或不再匯出)的 id:舊 hist 檔刪掉,不讓 wrangler 一直上傳。"""
        for p in (self.stock_dir / "hist").glob("*.json"):
            if p.name == "index.json":
                continue
            sid = p.name.split(".")[0]
            if sid not in self.index:
                p.unlink()
        (self.stock_dir / "hist" / "index.json").write_text(
            dumps_compact(dict(sorted(self.index.items()))), encoding="utf-8")


def size_entry(payload: dict) -> dict[str, int]:
    """每個頂層鍵的 raw bytes(緊湊序列化,UTF-8)+ 總計,給 ``--size-report``。"""
    sizes = {k: len(dumps_compact(v).encode("utf-8")) for k, v in payload.items()}
    sizes["_total"] = len(dumps_compact(payload).encode("utf-8"))
    return sizes


def summarize_sizes(entries: dict[str, dict[str, int]], union_ids: set[str]) -> dict:
    """分「聯集」「其餘」兩組(平均會誤導,docs/44 §3):每鍵 p50/p90/max/mean。"""
    def stats(values: list[int]) -> dict:
        if not values:
            return {"n": 0}
        s = sorted(values)
        pick = lambda q: s[min(len(s) - 1, int(round(q * (len(s) - 1))))]
        return {"n": len(s), "p50": pick(0.5), "p90": pick(0.9), "max": s[-1],
                "mean": round(sum(s) / len(s))}

    groups = {"union": [], "other": []}
    for sid, sizes in entries.items():
        groups["union" if sid in union_ids else "other"].append(sizes)
    out = {}
    for name, rows in groups.items():
        keys = sorted({k for r in rows for k in r})
        out[name] = {"stocks": len(rows),
                     "keys": {k: stats([r[k] for r in rows if k in r]) for k in keys}}
    return out
