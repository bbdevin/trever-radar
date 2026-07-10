# 12 零成本架構修訂(2026-07-06,取代 06 的 V1 部署章節)

使用者決策:**開發階段零花費**。無 VM、無 FinMind 贊助。本文為現行架構,與 06 衝突處以本文為準。

## 1. 免費主機結論(回答「GitHub 或 Vercel 哪個好」)

兩者角色不同,搭配用,不是二選一:

| 角色 | 服務 | 為什麼 |
|---|---|---|
| 排程 + 運算(核心) | **GitHub Actions**(私有 repo 免費 2,000 分/月) | 每晚管線跑 5–10 分鐘,月用量 <300 分;Vercel 函式有秒級時限跑不了長管線 |
| 前端靜態站 | **Cloudflare Pages**(首選)或 Vercel Hobby(次選) | 皆免費;選 CF 因為可加 **Cloudflare Access**:免費 email 白名單登入(≤50 人),零登入程式碼,等於免費拿到「使用者管理」 |
| 資料庫 | **SQLite 單檔**(管線內)+ 靜態 JSON(前端讀) | 不用任何雲端 DB 服務 → 不受 Supabase 免費層休眠/500MB 限制;T+1 批次產品本質上不需要線上 DB |

> **2026-07-10 現況補充**:市場資料與評分的唯一真相仍是 SQLite;但自選股與 Google OAuth
> 已使用 Supabase 免費層作個人化服務。Supabase 不存市場資料,不改變靜態 JSON 架構。
> 後續範圍依 `docs/20_simplification_strategy.md`:保留跨裝置自選,不擴張成一般後端或假性資料安全閘門。

> **2026-07-10 私人測試/R2 決策**:見 `docs/21_private_beta_access_r2_plan.md`。
> Access 將保護 custom domain + production pages.dev + previews;R2 是 private object storage,
> 先存 SQLite verified snapshot,不是可直接查詢的資料庫,也不立即取代 Actions cache/Release。

註:GitHub Pages 不行(私有 repo 需付費方案);Vercel Hobby 條款限非商業用途(私人工具符合);GitHub Actions cron 可能延遲數分鐘~一小時,對晚間 T+1 資料無害,排 17:30 台北時間 + 失敗重試。

## 2. 架構(V1-Free)

```
GitHub Actions(每交易日 17:30 台北時間)
  └─ pipeline(Python 3.11 + SQLite)
      抓官方資料 → 入庫 → 指標 → 評分 → 產出 web/public/data/*.json
      → 部署前端+資料(wrangler pages deploy / vercel deploy)
      → SQLite 快取(actions/cache)+ 每週備份(Release asset)
使用者瀏覽器 → Cloudflare Access 登入 → Pages 靜態站(Vue 3 SPA)→ 讀 JSON
```

- **無伺服器程式碼**:前端互動(篩選、排序、分點切換)全在瀏覽器內對 JSON 運算;30 檔清單與單股 JSON 都是小檔。
- JSON 產出範圍:`watchlist.json`、`explore/*.json`、`stocks/{id}.json`(240 日 K + 指標 + 分數;僅產出候選池 ∪ 自選 ∪ 近 30 日曾入選,約 300 檔)、`meta.json`(資料日與健檢狀態)。
- SQLite 續存:actions/cache 為主;每週日 gzip 上傳 Release(單一 rolling release);兩者皆失時 `rebuild` 指令以節流模式重抓(每日一請求全市場端點,約一晚補完 240 日)。
- 開發階段(現在):管線在本機跑,同一套程式;推上 GitHub 後只是加 workflow yaml。

## 3. 技術棧變更(取代原 Laravel 定案)

| 原(06) | 新(本文) | 原因 |
|---|---|---|
| Laravel + Inertia + Vue 單體 | **Python 管線 + Next.js 15 靜態輸出(`output: 'export'`)** | 免費雲上沒有堪用的 PHP 常駐環境;批次產品不需要常駐後端;前端框架依使用者指定用 Next.js,但僅用其靜態輸出,不用 SSR/API routes(維持零伺服器) |
| PostgreSQL 16 | **SQLite**(SQLAlchemy Core,連線字串可換 PG) | 零服務;未來有預算換 Postgres 只改 DSN |
| Laravel Queue/Scheduler | GitHub Actions cron + Python 管線內部步驟鏈 | |
| Breeze 登入 | Cloudflare Access(email 白名單) | 零程式碼 |
| Telegram 通知 | 保留(Actions 內 curl 即可) | |

05 資料庫文件的表設計照用(SQLite 語法),warrant_daily/branch 裁剪策略照用。

## 3.5 深歷史策略(2026-07-06 補充)

- 官方整市場端點成本 = 每「天」2 請求 → 適合近 240 日回補(`backfill`),不適合抓到上市日(上萬請求)。
- **FinMind `TaiwanStockPrice` 免費解決深歷史**:每「檔」一請求即回傳上市以來全部日K(實測 2330 匿名一次拿 8,031 筆,1994-09-13 起)。`deep-backfill --ids/--top/--all`。
- 匿名有低額度;免費註冊 token 後約 600 req/hr → 全市場 ~2,000 檔一晚拉完。已含配額中斷續跑(已有深歷史的股票自動跳過)。
- 分工定案:**日常更新走官方(權威、含權證),深歷史走 FinMind(免費、省請求)**。

## 4. 範圍變更:分點免費裁剪版先行(2026-07-08 修訂)

無付費 → 全市場全量分點資料仍無合法穩定免費來源(TWSE bsr 有 CAPTCHA,不做破解;FinMind 分點屬贊助方案)。但已採用富邦 ebrokerdj 公開頁低頻抓「評分池前 80 檔的前 15 大買/賣超分點」,先把分點籌碼接進 V1:

- **V1-Free 評分改為**:分點 35% + 權證 20% + 技術 20% + 法人/融資 15% + 題材 10% − 風險扣分。題材尚未接入時回傳 null,權重自動歸一化。
- `branch_score` 目前使用連買、多分點同步、買方集中度、大戶淨流、反手倒貨風險;地緣/關鍵分點/可信度分數仍待資料累積與人工名單。
- 個股籌碼 K 線(09)的完整「分點足跡」與全量分點統計仍延後至有預算月付 FinMind 贊助或資料累積足夠時啟用;現階段前端先在綜合榜顯示分點分與分點理由。
- 04 的完整分點模型規格全部保留不刪——免費裁剪版是先行版本,不是最終上限。

## 5. V2 盤中的零成本路徑(預告)

盤中 worker 是常駐程式,免費雲跑不了 → 屆時跑在**你自己的電腦**(開盤時段本來就開機),訊號寫入同一資料流。屆時再議,不影響現在。

## 6. 帳號待辦(使用者本人操作,開發不被此擋)

1. GitHub 私有 repo(推程式後 Actions 才能跑)
2. Cloudflare 帳號(Pages + Access 設定,約 20 分鐘)
3. (選)Telegram Bot token(告警通知)
