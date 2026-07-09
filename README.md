# Trever Radar

盤後找籌碼,盤中看發動。台股籌碼異常與盤中發動訊號偵測工具(私人使用,≤10 人)。

> 本系統僅彙整公開市場資料供個人研究,非投資建議;訊號不保證獲利;投資人應自行判斷並承擔風險。

**正式站**:https://radar.techtrever.com — GitHub Actions 每交易日 17:30 / 21:00(台北)自動更新;`main` push 會用現有 DB 重建並部署前端,平常不需人工操作。

## 結構

- `docs/` — 產品與技術規格;**開發前先讀 `docs/project-context.md`,目前進度看 `docs/STATUS.md`**
- `pipeline/` — Python 資料管線(抓取 → SQLite → 匯出 JSON)
- `web/` — 前端(Next.js 15 靜態輸出 + lightweight-charts)
- `data/` — SQLite 與產出物(不進 git;雲端以 Actions cache + release 備份續存)
- `.github/workflows/` — 5 支自動管線(`daily-market`14:10/`daily-insti`16:10/`daily-branches`17:40+21:00/`data-backfill`01:10/`deploy`)+ Cloudflare Pages 部署;時間表單一真相見 `docs/08_scheduler_jobs.md` §0(見 `DEPLOY.md`)

## Pipeline 指令

```powershell
cd pipeline
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt

.venv\Scripts\python -m radar import-daily              # 匯入今日(台北時間)
.venv\Scripts\python -m radar import-daily --date 20260703
.venv\Scripts\python -m radar import-daily --datasets insti,margin
.venv\Scripts\python -m radar backfill --days 240       # 官方端點回補近一年
.venv\Scripts\python -m radar deep-backfill --top 30    # FinMind 上市以來全歷史(每檔一請求)
.venv\Scripts\python -m radar deep-backfill --all       # 全市場深歷史(建議設 token)
.venv\Scripts\python -m radar import-stock-info         # 產業別
.venv\Scripts\python -m radar compute-adjustments --ids 2330
.venv\Scripts\python -m radar compute-adjustments --top 60 --sleep 6.2
.venv\Scripts\python -m radar compute-indicators --ids 2330
.venv\Scripts\python -m radar compute-indicators --all
.venv\Scripts\python -m radar compute-scores              # 產生盤後綜合分
.venv\Scripts\python -m radar compute-performance         # 回填 daily_scores 後續報酬
.venv\Scripts\python -m radar export-json               # 產出前端 JSON(含四榜/個股K線/權證資料)
.venv\Scripts\python -m radar status                    # 匯入紀錄 + 各表筆數
```

資料公布時間:日K/權證 ~14:00 後、法人 ~16:00 後、融資券 ~16:30 後;尚未公布顯示 `empty`,重跑即補(upsert 冪等)。

`compute-adjustments` 使用 FinMind 免費的 `TaiwanStockDividendResult` 每檔一請求,把 `daily_prices.adj_factor` 補齊;`TaiwanStockPriceAdj` 是付費資料,不用。

FinMind token(免費註冊,600 req/hr):環境變數 `RADAR_FINMIND_TOKEN`(本機 `setx`;雲端已設 GitHub secret)。

## 前端開發

```powershell
cd web
npm install
npm run dev     # http://localhost:3000(讀 public/data 的 JSON,先跑 export-json)
npm run build   # 靜態輸出到 out/
```

## 部署

全自動,見 [DEPLOY.md](DEPLOY.md)。push `main` 會部署程式/UI 更新;手動重跑某階段:`gh workflow run daily-branches --repo bbdevin/trever-radar`(其餘同理換 workflow 名,見 `docs/08_scheduler_jobs.md` §0)。
