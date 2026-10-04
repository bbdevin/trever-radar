# 44 — 整體效能規劃(VPS 批次 × 網站)

> 2026-10-03 定稿草案。來源:兩位 Fable Planner 唯讀量測(VPS `mode=ro`、`dbstat`、`~/radar-cron.log` 09-16～10-03、正式站回應標頭;本機 `next build`、Playwright 390px CPU×4)。
> 使用者硬需求:**資料與每一個功能、每一個數字改前改後完全一致**;要做就做最好。
> 狀態:📝 規劃,待使用者核准 P0 維護窗。轉換工具與操作手冊(`docs/43`)由執行者準備中。

## 0. 結論

1. **使用者體感與 SQLite 無關。** 網站只讀 Cloudflare 靜態 JSON(線上 brotli,TTFB 0.3–0.4 s),登入／自選走 Supabase;多人同時使用不會互相拖慢。**不換資料庫引擎**(§5)。
2. **手機上真正慢的三件事**(網站端):
   - 每點一檔個股都是**整頁重新載入**(`<a href>` / `window.location.href`),每次重跑 ~1.1 MB(解壓後)程式、登入閘門、四個 Provider 查詢;中階手機約 1.3–1.65 s,每次導航重付。
   - **登入狀態重複查詢**:`useSession()` 14 個呼叫點各自查 `app_profiles` 兩次,首頁一次載入約 90 次 Supabase 請求;`AuthGate` 等 profile 回來前整頁空白(0.25–0.5 s)。
   - **資料永不快取**:`dataFetch` 一律 `cache: "no-store"`,同一檔看第二次、隔天再看都整包重抓;個股 JSON 大型股 57%(正式)是 K 線全歷史,`branch_history` 固定約 290 KB raw。自選頁每檔抓整包只為最後兩根 K 線。
3. **VPS 批次一個交易日 DB 鎖忙 5.5–7 小時**:①分點爬蟲 95–165 分(網路禮貌率,不是 I/O)②`export-json` 每次 14–34 分 × 6 輪 ≈ **2 小時**③`compute-branch-stats` 12 分④夜間分位 10–15 分⑤deploy 10 分。
4. **export 慢的主因 = 分點表儲存佈局**:逐檔 `branch_history` 要回表拿 `buy_lots`,40 檔樣本 11.2 s → 全市場 ≈ **11 分/輪**,佔 export 一半以上。**WITHOUT ROWID 轉換直接解這段**(估 1–2 分)。
5. **磁碟**:`radar.db` 實為 **9.03 GB**(不是 5.5),磁碟剩 3.4 GB;分點表家族 6.13 GB(68%,PK 索引 42% 是頁分裂空洞),`daily_prices` 1.49 GB。`docs/29` 的「`indicators_daily` 52%」已過時(現 68 MB)。轉換後估 **6.0–6.5 GB**,但每天仍長約 14 MB,**12–15 個月後再撞牆**,「PC 來回壓實」要變年度例行,或由使用者決定權證分點列保留天數。**2026-10-04 已定案**(§6.4):權證分點列保留 150 個交易日,與 `warrant_daily` 同一條線;個股/ETF 列永久保留。過期列刪除後頁面進 freelist 重用,2027-02 消化完積壓後每天淨成長約 **6–7 MB**(只剩個股列)。

## 1. 分期總表

| 階段 | 內容 | 預期效果 | 需你核准 | 影響範圍 |
|---|---|---|---|---|
| **W-P0** 網站(純前端) | ①登入狀態單例 ②站內導航改客戶端換頁(`next/link`/`router.push`,個股頁 `key={id}`)③`_headers` 讓 `/_next/static/*` 一年快取 ④正式站基準量測 | 每次換頁省 1–2 s(中階手機);首頁 Supabase 請求 ~90 → 1 | 否(一般前端修正) | 只動 `web/` |
| **D-P0** 維護窗(資料庫) | 離線把 `branch_trades_raw` + `daily_prices` 轉 WITHOUT ROWID、丟 1.33 GB 覆蓋索引、壓實;`page_size`/`ANALYZE` 各自以基準決定 | export 每輪 −9～−10 分(一天 −1 小時);夜間分位 −5～−8 分;9.03 → 6–6.5 GB | **是**(正式 DB 重建 + schema 變更 + 停機窗) | VPS 停寫一段時間,網站照常 |
| **D-P0.5** 同批程式 | `db.py` 連線 PRAGMA(`synchronous=NORMAL`、`cache_size=-65536`、`mmap 256MB`;`temp_store` 維持 FILE);`upsert()` 改 executemany;export 分段計時 log | `compute_all` 寫入 212 s → 40–60 s;寫入段 −20～−40% | 否 | 只動程式,不改檔案格式 |
| **P1** 資料格式拆檔(前後端一起) | 見 §3:個股 JSON 拆「核心＋K線歷史(內容雜湊檔名,一年快取)＋籌碼區段」,每輪只重算有變動的區段;`separators` 去空白、移除前端沒用到的 `af`;`no-store` → `no-cache`(304) | 一天 export ~2 h → ~35–45 分;手機首屏下載 0.5–1.5 MB raw → ~100 KB;重複看同一檔近乎 0 下載 | **格式請你過目**;Worker 規則需資安審查 + 核准 | 前端先上雙讀 → VPS 切格式 → Worker |
| **P1** Worker 驗證優化 | 同時多個請求只查一次 Supabase;JWKS 本地驗簽;profile 快取 5 分 | 冷啟動每頁 −0.25～−0.5 s | **是 + 資安審查**(門鎖) | `cloudflare-data-worker/` |
| **P2** 觀察後再決定 | 個股分頁元件按需載入、點擊預抓、爬蟲段不持 DB 鎖、權證分點增量彙總、`radar.json` 瘦身、權證分點列保留天數 | 邊際 | 部分需核准 | — |

**順序**:W-P0(現在就能做,與資料庫無關)∥ D-P0 工具準備 → D-P0 維護窗 → 觀察一週數字 → P1。**一個維護窗只換一個高風險零件**:D-P0 窗內不順手做 P1 拆檔。

## 2. D-P0 維護窗(細節見 `docs/43`)

- **傳輸不走 Google Drive**(只剩 2.4 GiB):VPS 持鎖 → `wal_checkpoint(TRUNCATE)` → `integrity_check` → gzip(~2.1 GB)+ sha256 → PC 經 ssh 拉回(PC D 槽 793 GB、已有 rclone/ssh)。
- **PC 上**:轉換 → 一致性驗證 → 速度比對(小快取模擬 VPS;逐檔查詢 + **日期切片查詢**,後者是聚集表可能變慢的地方,任一條退步 >2× 且修不好 → 該變數不上)。
- **換檔**:新檔 6–6.5 GB 與舊檔 9 GB 無法並存 → PC 確認舊檔 gz 雜湊一致並保留、Drive 有 10-03 週備份後,VPS 才刪舊檔,PC 串流新檔回去 → `integrity_check`、查詢計畫比對、唯讀跑一次 `export-json` 與現行網站資料逐檔比對 → 放鎖。
- **窗口**:週六 07:30 → 週一 14:10 之間任一段(備份 05:00、TDCC 06:30 之後)。
- **一致性保證**:逐表依主鍵排序的 sha256(含 3,238 萬列分點、1,028 萬列日價)、列數、DDL 除 `WITHOUT ROWID` 與被丟索引外逐字相同、完整 export 約 3,580 檔逐位元相同(排除 `generated_at`)。SQL 與佈局無關 → 同一份程式新舊庫都能跑 → **回滾只要把舊檔串回去**。
- **刪舊檔時機**:新檔上線後跑完一整個交易日(含 22:00 分點輪與 00:05 夜間作業)、網站抽查正常。
- **你需要做的**:核准窗口;(可選)sudo 停用並刪除未啟用的 `/swapfile2`(2 GB)與 dangling docker images(**不可 `prune -a`**,會刪掉盤中 worker 映像)。

## 3. P1 資料格式(兩份規劃的整合版)

網站端提「核心檔 + 雜湊歷史檔」(為了快取),VPS 端提「head + 分頁區段」(為了每輪少算、首屏變小)。兩者相容,採**合併設計**:

```
stocks/{id}.json            核心:meta、scores、reasons、technical、當日分點、權證、期貨摘要、
                            近 12–24 個月 candles(cut = 前一年 1/1)、指向下面兩檔的指標
stocks/hist/{id}.{hash8}.json   cut 以前的 K 線(內容雜湊檔名 → 一年 immutable 快取;年初滾動一次)
stocks/chips/{id}.json      branch_history、branch_pnl_est、branch_pctile_counts、branch_tags
                            (只在 17:40/22:00/00:05 重算;籌碼日報分頁才抓)
```

- **不變式(測試鎖住)**:前端把三檔組回來後,必須與今天的單一 JSON **逐鍵深度相等**(扣除前端沒讀的 `af`)。VPS 端 `export-json --verify-split` 在記憶體內同時產生新舊格式比對。
- **畫面一致**:Playwright 對同一份資料,逐頁、逐分頁、390px 與 1280px,比對頁面全部文字(主要依據)+ 截圖;既有 node／pytest 全綠。
- **上線順序**:前端雙讀(新舊格式都能讀)先上 → VPS 切新格式(環境旗標可退回)→ Worker 對雜湊歷史檔給長快取(需資安審查)→ 觀察一週後停產舊單檔。
- 先做 `export-json --size-report`(每檔每個欄位的大小分布,**分「榜單聯集 275 檔」與「其餘 2,143 檔」兩組**,否則平均會誤導)。

### 3.1 正式機實測(2026-10-03,修正網站端以本機 fixture 推估的「candles 佔 95%」)

| 檔 | 總 raw | candles | branch_history |
|---|---|---|---|
| 2330(聯集,全史 8,092 根) | 1,424 KB | 811 KB(57%) | 302 KB |
| 6488(聯集,2,909 根) | 803 KB | 290 KB | 284 KB |
| 4967(非聯集,600 根上限) | 532 KB | 59 KB(11%) | **283 KB(53%)** |

- 89% 的個股(2,143 檔)早就只有 600 根 K 線,**最大的是籌碼區段**(branch_history + pnl + pctile + tags ≈ 340–370 KB raw)。所以拆成兩步:
  - **P1-a**:K 線歷史拆檔(雜湊檔名)＋`--size-report`＋`separators`＋`--verify-split`。對聯集 275 檔首屏大幅下降(2330:1.42 MB → ~0.6 MB raw),其餘只約 −10%。
  - **P1-b**:籌碼區段 `chips` 延遲載入＋`--sections` 依輪次重算 → **才是把 p50 從 497 KB 壓到 ~120 KB 的那一步**。順序 a → b,都在 D-P0 維護窗之後。
- 規則補充:
  - 歷史檔完整度 = 當日是否在聯集(既有行為),前端不可假設歷史檔永遠是全史。
  - export 寫新歷史檔前**刪掉同檔舊雜湊檔**,否則 wrangler 會一直上傳舊檔、佔 VPS 磁碟。
  - 跳過重建:`stocks/hist/index.json` 記 id→hash/bars/cut/built_at;`built_at` 之後 `import_logs` 沒有除權息重算或深度回補 → 全域跳過歷史檔重建,只重建當天進出聯集的檔。籌碼區段同理,只在分點有新列的輪次重建。
  - `separators` 主要省 VPS 寫入(每輪 1.13 → ~0.9 GB),線上 brotli 下載量幾乎不變。
  - `af`(還原因子):前端與盤中 worker 都沒讀;排後由使用者決定,建議改出一份稀疏的 `adj`(只有除權息日)而不是直接丟掉。
  - `cloudflare-data-worker` 的任何 commit 會在**下一輪 VPS deploy 自動上線**(不經 GitHub),改 Worker 前要先告知並完成資安審查。

## 4. 明確不做

- 不換 DB 引擎、不引入任何需綁卡或常駐服務(Postgres、D1、R2、KV、SSR)。
- 不在 VPS 原地轉換;不在交易日窗口做。
- `ix_branch_trades_raw_date` 由覆蓋式 `ix_branch_trades_raw_date_cover (date, stock_id, branch_id, buy_lots, sell_lots, net_lots, pct)` 取代(2026-10-04 定案,`docs/43`),`_branch` 保留;不轉 `indicators_daily`、`daily_scores`、`branch_stock_stats`、`pctile_counts`。
- 不設 `temp_store=MEMORY`、不把 `cache_size` 開到數百 MB(1.7 GB RAM 有 OOM 前例)。
- 不讓 Service Worker 快取 `/data`、不顯示過期訊號;不裁數字精度;不換圖表庫;不做列表虛擬化(列表量級不需要)。
- 不加前端登入繞過;不改 workflow／secrets／DNS／crontab(P1 的輪次差異以腳本參數 `--sections` 實作,不改 crontab)。

## 5. 為什麼不換資料庫

1. 使用者路徑沒有資料庫(靜態 JSON + Supabase)。
2. 慢在 I/O 局部性與單執行緒 Python:同一台機器、同一張表,依股票聚集的讀法 1 分鐘、散落讀法 11 分鐘——換引擎一樣要處理,Postgres 的表同樣不自動按鍵聚集,還要多養常駐服務,1.7 GB RAM / 3.4 GB 磁碟放不下。
3. 零成本與免綁卡;雲端託管會把 3,238 萬列放到網路另一端,只會更慢。
4. 重寫 60+ 處 SQLite 方言與 1,100+ 測試,換來 0 使用者體感。再議條件沿用 `docs/31` §11。

## 6. 使用者決定(2026-10-03 22:00)

1. ✅ D-P0 維護窗:**2026-10-10(週六)**,前提是工具與 `docs/43` 完成、PC 試跑通過。
2. ✅ `daily_prices` 同窗轉換(基準不過就自動剔除)。
3. ✅ W-P0 前端三項:今晚開工,**驗證通過後 00:00 之後才推上線**。
4. ✅ **權證分點列保留天數(2026-10-04 Planner 定案)**:`branch_trades_raw` 的 6 碼列保留 **150 個交易日**,與 `warrant_daily` **共用同一個 `war_cutoff`**(嚴格 `<` 刪,邊界日保留);4 碼個股/ETF 列**永久保留**。實作於 `pipeline/radar/prune.py`(`radar prune --warrant-branches 150 --max-dates 10 [--dry-run]`),每輪由新到舊最多 10 個過期日、一日一交易、連續 3 個空日即停,不做一次性補刪、不 VACUUM(freelist 重用)。只在新版面(有 `ix_branch_trades_raw_date_cover`)啟用,舊版面跳過。每日 17:40 那輪 `daily-branches.sh` 原本就跑 `radar prune`,排程不變。效果:2027-02 起每天淨成長約 6–7 MB(原 ~14 MB)。詳見 `docs/29` §2.4。
