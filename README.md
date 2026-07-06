# Trever Radar

盤後找籌碼,盤中看發動。台股籌碼異常與盤中發動訊號偵測工具(私人使用,≤10 人)。

> 本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。

## 結構

- `docs/` — 產品與技術規格(開發前先讀 `docs/project-context.md`)
- `pipeline/` — Python 資料管線(抓取 → SQLite → 指標 → 評分 → JSON 產出)
- `web/` — 前端(Vue 3 + Vite 靜態 SPA)(尚未建立)
- `data/` — SQLite 資料庫與產出物(不進 git)

## Pipeline 使用

```powershell
cd pipeline
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt

.venv\Scripts\python -m radar import-daily              # 匯入今日(台北時間)
.venv\Scripts\python -m radar import-daily --date 20260703
.venv\Scripts\python -m radar import-daily --datasets insti,margin
.venv\Scripts\python -m radar status                    # 匯入紀錄 + 各表筆數
```

資料集:`quotes`(日K+權證,TWSE 約 14:00 後)、`insti`(法人,約 16:00 後)、`margin`(融資券,約 16:30 後)。尚未公布顯示 `empty`,可重跑補齊(upsert 冪等)。
