# Trever Radar — 專案核心決策(AI 開發必讀)

> 本檔是給 AI 輔助開發時每次必讀的最小上下文。保持在 150 行以內。
> 詳細規格請依任務只讀對應文件,不要整包丟給模型。

## 產品一句話

台股籌碼異常與盤中發動訊號偵測工具:盤後找籌碼,盤中看發動。只給觀察訊號與風險提醒,不推薦買賣、不自動下單。

## 不可違反的原則

1. 私人使用,≤10 人,邀請制,無金流、無多租戶、無公開註冊。
2. **目前零花費**:只用免費資料與免費雲(GitHub Actions + Cloudflare Pages/Access)。
3. 每個訊號必須能輸出「人看得懂的觸發理由 + 風險提醒」,不能只有分數。
4. 不做自動下單。元大 API 最早 V3、僅個人輔助、手動確認。
5. 不過度工程:V1-Free 無任何常駐伺服器、無雲端 DB 服務、無登入程式碼。
6. 訊號文字用規則模板產生,不用 LLM(省 token、可回測、可重現)。

## 技術棧(2026-07-06 定案,取代舊 Laravel 方案)

- 管線:Python 3.11 + requests + pandas + SQLAlchemy Core + SQLite(`pipeline/`)
- 前端:Next.js 15(App Router)+ TypeScript + React,**`output: 'export'` 靜態輸出**(零伺服器原則不變)+ lightweight-charts(`web/`)(2026-07-06 依使用者指定由 Vue 改為 Next.js)
- 前端資料 = 管線每晚產出的靜態 JSON(`web/public/data/`),無後端 API
- 排程:GitHub Actions cron(台北 17:30/21:00);`main` push 會用現有 DB 匯出 JSON、build、deploy,但跳過資料匯入
- 部署:Cloudflare Pages + Access(email 白名單登入);Vercel 為備選
- 本機執行:`cd pipeline; .venv\Scripts\python -m radar <指令>`

## 資料源(V1-Free)

| 資料 | 來源 | 備註 |
|---|---|---|
| 日K+權證每日成交 | TWSE `MI_INDEX`(type=ALL)/ TPEx 日成交 | 全市場單日一請求;近一年回補用 `backfill` |
| 上市以來深歷史日K | FinMind `TaiwanStockPrice`(免費,匿名可用,每檔一請求)| `deep-backfill`;免費註冊 token(RADAR_FINMIND_TOKEN)提高額度到約 600 req/hr |
| 法人買賣超 | TWSE `T86` / TPEx | |
| 融資融券 | TWSE `MI_MARGN` / TPEx | |
| 注意/處置 | TWSE/TPEx 公告 | |
| 還原價 | FinMind `TaiwanStockDividendResult` 免費資料自算 `adj_factor` | `TaiwanStockPriceAdj` 需付費,不用 |
| **分點** | **延後**(需 FinMind 贊助,月數百元,使用者尚未同意花費) | 04 規格保留,程式留插槽 |
| 盤中(V2) | Fugle;worker 跑使用者自己電腦 | 屆時再議 |

## 評分(V1-Free 權重)

權證 30% + 技術 30% + 法人/融資 25% + 題材 15% − 風險扣分。
branch(分點)分數插槽回傳 null → 權重自動歸一化。規則細節一律看 04。

## 模組邊界(改 code 時只讀對應模組)

- `pipeline/radar/providers/*` — 各資料源抓取+解析(一源一檔,回傳 DTO dataclass)
- `pipeline/radar/db.py` + `schema.py` — SQLAlchemy Core 表定義與 upsert
- `pipeline/radar/compute/*` — 指標、評分與績效回填(純函式,golden-file 測試);技術指標在 `compute/indicators.py`,綜合分在 `compute/scores.py`,後續報酬在 `compute/performance.py`
- `pipeline/radar/export/*` — JSON 產出;目前包含 radar/meta、榜單聯集個股 K 線、權證榜與個股權證資料
- `pipeline/radar/cli.py` — 指令入口
- `web/app/*` — Next.js 頁面;`web/components/*` — 元件;`web/lib/*` — JSON 讀取與格式化

## 文件地圖(依任務讀)

00 藍圖總表|01 產品定位|02 版本範圍與驗收|03 資料源評估|04 全部評分規則|05 資料表|06 架構(部署章節已被 12 取代)|07 前端頁面|08 排程流程|09 籌碼K線|10 資安法規|11 AI 開發流程|**12 零成本修訂(現行架構)**|13 分點排行與追蹤(規格備妥,卡付費資料)|**STATUS(目前進度,單一真相)**|../DEPLOY(部署)

## 目前狀態(2026-07-08,細節看 STATUS.md)

已上線 https://radar.techtrever.com,GitHub Actions 每交易日自動更新,`main` push 也會正式部署。管線(日K/權證主檔/權證彙總/法人/融資券/產業別/雙軌歷史回補/還原因子 CLI/技術指標/盤後綜合分/績效回填)與前端(族群資金流+熱門/爆量/強勢/權證/綜合榜+個股 K 線+週月K+MA/布林/副圖+技術摘要+個股權證 Tab)完成。**下一步:題材分數接入綜合評分,以及探索頁/自選股/觀察價與失效價。**

## 已做的關鍵取捨(不要翻案,除非使用者同意)

1. 零花費 → 分點以免費公開頁裁剪匯入,完整分點統計/付費資料延後;不做 TWSE bsr CAPTCHA 破解。
2. Laravel/PostgreSQL/VM 方案廢止,改 Python+SQLite+靜態 JSON(理由見 12 §3)。
3. V1 不做盤中;V2 盤中 worker 跑使用者本機。
4. W 底/頸線型態辨識不做,用「N 日新高/箱型上緣突破」替代。
5. 權證分點僅抓上市權證熱門標的龍頭權證;上櫃權證無免費來源,不硬做。
6. 前端無伺服器程式碼;登入交給 Cloudflare Access(2026-07-07 使用者決定先不開、網站暫公開,靠 noindex/robots.txt 低調;要分享或恢復私有時照 DEPLOY.md §4 補上)。
7. SQLite 為唯一真相;JSON 是產出物,可隨時重建。
8. 首頁「綜合」榜使用 `daily_scores.final`;權證分/技術分/法人融資分已接入,題材分暫為 NULL 並自動重分配權重。
9. 技術指標與績效回填必須用還原價:`adj_price = price * adj_factor`;`adj_factor` 由 `python -m radar compute-adjustments --ids/--top/--all` 補,尚未全市場自動排程。
