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
| **D-P0.5** 同批程式 ✅ 2026-10-04 程式完成(見 §7) | `db.py` 連線 PRAGMA(`synchronous=NORMAL`(僅 WAL)、`cache_size=-65536`;`temp_store` 維持 FILE;**mmap 不設**);`upsert()` 改 executemany;export 分段計時 log | `compute_all` 寫入 212 s → 40–60 s;寫入段 −20～−40% | 否 | 只動程式,不改檔案格式 |
| **P1** 資料格式拆檔(前後端一起)**— 2026-10-05 程式完成於分支(§3.2),待合 main** | 見 §3:個股 JSON 拆「核心＋K線歷史(內容雜湊檔名,一年快取)＋籌碼區段」,每輪只重算有變動的區段;`separators` 去空白、移除前端沒用到的 `af`;`no-store` → `no-cache`(304) | 一天 export ~2 h → ~35–45 分;手機首屏下載 0.5–1.5 MB raw → ~100 KB;重複看同一檔近乎 0 下載 | **格式請你過目**;Worker 規則需資安審查 + 核准 | 前端先上雙讀 → VPS 切格式 → Worker |
| **P1** Worker 驗證優化 | 同時多個請求只查一次 Supabase;JWKS 本地驗簽(ES256 釘死、移除 `/auth/v1/user`);profile 以 `sub` 快取 5 分。**2026-10-04 已在分支實作(`src/auth.js` + `test/*.test.mjs`),獨立資安審查通過(4 個 Low 已修),⏳ 待使用者核准,未合 main、未上線** | 冷啟動每頁 −0.25～−0.5 s | **是 + 資安審查**(門鎖) | `cloudflare-data-worker/` |
| **P2** 觀察後再決定 | 個股分頁元件按需載入、點擊預抓、爬蟲段不持 DB 鎖、權證分點增量彙總、`radar.json` 瘦身(**2026-10-06 程式完成於分支,§3.3**)、權證分點列保留天數 | 邊際 | 部分需核准 | — |

> **P2「爬蟲段不持 DB 鎖」的進度(2026-10-04,`docs/47`)**:分點輪改成先**探測**來源(等待期間放掉 DB 鎖,只握分點來源鎖),達門檻才全量爬;各日更輪的輪詢在每次嘗試之間放鎖;非交易日分點/資券/夜間輪收工。估 DB 鎖忙碌 4.3–5.5 → ~2.6–3.0 小時/日、非交易日 ~3.5 → ~0.1 小時。**全量爬本身仍持鎖**(逐檔 commit),那一段不變。deploy 全量重傳(`generated_at`)仍屬 P1。

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
stocks/{id}.json            核心:meta、scores、reasons、raw_risks、technical、price_levels(docs/45)、當日分點、權證、期貨摘要、
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

### 3.2 P1 拆檔實作決定(2026-10-05,Fable Planner+Executor;程式在分支,未合 main)

使用者交代「現在能做的就都做,按照 Fable 決定」。硬前提不變:**每一個畫面上的數字改前改後一致,只換包裝**。以下是定案與理由。

**檔案佈局(VPS `export-json` 每輪都寫)**

```
stocks/{id}.json              舊單一檔(**過渡期照寫**,逐位元不變;舊前端與尚未更新的分頁靠它)
stocks/core/{id}.json         核心:舊檔扣掉 chips 四鍵、K 線只留 cut 之後;多一個 parts 指標
stocks/hist/{id}.{hash8}.json cut 以前的 K 線(只有「榜單聯集」那 ~275 檔有;內容雜湊檔名)
stocks/hist/index.json        id → {file, hash, bars, cut, first}(維運用;前端讀 core.parts 不讀它)
stocks/chips/{id}.json        branch_history / branch_pctile_counts / branch_tags / branch_pnl_est
```

- `core.parts = {version: 1, hist: {file, bars, cut, first} | null, chips: {file, keys}}`。前端把 `hist.candles + core.candles` 接回、chips 四鍵塞回、刪掉 `parts`,**必須與舊單一檔逐鍵深度相等**(node 與 pytest 都鎖這條;`export-json --verify-split` 在匯出時對每一檔在記憶體內再比一次)。
- **cut = 資料日前兩年的 1/1**(`hist_cut`),不是 §3 草案的「前一年 1/1」:核心因此至少有 ~490 根,涵蓋「1 年」區間(240 根)+ 年線回看(240 根),K 線分頁六個區間裡只有「5 年／全部」在 hist 到之前會少畫;均線不會斷。代價是核心多約 245 根(~22 KB raw)。
- **hist 只給聯集股**:非聯集股本來就只有 600 根(滑動視窗),若也切會天天換雜湊、天天新檔;聯集股的 cut 以前內容一年不變,只在除權息重算 af 時換檔。寫檔前先看同名檔是否已存在(存在就不重寫),再刪同 id 其他雜湊檔;本輪沒寫到 hist 的 id(退出聯集)其舊檔一併刪,`stocks/hist/` 不會累積。
- 新檔一律 `separators=(",", ":")`(raw −15~20%);舊單一檔維持原序列化,所以「舊檔逐位元不變」可直接驗。
- **chips 不延後抓**:多空摘要(標頭「多方 N·空方 N」與多空分頁)要 branch_history/pnl/pctile/tags,K 線的主力買賣超 pane 也要 branch_history;延後抓等於先畫一個不同的畫面。所以個股頁第一次畫面 = core + chips 都到(兩個請求並行);**只有 hist 是漸進的**:多空摘要與多空分頁等 hist 到才算(之前是骨架,不是 0·0),其餘(報價、K 線預設 3 月、籌碼日報、法人、資券…)先畫。非聯集股沒有 hist,行為與今天完全相同。
- `--sections`(依輪次只重算 chips)**不做**:`branch_pnl_est` 的未實現損益用到當日收盤、`branch_tags.as_of` = 資料日,chips 每一輪本來就會變,略過重算就是輸出舊數字。P2 若要省 export 時間,路線是 §3 的「分點無新列就整段跳過」而不是這個旗標。
- `af` 不動(待使用者決定);`dataFetch` 的 `no-store` 不動(改 `no-cache`/304 要連 Worker 標頭一起看);Worker **不改**——`stocks/hist/*` 目前跟其他檔一樣 `private, max-age=60`,要拿到「一年 immutable」必須改 Worker(資安審查 + 核准,見下方待辦)。

**相容矩陣(程式走 Pages push 即上線;資料等 VPS 下一輪 `sync_code` 後 export)**

| | 舊資料(只有 `stocks/{id}.json`) | 新資料(三份都有) |
|---|---|---|
| 舊前端 | 今天的狀態 | 讀 `stocks/{id}.json`,內容逐位元同舊版 → 正常 |
| 新前端 | 先抓 `stocks/core/{id}.json` → 404 → 退回 `stocks/{id}.json` → 正常 | 走新佈局;hist 抓不到(部署瞬間雜湊換了)重抓一次 core,再不行退回舊單一檔 |
| 多方榜建置器(VPS) | 舊路徑 | `stocks/core/` 存在就讀 core+chips+hist 合併(同一個 `mergeStockParts`),輸出不變 |
| 自選頁 | 舊路徑 | 只抓 core(最後兩根 K 與 scores 就在 core)→ 每檔 ~500 KB → ~120 KB |

**檔數**:Workers 靜態資產每版上限 20,000 檔。估今天 ~6,400(2,418 個股 + 權證分點明細 ~3,800 + 其餘);過渡期 +2,418 core +2,418 chips +~275 hist +1 ≈ **11,500**;清理後 ≈ 9,100。單檔 25 MB 無虞(最大的個股檔 1.4 MB)。

**誠實註記(2026-10-05 驗證者要求)**:
- **hist 目前沒有瀏覽器快取效益**:`dataFetch` 是 `no-store`,Worker 對 `stocks/hist/*` 也只給 `private, max-age=60`(同其他檔)。`stockLoad` 對 hist 用 `cache: "default"`,但要等清理步驟 ④ 改 Worker 標頭(資安審查)才會真的快取;在那之前聯集股每次進頁都重抓 hist,**首次載入總位元組與今天相同**(只差 separators 的空白),得到的是「核心先畫、hist 後到」的體感與 export/deploy 端的好處。
- **過渡期成本(實測比例)**:本機 968 檔 46.0 MB → core 26.6 + chips 0.3 + hist 12.6 MB;正式機 2,418 檔估 stocks 約 1.13 GB → 新增 core ≈ 0.65 GB + chips ≈ 0.25 GB + hist ≈ 0.3 GB,**磁碟約 +1.2 GB、wrangler 每輪上傳位元組約 +80%**(hist 內容不變不重傳,core+chips 每輪都變)。VPS `df` 2026-10-05:`/` 29 GB、已用 76%、**剩 6.8 GB**;週六 05:00 `weekly-backup.sh` 另需約 2.1 GB 暫存 gzip → 過渡期最低點約 6.8 − 1.2 − 2.1 ≈ **3.5 GB**,不會撞牆,但 D-P0 前的 9 GB DB 若再長就更緊,所以過渡期要短。
- **並行 export(`mid-backfill-publish.sh` 不持 DB 鎖)**:三份都 tmp+rename、hist 先寫 core 後寫、同名 hist 只在檔案大小等於這次內容才重用(截斷檔會重寫)、index 沒指到的 hist 檔要 **mtime 老過 24 小時**才刪,而且**重用時會把 mtime 刷新到現在**(否則一年沒變的 hist 早就老過寬限期,另一個聯集/雜湊不同的並行 export 會刪掉它——驗證者反例 S2/S3);第二道保險:磁碟上該 id 的 core 若仍指著這個檔也不刪(只為刪除候選檔讀一個 core)。代價是換雜湊後舊檔多留一天。前端:chips 抓不到→退舊檔;hist 404→重抓 core,core 404 或再 404→退舊檔;hist 網路錯誤→重試一次,再失敗保留已畫的頁面並在多空列標一行說明(`histFailed`),不整頁變錯誤。建置器:母體外的檔只讀核心;hist 不在時~~讀舊單一檔,沒有就~~略過該檔不中斷(2026-10-07 起一律警告並略過,不再退回舊單一檔——export 已不更新它,殘留的是過期內容)。

**清理步驟(縮短過渡:上線後連續 2–3 個乾淨交易日即可,不必等一週;另案)**:① 看 radar-cron.log 的 `export parts:`(hist_reused 應接近 hist_total)、正式站個股頁無 404 退回、建置器 `layout=split`;② VPS 腳本的 `radar export-json` 改成 `radar export-json --no-legacy-stocks`(12 支腳本,見 `test_bull_board_vps_wiring.py` 的清單)或把預設翻過來;③ 刪掉 VPS `web/public/data/stocks/*.json`(頂層那 2,418 個)讓 wrangler 下一輪移除(磁碟與每輪上傳回到比今天還少);④ Worker 加 `stocks/hist/*` 長快取 + `dataFetch` 對 hist 放行快取(資安審查),hist 才真正「一年只下載一次」。

**清理進度(2026-10-07)**:
- ① ✅ 2026-10-06 14:05 輪起正式機 log 乾淨:`export parts:` hist 重用正常、建置器 `layout=split failed=0`。
- ② ✅ **選「把預設翻過來」**(不是在 12 支腳本各加 `--no-legacy-stocks`):`export_json(legacy_stocks=False)` 為預設,CLI 改成 opt-in 的 `--legacy-stocks`(逃生口,回滾到只認舊檔的前端時用);`--no-legacy-stocks` 保留為無作用的相容旗標。理由:單一處改動,手動跑、`manual-catchup.sh`、`backfill-*.sh`、未來新腳本都自動正確,不必維護 12 支腳本的參數清單。export **不刪也不更新**殘留的舊單一檔(有測試鎖);讀取端一律先讀 `core/`,殘留舊檔不會被讀到。多方榜建置器 hist 不在時改為警告並略過,不再退回舊單一檔。讀取端盤點:前端個股頁 `loadStock`/自選頁 `fetchStockCore` 先抓 core(舊檔退回保留為無害的死碼)、盤中 worker 只讀 `radar.json`、`deploy_data` 只是 `wrangler deploy` 整個資產目錄、Worker 對路徑無特例;pipeline 測試改用 `read_merged_stock` 讀拆檔。
- ③ ✅ 已執行(2026-10-07 17:48,持 DB 鎖;因檔案由容器以 root 寫入,改在 `radar-pipeline` 容器內執行):刪除 2,419 檔、釋放 1,066.8 MiB,`deploy_data` 後 Workers 資產 6,461 檔,磁碟剩 7.0 GB。原規劃:`pipeline/tools/purge_legacy_stocks.py`(只刪 `stocks/` 這一層的 `*.json`,`core/chips/hist`、`hist/index.json` 不碰;預設 dry-run、`--write` 才刪;印檔數與位元組;`stocks/core/` 檔數 < 要刪的舊檔數就拒絕)。指令見 `docs/STATUS.md` 2026-10-07 條目。預估釋放 ≈ 1.1 GB 磁碟(2,418 檔,§3.2 估算的 stocks 舊檔約 1.13 GB),Workers 資產檔數 −2,418。刪除後下一輪 `deploy_data` 即從 Workers 移除。**舊前端快取**:Pages 早已部署新前端(2026-10-05 起),新前端先讀 `core/`,所以刪舊檔對現有使用者安全;只有在 Pages 回滾到 P1 之前的前端時才需要先跑一次 `export-json --legacy-stocks` 把舊檔補回。
- ④ ⏳ 未做(Worker 標頭改動需資安審查＋核准)。

**驗證方式**:pytest `test_stock_parts.py`(純函式 + 種子 DB 匯出:合併 == 舊檔、hist 不重寫、退出聯集刪檔、`--no-legacy-stocks`、`--size-report`);node `stockParts.test.ts` / `stockLoad.test.ts` / `bullBoardBuild.test.ts`(拆檔 fixture 與舊 fixture 建出同一份 bull_board.json);`pipeline/tools/split_legacy_dir.py` 把本機 968 檔真實舊 JSON(2026-07-08)用同一個 `split_stock_payload` 拆成新佈局,`web/scripts/verify-split-merge.mjs` 用前端的 `mergeStockParts` 接回逐檔 deepStrictEqual 並統計 raw/brotli 大小;Playwright `parity-snapshot.mjs` 對同一份 build 分別餵舊/新佈局,全部頁面文字相同;390px 截圖。

### 3.3 P2 首頁拆檔(`radar.json` 瘦身;2026-10-06,Fable Planner+Executor;程式在分支,未合 main)

**問題**:`radar.json`(正式約 770 KB raw,本機 7 月 fixture 203 KB)每次打開首頁整包下載、`no-store` 不快取;而 2026-10-04 起預設分頁是「多方榜」(讀 `bull_board.json`),從 `radar.json` 只用到表頭(資料日、成交額、各分頁檔數、題材/產業資金流、策略 meta、期貨名單);`stocks`(榜單聯集 ~275 檔,raw 佔 ~85%)要到未發動／策略／掃描等分頁才用。逐檔裡 `technical`(含 reasons/risks 兩個陣列,約每檔 raw 的 1/3)、`volume_lots`、`transactions`、`margin_chg_lots`、`chg5_pct`、`pocket_score`、`pocket_families` 與 `warrant` 的 6 個欄位,首頁卡片完全沒畫。

**選項與決定**(使用者「按照 Fable 建議」):

| 選項 | 決定 | 理由 |
|---|---|---|
| 丟首頁沒用的欄位 | ✅ 做(只在新檔) | 零畫面風險;`technical` 一項就是逐檔 raw 的 1/3 |
| 短鍵名／欄式陣列 | ❌ 不做 | brotli 後鍵名幾乎免費(fixture:compact 序列化省 10% raw、brotli 後 0%);換格式得動每個讀的人 |
| 依分頁拆、切到才抓 | ✅ 做成「表頭 + stocks」兩檔 | 各分頁共用同一份 `stocks`(lists 只是 id),再細拆只是重複;預設分頁完全不需要 stocks |
| 把少用的區塊搬出去 | ✅ `concentration`(分點頁用)、`summary_text`、`score_list_meta`(前端沒讀)不進表頭 | 都很小,順手 |
| 直接改 `radar.json` | ❌ 不改 | 分點頁、自選頁、盤中 worker、建置器、期貨推播、`futures-anomaly-digest` 都讀它;過渡期需要舊前端照常 |

**檔案佈局(VPS `export-json` 每輪寫,緊湊序列化,各自 tmp+rename,stocks 先寫 head 後寫)**

```
radar.json             照寫、逐位元不變(所有既有讀者不動)
home/head.json         {version:1} + radar.json 扣掉 stocks 與 concentration / summary_text / score_list_meta
home/stocks.json       {version:1, data_date, generated_at, stocks:[逐檔投影]}
```

- 逐檔投影 = 原列扣掉 `HOME_DROPPED_STOCK` 七個鍵,`warrant` 只留 `call_turnover / call_turnover_ratio / call_count`;**順序、其餘每個值與 `radar.stocks` 相同**(`home_split.py`;清單與 `web/lib/homeLoad.ts` 一致,pytest 讀 TS 檔核對)。
- 兩檔帶同一個 `generated_at`。前端先抓 head(多方榜、資券只要它),第一次切到要畫股票的分頁才抓 stocks;`generated_at` 對不上(mid-backfill 並行 export 夾到)→ 重抓 head 一次、再不行重抓 stocks 一次、還是不行退回 `radar.json`(一個檔永遠自洽)。head 抓不到(404／網路)→ 退回 `radar.json`;stocks 抓不到 → 退回 `radar.json`。
- 等 stocks 的那一瞬間:表頭、分頁列與檔數已經畫好,只有卡片區是骨架(與今天整頁骨架同一款);期貨分頁也等 stocks(股名從 stocks 取,不然 `useStockNames` 會去抓 113 KB 的 `stocks_index.json`);多方榜只在**舊 payload**(entries 沒有 `theme` 鍵)時才等 stocks;「策略」分頁沒登入時只畫登入提示、不抓。
- `RadarStock` 型別把丟掉的欄位標為可選、`warrant` 收成三鍵的 `Pick`:以後有人在卡片上讀它們,tsc 會擋。

**大小(本機 2026-07-08 fixture,139 檔;brotli q5 / q11)**

| | raw | br q5 | br q11 |
|---|---|---|---|
| `radar.json`(今天) | 203.0 KB | 33.5 KB | 27.1 KB |
| `home/head.json`(預設分頁只要這個) | 34.2 KB | 7.2 KB | 5.9 KB |
| `home/stocks.json` | 78.1 KB | 18.9 KB | 15.3 KB |
| head + stocks(股票分頁) | 112.3 KB | 24.2 KB | 20.4 KB |

預設分頁 **−83% raw / −78% brotli**;股票分頁 −45% raw / −28% brotli。補成今天 export 形狀的 fixture(加 raw_reasons / strategy_signals / strategy_meta / futures / pocket 假值)比例相近(221.7 → 41.6 + 106.5 KB raw;43.8 → 8.5 + 27.2 KB br)。正式機數字(770 KB raw)**本機拿不到**(`/data` 要 JWT 或 service key;本任務不 SSH),`export-json` 每輪會印一行 `export home: radar=… head=… stocks=…`(raw bytes),上線後看 `radar-cron.log` 即可。

**相容矩陣**(程式走 Pages push 即上線;資料等 VPS 下一輪 `sync_code` 後 export)

| | 舊資料(只有 `radar.json`) | 新資料(三份都有) |
|---|---|---|
| 舊前端 | 今天的狀態 | 讀 `radar.json`,逐位元同舊版 → 正常 |
| 新前端 | `home/head.json` 404 → `radar.json` 一次到齊(多一次 404 探測,只在 Pages 先上、VPS 還沒 export 的那幾小時) | head → 需要時 stocks;夾到不同輪就對齊或退回 `radar.json` |
| 分點頁／自選頁／盤中 worker／建置器／期貨推播／`futures-anomaly-digest` | `radar.json` | `radar.json`(不變) |

**驗證**:pytest `test_home_split.py`(投影只丟不加、鍵序、warrant 三鍵、接回 == 投影、不同輪擲例外、寫檔順序與緊湊序列化、種子 DB 匯出 radar.json 序列化不變 + home 兩檔接回 == 投影、TS 清單一致);node `homeLoad.test.ts`(拆檔／舊資料／stocks 404／head 網路錯誤／三種夾到情境／卡片讀的欄位都不在丟棄清單);`pipeline/tools/split_home_json.py` 對真實 fixture 拆檔、接回比對並量 raw/brotli;Playwright `parity-snapshot.mjs` 同一份 build 分別餵「只有 radar.json」與「radar.json + home/」(fixture 與補齊形狀的 fixture 各一組),首頁全部分頁 390px 與 1280px 文字快照 diff 為空;`--shots` 另存 390px 截圖。

**Worker(只核對,不改)**:`cloudflare-data-worker/src/index.js` 把 `env.ASSETS.fetch` 的回應原樣串流、只覆寫 `cache-control` 與 `vary`,沒有自己設 `content-encoding`,所以 brotli 由 Cloudflare 邊緣依 `Accept-Encoding` 對 `application/json` 自動做(2026-10-03 兩位 Planner 以正式站標頭量到的「線上 brotli」即此)。本任務本機沒有金鑰,**沒有重新量正式站標頭**;核對指令:`curl -sS -D - -o /dev/null -H "Accept-Encoding: br" -H "X-Radar-Service-Key: …" https://radar.techtrever.com/data/home/head.json | grep -i -E "content-encoding|cache-control"`。另:Worker 的 `NO_STORE` 只認 basename `radar.json`/`meta.json`,`home/*.json` 會拿到 `private, max-age=60`(`dataFetch` 是 `no-store`,瀏覽器不會用到;要與 `radar.json` 同語意可把兩個新檔名加進 `NO_STORE`——改 Worker 需資安審查,另案)。

**清理步驟(另案)**:`radar.json` **不會停產**(分點頁、自選頁、worker、建置器、推播都讀它);可做的是 ① 分點頁改讀自己的小檔(concentration)、自選頁改讀 `home/head.json` 的 `lists.armed`,讓 `radar.json` 只剩機器讀者;② 前端拿掉 `home/head.json` 404 退回(新資料上線 2–3 個交易日後);③ Worker `NO_STORE` 加 `home/head.json`、`home/stocks.json`。沒有磁碟或檔數壓力(兩個檔、合計比 `radar.json` 小),過渡期可以長。

**沒做、留著以後量**:`spark`(30 根收盤)在有 `spark_day` 的檔其實沒畫(卡片畫分時),fixture 裡 `spark` 佔逐檔 raw 14%;要省得把「有 spark_day 就不給 spark」寫進 export,與卡片的判斷耦合,先不做。`themes[].top` / `sectors[].subs`(資金流向面板,預設收合)約 33 KB raw,也可延後抓,但多方榜族群檢視要 `themes`/`sectors` 的 `vs20`,拆了省不多。**2026-10-09 後**:資金流向面板已移除(`docs/49` §10),`subs`/`top`/`share`/`avg_chg`/`up`/`down`/`turnover` 已無前端讀者,可直接從 `head.json` 投影丟掉(`radar.json` 不動);列為清理候選,另案。

### 3.4 chips v2:分點日史換成「每日全部列」的緊湊格式 `branch_days`(2026-10-10,Fable Planner+Executor;程式在分支,未合 main)

**問題(使用者 2026-10-10:「為什麼我每日買賣超籌碼分點不是前15…盟立就沒有資料。鉅祥只有六筆」)**:`branch_trades_raw` 每檔每日本來就有來源完整的 30 列(MoneyDJ 買超前 15 + 賣超前 15),但 `json_export` 的 `branch_history` 每天只留 **|淨額| 前 12 列(兩側合計)**。一邊倒的日子另一側整個不見:2464 10/08 匯出 12 列全是賣超 → 買超名單空白;2476 剩 6+6;2330 剩 3 買 9 賣。前端再把這 12 列拆成買/賣各切 13。這個裁剪也是多空事實、囤貨/出貨、股代、區間損益以外所有分點讀者的輸入。

**使用者決定(2026-10-10)**:「都改成前15大分點一致化」——全站所有讀「前 12 大」的地方改成來源的「買超前 15 + 賣超前 15」。這改了多方榜的輸入 → `bull-board-v2`(見 `docs/48` §8)。

**格式(`pipeline/radar/export/branch_days.py`;chips `version` 1 → 2)**

```
"branch_days": {"version": 2, "per_side": 15, "names": ["凱基-台北", …],
                "days": [["2026-10-08", [[ni, buy, sell], [ni, buy, sell, net], …]], …]}
```

- **與 raw 逐列相等**:每檔每日每一列都留(不裁、不合併同名、不重排,順序 = `branch_id DESC`,與以前相同);最多 480 個交易日、新→舊;NULL 張數同舊格式視為 0;`net` 只在來源 `net_lots ≠ buy − sell` 時寫第 4 欄,解碼後 net 永遠等於 raw。pytest `test_branch_days_export.py` 以種子 DB 逐列對照 raw(含 15 列全賣超的日子、同名兩個 branch_key、net ≠ 買−賣、482 天上限)。
- 前端 `web/lib/stockParts.ts decodeBranchDays`(與 Python `decode_branch_days` 同規則)在接回時解碼成舊 `branch_history` 形狀並拿掉 `branch_days`;**所有讀者仍讀 `branch_history`**,只是每天從 ≤12 列變成來源全部列。`mergeStockParts`/`mergeIfSplit`/`loadStock`(含舊單一檔)都走這條;建置器同一份程式。
- 評估過的其他選項:(a) 維持舊形狀直接放 30 列 → 每檔 ~700 KB raw(2.4×),否決;(b) 新舊兩鍵並存過渡 → chips 體積 1.6×,且舊前端讀到新 chips 本來就不會壞(見相容矩陣),否決;(c) 短鍵 `{n,b,s}` 不建名字表 → 省不到名字重複的那一半,否決。

**大小與時間(本機合成 480 日 × 30 列、名字池形狀同正式分點名;合成的 v1 每檔 295 KB raw 與 §3.1 正式機實測「`branch_history` 固定約 290 KB」吻合)**

| 每檔 480 日 | raw | gzip-6 |
|---|---|---|
| v1:每日 12 列、逐列物件(今天) | 295 KB | 57 KB |
| 舊形狀直接放 30 列(否決) | 699 KB | 128 KB |
| **v2:每日 30 列、名字查表** | **178 KB(−40%)** | 67 KB(+17%) |

- 正式機 chips 總量 596 MB(2,419 檔)→ 以 `branch_history` 佔 chips 75–85% 推估 **v2 ≈ 395–420 MB(約 −30%)**;若直接放 30 列會是 ≈ 1.2 GB。壓縮後(線上 brotli)每檔多約 +17%:內容真的多了 2.5 倍列,壓縮只能抵銷重複的名字。VPS 磁碟與 wrangler 上傳位元組(raw)都降。
- encode 時間:v2 每檔 4.2 ms vs 舊 sort+slice 6.7 ms(不再每天排序),export 的 `branch_history` 分段估 −6 s/輪;查詢不變(同一條 730 日 SQL)。正式機數字上線後看 `radar-cron.log` 的 `export timing: branch_history=…` 與 `du -sh web/public/data/stocks/chips`。

**全站「前 15 大」一致化(讀者盤點)**

| 讀者 | 以前 | 現在 |
|---|---|---|
| 籌碼日報 `BranchFlowSection`(聚合搬進 `lib/branchFlow.ts`,node 測試) | 12 列拆買/賣各切 13 | **1日** = 當日完整列(來源 30 列;舊 chips 時用個股 JSON 的 `branches`,它本來就是完整當日列);**N 日** = 各日前 15 大合計,每側最多 15;畫面常駐一句「各日前 15 大買賣超合計(來源每日只公布買超、賣超各前 15 大…),不是全市場完整合計」;淨流格改名「N日前15大淨流」;同名同日多列加總 |
| K 線「主力買賣超(前15大)」pane | 12 列 net 加總 | 全部列 net 加總,改名 **「前15大買賣超合計」**(手機 segment「前15大」) |
| 多空事實 `C_TOP15_FLOW_*` | 「前12大分點今日淨買超」(12 列合計) | **「前15大買賣超分點合計今日淨買超」**(30 列合計);門檻(佔量 2%/5%)不變 |
| 囤貨/出貨 `accumulation.ts`、融資×分點集中度 | 每天只看得到 12 列 | 每天全部列;文案 `TOP_N_PER_DAY` 12 → 15 |
| 強分點 `smartFacts`、追蹤/地緣/隔日沖事實、股代「近兩年前 12 大」、籌碼段「每天只存淨額前 12 大」 | 同上 | 同上,文案改「每日前 15 大買賣超」 |
| `branch_tags` 名字範圍 | 12 列 ∪ 當日 | 全部列 ∪ 當日(標籤因此可能多幾個分點) |
| `branch_pnl_est`、`pocket`、分點頁、權證分點 | 本來就用 raw 全部列 / 自己的查詢 | 不變 |

**相容矩陣**(程式走 Pages push 即上線;資料等 VPS 下一輪 `git pull` 後 export)

| | 舊 chips v1(`branch_history`) | 新 chips v2(`branch_days`) |
|---|---|---|
| 舊前端(使用者還沒重新整理的舊 bundle) | 今天 | `branch_history` 不在 → 走既有「沒有分點日史」路徑(籌碼日報只剩 1日 用 `branches`、K 線沒有主力 pane、多空少分點事實);**不會壞**,重新整理就好。chips 檔仍是 JSON、key 都認得 |
| 新前端 | 直接放回(每天 ≤12 列;1日 改用 `branches` 所以已經是完整的) | 解碼 → 全部列 |
| 多方榜建置器(VPS,與 export 同一份 checkout) | 同新前端 | 同新前端;版本字串 `bull-board-v2` |
| `read_merged_stock`(pytest/工具) | `branch_history` 放回原位 | `branch_days` 放回原位;`branch_history_of()` 兩代都讀 |

- 舊前端的「沒有日史」降級只發生在「VPS 已 export v2、使用者的分頁還是舊 bundle」的那段時間;所以**不留舊鍵並存**(體積 1.6×)。清理:chips v1 的讀取相容(`_LEGACY_CHIPS_KEYS`、TS `CHIPS_KEYS` 裡的 `branch_history`、`branch_history_of`)可在正式機連續 2–3 個交易日都是 v2 之後移除;另案。
- `--legacy-stocks` 逃生口寫的舊單一檔同樣帶 `branch_days`(前端 `loadStock` 的舊檔路徑也解碼)。

**驗證**:pytest 全套 1704 passed(新 `test_branch_days_export.py` 7 項;`test_stock_parts`/`test_json_export_branch_tags`/`test_branch_interval_pnl`/`test_bull_bear_codes` 跟著改);web node 398 passed(新 `branchFlow.test.ts` 5 項、`stockParts`/`stockLoad` v2 案例、`bullBoardBuild` 版本換代案例、事實文案);`tsc`、`next build`;390px 深/淺色 Playwright 截圖(假 session 攔截 Supabase、`/data/**` 餵 2464 型/2476 型合成 chips v2)`docs/evidence/44_branch_days/`:2464 1日 買方 0 家/賣方 15、5日 14/15,2476 1日 8/6(同名兩列加總成一列、怪怪-分點 net=5),K 線 pane 標題「前15大買賣超合計」,無水平溢出。

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
4. 待決:權證分點列保留天數(資料刪除,不決定則 12–15 個月後再壓實一次)。

## 7. D-P0.5 執行紀錄(2026-10-04)

- **`db.upsert()`**:由 SQLAlchemy 多列 VALUES(每 800 列一句、每句重新編譯)改為 driver 層 `executemany`,每組欄位一句預備好的 `INSERT … ON CONFLICT(pk) DO UPDATE SET col=excluded.col`。語意不變:只更新 row 內有的欄、沒帶的欄保留舊值;全 PK 列 → `DO NOTHING`;Python 端 scalar default(`stocks.is_active`、`import_logs.rows`)與型別綁定(Boolean→0/1)照 SQLAlchemy 原規則;**連續**同 key set 的列共用一句(原順序保留,同 PK 後列勝出),key set 不同也能混寫;回傳寫入列數。新增 `db.insert_many()`(純 INSERT,同一路徑)給整表 DELETE+INSERT 的 `branch_stock_pctile_counts`。`compute_branch_stats`(整表重寫)、分點匯入 `upsert_branch_trades`、`daily_scores`、指標、PIT 都經 `upsert()` 自動受益。
- **PRAGMA**:連線事件在 journal_mode=WAL 時設 `synchronous=NORMAL`(WAL 下斷電最多丟最後幾次 commit,不會損壞);`init_db` 切 WAL 的那條連線同步設定。`cache_size=-65536` 保留;`temp_store`、mmap 維持預設。
- **一致性**:合成庫(`make_synthetic_branch_db.py`,預設 60 檔 ×120 日,及 600 檔 ×250 日 ×400 分點、239 萬分點列)以 `compute_parity.py --old-code <HEAD 匯出> --new-code .` 跑 00:05 鏈(branch-stats/PIT/pctile/scores,小庫另含 indicators),**全部 26 張表(原始＋衍生)PK 排序 SHA-256 相同**。分點匯入／stocks 部分欄位／daily_scores 部分欄位更新另以腳本新舊程式各寫一份,含 `typeof` 的雜湊相同。
- **效能(本機 PC)**:600 檔合成庫 `compute-branch-stats` 寫入段 71 s → 3 s(21.3 萬列),整步 113 s → 49 s;單測 30 萬列 `branch_stock_stats` DELETE+upsert 129 s → 3 s;分點匯入 9 萬列 23 s → 3.6 s;daily_scores 9,000 列 1.6 s → 0.09 s。正式 `compute_all` 寫入段(114 萬列,212–227 s)依比例估 **約 10–20 s**(VPS CPU 較慢、真實索引較多,以 VPS 下一輪 `branch stats timing: write=` 為準)。`branch-stock-pctile-counts` 本來就是 executemany,只省綁定開銷(87 → 76 s,計算為主)。
- 未做:export 分段計時已於 WITHOUT ROWID 批次上線(`export timing:`),本批不動 `json_export.py`。
