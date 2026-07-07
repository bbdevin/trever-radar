# 專案狀態(2026-07-07)

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | 公開網址、noindex + robots.txt;Access 未開(使用者決定,要鎖照 DEPLOY.md §4) |
| 自動排程 | GitHub Actions 每交易日 17:30 / 21:00(台北)抓資料 → 建站 → 部署;`main` push 會直接用現有 DB 匯出 JSON → 建站 → 部署 |
| Repo | github.com/bbdevin/trever-radar(私有) |
| DB | SQLite,Actions cache 續存 + release `db-backup` 週備份(週五/手動觸發時) |

## 已完成 ✅

### 資料管線(pipeline/,Python + SQLite)
- [x] TWSE/TPEx 日K + 權證每日成交(全市場,每日 2 請求)
- [x] 法人買賣超(T86 / TPEx insti)、融資融券、匯入紀錄與健檢基礎(import_logs)
- [x] `backfill`:官方端點回補近 240 交易日(已完成)
- [x] `deep-backfill`:FinMind 上市以來全歷史(每檔 1 請求;榜單股已拉,全市場待跑)
- [x] `import-stock-info`:官方產業別(FinMind TaiwanStockInfo)
- [x] `import-warrant-master`:權證主檔(TWSE t187ap37_L + TPEx OpenAPI;標的/履約價/行使比例/到期日;TWSE 以名稱反查代號,匹配率 94.5%)
- [x] `aggregate-warrants`:warrant_stock_daily 彙總(認購/認售金額量檔數,排除牛熊證;已回填 240 日,每晚增量)
- [x] `export-json`:radar/meta/個股 K 線 JSON + 權證異動榜 + 個股權證 60 日趨勢/熱門權證明細
- [x] `compute-adjustments`:用 FinMind `TaiwanStockDividendResult` 免費資料計算 `daily_prices.adj_factor`(除權息前後價比累乘;已用 2330 實測)
- [x] `compute-indicators`:以還原價計算 MA5/10/20/60、RSI14、KD、MACD、20日新高、60日箱型、ADV20、volume_ratio、tech_score、reasons/risks
- [x] `compute-scores`:盤後綜合分數(權證30/技術30/法人25 加權,分項缺資料自動重分配權重;風險扣分:短線過熱/爆量長上影/開高走低/RSI過熱/外資連賣/融資過熱;法人買超設佔成交量1%顯著性門檻)→ `daily_scores` + 理由/風險 JSON;首頁「綜合」榜(預設 tab)
- [x] upsert 只更新帶入欄位(防止日常匯入洗掉補充欄位)
- [x] SQLite WAL + busy timeout(回補與匯出可並行)

### 前端(web/,Next.js 15 靜態輸出)
- [x] 今日雷達:市場總覽卡、**族群資金流面板**(產業別金額佔比 / vs20日均 / 廣度 / 龍頭)、**熱門/爆量/強勢/權證四榜**
- [x] 股票卡:權證認購成交金額、20日倍數、購售比、成交檔數摘要
- [x] 個股頁:上市以來 K 線 + 成交量(lightweight-charts)、區間切換 1月/3月/1年/5年/全部、**權證 Tab**(60 日認購/認售金額趨勢 + 當日熱門權證明細)
- [x] 個股頁 K 線疊加 MA5/20/60,下方顯示技術分、MA20/60、RSI14、量比與觸發理由
- [x] 現代 fintech UI:深色、玻璃頂欄、手機底部導航、SVG 圖示、Manrope 數字字體、骨架屏、RWD 375–1440
- [x] 台股慣例紅漲綠跌、免責聲明常駐

### 基礎設施
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域
- [x] `main` push 觸發正式部署;push 事件跳過資料匯入,只用 cache/release DB 匯出 JSON、build、deploy
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)

## 未完成(依優先序)

1. **訊號績效回填**(daily_scores 的 1/3/5/10/20 日後續報酬 → 驗證權重與門檻)
2. 題材標籤(人工維護表)+ 題材熱度
3. 探索頁、自選股、觀察價/失效價
4. `deep-backfill --all` 全市場深歷史 + `compute-adjustments --all` 分批補全市場還原因子(使用者本機或雲端跑一晚;注意 FinMind 600 req/hr 額度)
5. **分點排行與追蹤**(2026-07-07 使用者需求,完整規格已寫於 **docs/13**:手動種子名單〔富邦新店/凱基三多/元大大天母/永豐金內湖/凱基信義〕+ 可信度演算法自動入選 + 今日動向表 + 權證分點視角)——**卡在資料:需 FinMind 贊助月付約 NT$300–600,使用者點頭即開工**
6. V2 盤中(Fugle + 本機 worker)

## 已知債務 / 注意

- 個股 JSON 一檔約 0.5MB(全歷史);擴到數百檔時改「預設 5 年 + 按需載入」
- 權證榜目前是「認購成交金額 / 20 日均值」的異動排序,尚不是 04 定義的完整 0–100 權證分;完整分數與 reasons/risks 等評分模組一起做
- 權證 warrant_daily 約 1,000 萬列/年增速;彙總表已建,依 05 規劃明細僅留 2 年(清理排程未寫)
- 還原價資料層已完成,但尚未接 nightly 全市場自動跑;目前用 `compute-adjustments --ids/--top/--all` 手動或分批補。`TaiwanStockPriceAdj` 是付費資料,本案改用免費 `TaiwanStockDividendResult` 自算
- 技術指標已接 nightly `compute-indicators --all`;若某些股票尚未補還原因子,會先以 `adj_factor=1` 計算,之後補因子再重算即可
- 已下市權證不在主檔,kind 靠代號尾碼推斷可能誤標(認售尾碼不只 P,還有 T/Q/S 等)→ 歷史認購/認售比略失真;認售佔比極低,影響小
- 評分門檻(65 分觀察線、法人 1% 顯著性、權證倍數分段)為 04 起始值,待訊號績效回填後校準;目前寧缺勿濫,達標日常 0–5 檔屬預期
- `compute-adjustments` 逐列 UPDATE,跑 --all 會慢;改 executemany 批次後再跑全市場
- Actions 有 Node 20 → 24 的 deprecation 警告(actions 版本升級,無急迫)
- 本機 dev 與雲端 DB 已分岔:雲端為正式真相,本機僅開發;push 部署會從 Actions cache/release DB 產出線上 JSON

## 最近完成

- 2026-07-07 `842b4e0 feat: add warrant radar UI`:首頁新增權證榜,股票卡/個股頁接上權證摘要、趨勢與熱門權證明細。
- 2026-07-07 `ed363b1 ci: deploy site on main push`:正式分支 push 會觸發 Cloudflare Pages 部署;已確認 GitHub Actions `nightly-radar` push run 成功。
- 2026-07-07 還原價資料層:新增 `daily_prices.adj_factor`、SQLite additive migration、`compute-adjustments` CLI、單元測試;2330 實測 6 筆除息事件/8031 日價列更新成功。
- 2026-07-07 技術指標資料層/UI:新增 `indicators_daily`、`compute-indicators`、技術分 reasons/risks、MA5/20/60 K 線疊線與個股頁技術摘要;本機 Top80 實算 18.5 萬列成功。
