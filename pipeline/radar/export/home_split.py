"""首頁資料拆檔(docs/44 P2):``home/head.json`` + ``home/stocks.json``。

``radar.json`` 一檔同時服務首頁、分點頁(concentration)、自選頁(lists.armed)、盤中 worker、
多方榜建置器與期貨推播;首頁每次打開都整包下載,而預設分頁(多方榜)其實只讀表頭。
這裡把首頁要的東西拆成兩份:

* ``head``:``radar.json`` 扣掉 ``stocks`` 與首頁沒有讀的頂層鍵(``HOME_DROPPED_TOP``)。
* ``stocks``:``radar.stocks`` 逐檔投影——丟掉首頁卡片沒有畫的欄位(``HOME_DROPPED_STOCK``),
  ``warrant`` 只留卡片畫的三個鍵。順序、其餘每一個值都與 ``radar.stocks`` 相同。

兩份都帶同一個 ``generated_at``:前端先抓 head,等到要畫股票的分頁才抓 stocks,兩個檔若
來自不同輪 export(mid-backfill 並行匯出)就靠它對不上而重抓。``radar.json`` 過渡期**照寫、
逐位元不變**;這個模組只是投影,不碰資料庫,也不改 radar 本身。

鍵名清單與 ``web/lib/homeLoad.ts`` 的 ``HOME_DROPPED_STOCK``/``HOME_WARRANT_KEYS`` 必須一致
(``test_home_split.py`` 讀 TS 檔核對)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .stock_parts import dumps_compact, write_atomic

HOME_VERSION = 1

# radar.json 的頂層鍵裡首頁完全沒有讀的:concentration 是分點頁的集中度榜(分點頁讀
# radar.json 本尊),summary_text / score_list_meta 前端沒有任何地方讀。
HOME_DROPPED_TOP: tuple[str, ...] = ("concentration", "summary_text", "score_list_meta")

# radar.stocks 每一檔裡首頁(StockCard / ThemeGroupedList / 多方榜族群 / 期貨股名)沒有畫的欄位。
# technical 是最大的一塊(含 reasons/risks 兩個陣列);其餘是個股頁才顯示的數字。
HOME_DROPPED_STOCK: tuple[str, ...] = (
    "technical", "volume_lots", "transactions", "margin_chg_lots", "chg5_pct",
    "pocket_score", "pocket_families",
)

# StockCard 在沒有評分時畫的三個權證欄位;其餘(put_*、call_volume、call_avg20、put_call_ratio)
# 只有個股頁用。
HOME_WARRANT_KEYS: tuple[str, ...] = ("call_turnover", "call_turnover_ratio", "call_count")


def home_stock(s: dict) -> dict:
    """一檔的首頁投影:鍵序照原樣,只丟不加。"""
    out: dict[str, Any] = {}
    for k, v in s.items():
        if k in HOME_DROPPED_STOCK:
            continue
        if k == "warrant" and isinstance(v, dict):
            v = {wk: v[wk] for wk in HOME_WARRANT_KEYS if wk in v}
        out[k] = v
    return out


def home_projection(radar: dict) -> dict:
    """整份 radar 的首頁投影(= head ⊕ stocks 接回來應該得到的東西)。"""
    out: dict[str, Any] = {}
    for k, v in radar.items():
        if k in HOME_DROPPED_TOP:
            continue
        out[k] = [home_stock(s) for s in v] if k == "stocks" else v
    return out


def split_home(radar: dict) -> tuple[dict, dict]:
    """拆成 (head, stocks_file)。兩份都帶 version 與同一個 generated_at。"""
    head: dict[str, Any] = {"version": HOME_VERSION}
    for k, v in radar.items():
        if k == "stocks" or k in HOME_DROPPED_TOP:
            continue
        head[k] = v
    stocks_file = {
        "version": HOME_VERSION,
        "data_date": radar["data_date"],
        "generated_at": radar["generated_at"],
        "stocks": [home_stock(s) for s in radar.get("stocks", [])],
    }
    return head, stocks_file


def merge_home(head: dict, stocks_file: dict) -> dict:
    """接回一份(鍵序同 radar:stocks 放最後面,其他照 head)。兩份不是同一輪就擲例外。"""
    if head.get("generated_at") != stocks_file.get("generated_at"):
        raise ValueError(
            f"home head/stocks generated_at mismatch: "
            f"{head.get('generated_at')!r} vs {stocks_file.get('generated_at')!r}")
    out = {k: v for k, v in head.items() if k != "version"}
    out["stocks"] = list(stocks_file["stocks"])
    return out


def write_home(out: Path, radar: dict) -> dict[str, int]:
    """寫 ``home/stocks.json`` 再寫 ``home/head.json``(各自 tmp+rename)。回傳兩檔的 raw bytes。

    stocks 先寫:head 到了而 stocks 還是上一輪的,前端靠 generated_at 對不上會重抓;反過來
    (stocks 新、head 舊)也一樣。沒有一刻會讀到半個檔。
    """
    head, stocks_file = split_home(radar)
    home_dir = out / "home"
    home_dir.mkdir(parents=True, exist_ok=True)
    stocks_text = dumps_compact(stocks_file)
    head_text = dumps_compact(head)
    write_atomic(home_dir / "stocks.json", stocks_text)
    write_atomic(home_dir / "head.json", head_text)
    return {"head": len(head_text.encode("utf-8")), "stocks": len(stocks_text.encode("utf-8"))}
