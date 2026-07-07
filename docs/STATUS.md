# 專案狀態(2026-07-07)

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | 公開網址、noindex + robots.txt;Access 未開(使用者決定,要鎖照 DEPLOY.md §4) |
| 自動排程 | GitHub Actions 每交易日 17:30 / 21:00(台北)抓資料 → 建站 → 部署 |
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
- [x] `export-json`:radar/meta/個股 K 線 JSON
- [x] upsert 只更新帶入欄位(防止日常匯入洗掉補充欄位)
- [x] SQLite WAL + busy timeout(回補與匯出可並行)

### 前端(web/,Next.js 15 靜態輸出)
- [x] 今日雷達:市場總覽卡、**族群資金流面板**(產業別金額佔比 / vs20日均 / 廣度 / 龍頭)、**熱門/爆量/強勢三榜**
- [x] 個股頁:上市以來 K 線 + 成交量(lightweight-charts)、區間切換 1月/3月/1年/5年/全部
- [x] 現代 fintech UI:深色、玻璃頂欄、手機底部導航、SVG 圖示、Manrope 數字字體、骨架屏、RWD 375–1440
- [x] 台股慣例紅漲綠跌、免責聲明常駐

### 基礎設施
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)

## 未完成(依優先序)

1. **還原價**(除權息調整)→ 技術指標正確性的前提
2. **技術指標**(MA/RSI/KD/MACD/20日高/箱型)+ golden-file 測試
3. **評分模組**(04 規格;V1-Free 權重:權證30/技術30/法人融資25/題材15)→ 觀察清單 + 理由文字
4. 題材標籤(人工維護表)+ 題材熱度
5. 探索頁、自選股、訊號歷史回填
6. `deep-backfill --all` 全市場深歷史(使用者本機或雲端跑一晚)
7. 分點功能(等付費 FinMind 贊助決定,規格已備於 04/09)
8. V2 盤中(Fugle + 本機 worker)

## 已知債務 / 注意

- 個股 JSON 一檔約 0.5MB(全歷史);擴到數百檔時改「預設 5 年 + 按需載入」
- 權證 warrant_daily 約 1,000 萬列/年增速;彙總表已建,依 05 規劃明細僅留 2 年(清理排程未寫)
- 已下市權證不在主檔,kind 靠代號尾碼推斷可能誤標(認售尾碼不只 P,還有 T/Q/S 等)→ 歷史認購/認售比略失真;認售佔比極低,影響小
- Actions 有 Node 20 → 24 的 deprecation 警告(actions 版本升級,無急迫)
- 本機 dev 與雲端 DB 已分岔:雲端為正式真相,本機僅開發
