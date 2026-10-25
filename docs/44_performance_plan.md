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

- **與 raw 逐列相等**:每檔每日每一列都留(不裁、不合併同名、不重排,順序 = `branch_id DESC`,與以前相同);最多 480 個交易日、新→舊;NULL 張數同舊格式視為 0;`net` 只在來源 `net_lots ≠ buy − sell` 時寫第 4 欄,解碼後 net 永遠等於 raw。pytest `test_branch_days_export.py` 以種子 DB 逐列對照 raw(含 15 列全賣超的日子、同名兩個 branch_key、net ≠ 買−賣、種子 482 天只留 480 天的上限)。
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

### 3.5 export-json 提速(2026-10-15;程式在分支,未合 main)

**問題**:每一輪都跑 `radar export-json`(持 DB 鎖),晚上分點輪還跑兩次(第一段上線、第二段排行統計)。正式機 2026-10-14:19:45→20:01(1,000 s)、20:14→20:31(996 s);使用者要等第一次 export 跑完才看得到當天分點。20:14 那輪 `export timing: branch_history=220.3s candles=16.1s pctile=78.1s pnl=115.8s levels=6.2s warrant_shards=207.6s tracked=22.1s write=46.3s`(合計 ~712 s,其餘 ~290 s 沒有計時;`wpos: … secs=63.9` 在 warrant_shards 裡)。

**硬前提**:同一個 DB 狀態下,每一個輸出檔與改前**逐位元相同**(`generated_at` 除外);記憶體峰值不得多於 ~50 MB;不加任何依賴。

**改了什麼**(每一項都附「為什麼結果不變」;`pipeline/tests/test_export_speedups.py` 把每一項與它取代的舊查詢/舊程式原文逐列比對)

1. **計時補齊**:`export timing:` 原本 8 個鍵順序不動,後面加 `radar`(開頭到 radar.json/meta.json 寫完,不含 intraday)、`intraday`(spark_day＋分K,晚上那輪會連 Fugle)、`side`(資券排行/法人族群/指數/搜尋索引/個股迴圈前的讀表)、迴圈內的 `warrant_q`(權證歷史＋active_warrants)、`margin`、`holders`(集保＋董監)、`payload`(組 payload,含 branch_tags)、`loop_other`(迴圈內其餘)、`branches`(rankings/today/warrant_movers)、`total`。下一輪正式 log 就能說出那 ~290 s 在哪。`export parts:` 行多一個 `unchanged=`(見第 7 點)。
2. **權證分點 120 日窗口:三次掃描 → 一次**(`_WARRANT_WINDOW_SQL` / `_WarrantWindowScan`;`docs/51` §5.2 列的下一步)。以前同一窗口掃三次:區間彙總(GROUP BY 券商×權證)、逐日序列(GROUP BY 券商×標的×日)、持有估算(GROUP BY 標的×券商×權證×日)。三者都能由最細的 (標的, 券商, 權證, 日) 的淨張合計＋金額合計加回去:同一 (權證, 日) 的 `wd.close` 只有一個(主鍵),所以「日內先加再跨日加」與舊的「逐列加」是同一組整數相加。條件與 JOIN 與舊查詢逐字相同(舊持有估算多的 `kind IN ('call','put')` 改在 Python 篩),計畫同舊持有估算那條(`SCAN warrants → branch_trades_raw 主鍵`,**沒有** TEMP 表 JOIN)。列依 (標的, 券商) 相鄰,一次只留一個配對在記憶體:配對結束時判定是否入選(任一區間 |合計| ≥ 100 萬,= 舊 charted),沒入選的整個丟掉(舊程式裡它們本來就不產生任何輸出),入選的才算逐日序列、餵持有估算串流;標的現股收盤在遇到該標的第一個入選配對時才讀(主鍵範圍)。輸出順序:舊區間彙總的 GROUP BY 依 (券商, 標的, …) 排序 → 新程式照 `sorted((券商, 標的))` 走、配對內權證遞增;逐日序列每檔裡券商的先後 = 舊查詢第一次出現的順序 = (最早日, 券商名)。副作用:舊程式把區間彙總全部 `fetchall()` 再每組建一個 17 鍵 dict,合成庫上這是整個 export 的記憶體峰值(見下表)。
3. **個股 `active_warrants`**:舊的單檔查詢在每一檔都 `SCAN warrants`(`warrants.stock_id` 沒有索引;正式約 10.5 萬列 × 2,418 檔)。改成當日成交的認購/認售一次讀齊、依標的分組,Python 依成交金額遞減取前 12。**成交金額有同額(前 13 名內)時**,同額的先後與誰被 LIMIT 擠掉取決於 SQLite 的計畫與排序器,Python 不保證重現 → 那幾檔照舊跑原本的單檔查詢;沒有同額時「遞減取前 12」只有一個答案。
4. **個股分點日史**(`branch_history`):只讀 `branch_trades_raw` 主鍵範圍、不 JOIN `branch_dim`(名字在 Python 查表;查不到的 id 照 JOIN 語意丟掉),DBAPI cursor 直接拿 tuple;同一個 ORDER BY(主鍵倒走、不排序)。以前先問「這檔有沒有任何分點列」再查——沒有列時這條本來就回空,那一問拿掉。
5. **區間損益**(`compute/branch_interval_pnl.py`):三個窗口都是同一串日子的後綴,「淨額非 0 的日子、(淨額, 價格)、最後一個缺價/還原因子變動的位置、正淨額後綴和」每個分點先算一次,各窗口只切後綴;買進張數(整數)後綴和 < 50 的配對直接跳過模擬(模擬完也會被同一條門檻濾掉;淨額不是整數時不預篩);換算價每個日期算一次;`simulate_pair` 的 `min()/max()` 換成同義比較(`min(a,b)` 只在 `b<a` 時回 `b`),浮點式子與順序一個沒動。隨機輸入 300 組與舊實作的 JSON 逐字相同。
6. **分位計數**(`branch_pctile_counts`):DBAPI cursor + `zip`(與 `.mappings()` 同鍵同序同值)、兩派欄位對照表先排好一次,不在每列重組 f-string。
7. **內容沒變的 core/chips 不重寫**(`stock_parts.write_atomic_if_changed`):先比大小、相同才讀回逐位元比;寫出的位元組不變(wrangler 本來就只傳變了的檔;core/chips 的 mtime 沒有讀者,hist 的寬限期邏輯不經過這裡)。同一資料日的各輪,多數 chips(分點列只在分點輪變)與部分 core 一個位元都沒變。

**沒有改、量過不值得的**:`bd1`(`SELECT MAX(b.date)` 權證分點資料日)在合成庫量起來 0.0 s,維持原查詢(試過「逐日往回找」的寫法,省不到東西,已撤回)。集保/董監(`holders`)合成庫沒有資料量不到,改成計時。

**量測**(本機 Windows,Python 3.11 / SQLite 3.38.4;合成庫 `make_synthetic_branch_db.py --stocks 800 --days 500 --branches 300 --warrants-per-stock 10 --stock-rows 22 30 --warrant-branch-days 150` → `convert_branch_raw_without_rowid.py --analyze`(正式版面:WITHOUT ROWID＋日期覆蓋索引＋ANALYZE)→ `compute-branch-stats` ＋ `branch-stock-pctile-counts`:現股分點 1,040 萬列(每檔每日 22–30 列 × 500 日)、權證分點 240 萬列(150 日)、持有估算 73.6 萬列 / 83,976 配對、pctile 24 萬列;資料庫 1.8 GiB)。每次都是獨立行程、唯讀 immutable 開庫、`PYTHONHASHSEED=0`。

| 段(秒) | 舊(1a59c60)兩次 | 新,空目錄(兩次) | 新,寫進同一目錄再跑(兩次) |
|---|---|---|---|
| branch_history | 34.3 / 31.9 | 24.2 / 25.8 | 23.3 / 28.0 |
| candles | 1.1 / 1.1 | 1.1 / 1.1 | 1.0 / 1.0 |
| pctile | 8.1 / 7.5 | 5.8 / 4.9 | 5.6 / 5.2 |
| pnl | 27.0 / 25.0 | 21.8 / 19.0 | 20.9 / 21.1 |
| levels | 0.9 / 0.9 | 0.9 / 0.9 | 0.9 / 1.0 |
| warrant_shards(其中 `wpos: secs`) | 66.4 / 56.0(19.9,只含持有估算) | 31.5 / 28.4(23.3 / 20.3,含整個窗口掃描) | 29.9 / 31.4 |
| tracked | 7.5 / 6.9 | 7.1 / 7.9 | 7.2 / 7.5 |
| write | 22.8 / 21.3 | 23.0 / 21.2 | **11.4 / 12.1**(`unchanged=1600`,全部 core/chips 沒重寫) |
| 舊版未計時(總計 − 8 段) | 8.5 / 7.4 | radar 1.7、intraday 0.1、side 0.2、warrant_q 0.2、margin 1.7–1.9、holders 0.3–0.4、payload 0.7–1.0、loop_other 0.0、branches 1.8 | 同左 |
| **total** | **176.5 / 159.0** | **122.8 / 115.9(約 −25~30%)** | **107.2 / 114.3(約 −30~35%)** |
| 行程記憶體峰值(Peak Working Set) | 2,186 MiB | **709 / 709 MiB** | 708 / 709 MiB |

(第二次「新」是最後版本的程式;兩次之間只差並行寫入的分點名重讀與損益/分位的最後一輪微調。本機同一份程式前後兩次差 ±10%,讀數以區間看。)

- **逐位元一致**:`export_parity.py --dirs 舊 新`:3,374 檔 = 3,366 IDENTICAL + 8 TIMESTAMP(只差 `generated_at`),0 VALUE/ORDER-ONLY/MISSING;空目錄與「寫進舊匯出目錄再跑一次」(走不重寫路徑)兩種都通過。另一個小庫(60 檔 × 250 日,60 個分點)同樣通過。
- 記憶體峰值降了約 1.5 GB:舊程式的區間彙總 `fetchall()` + 每組一個 dict 在這個合成庫上是整個 export 的峰值(合成庫的「券商 × 權證」組數比正式機多,正式機的降幅會小很多,但方向一樣,不會變大)。
- 合成庫的 `warrants` 只有 8,000 檔(正式 ~10.5 萬),所以舊的 active_warrants 逐檔掃表本機只要 0.36 s(800 檔);依「檔數 × 權證數」外推正式機舊做法約是本機的 40 倍,是那 ~290 s 未計時裡的嫌疑之一(新做法 0.05 s,量級與權證數無關)。

**正式機省多少(誠實估計)**:本機量到的是 CPU 為主(合成庫幾乎全在 OS 快取裡);正式機 1.7 GB RAM、慢磁碟,快取效應會讓本機**低估** I/O 的那一半。

| 段 | 正式 10-14 | 預估 | 依據 |
|---|---|---|---|
| warrant_shards | 207.6 s | 約 90–120 s(省 ~90–120 s) | 三次窗口掃描剩一次;wpos 那一次在正式機 52–64 s,另兩次是同量級的整窗掃描+排序器 |
| branch_history | 220.3 s | 約 150–190 s(省 ~30–70 s) | 本機 −25~30%(省掉每列一次 branch_dim B-tree 查找與 SQLAlchemy Row);正式機若是讀盤為主,省得較少 |
| pnl | 115.8 s | 約 90–95 s(省 ~20–25 s) | 純 CPU,本機 −15~20% |
| pctile | 78.1 s | 約 55–60 s(省 ~20 s) | 純 CPU,本機 −25~30% |
| active_warrants(未計時) | ? | 省 ~20–60 s(猜) | 正式 2,418 次整表掃描 × 10.5 萬列 → 1 次 |
| write | 46.3 s | 第一次 export 不變;同日重跑省約一半 | 第二段 export、無新資料的輪次 |

合計**第一段 export 約省 180–300 s(1,000 → 約 700–820 s)**;第二段 export 再多省 write 的一半。數字要以合併後第一輪的 `export timing:`(新鍵會把未計時的 ~290 s 拆開)為準,回填本節。

**風險**:
- 逐日序列裡每檔券商的**鍵順序**依「舊 SQLite 排序結果 = (最早日, 券商名)」重現;本機 SQLite 3.38.4 與 VPS 容器的 SQLite 版本若排序器行為不同,舊輸出本身在 VPS 上就可能不是這個順序 → 新舊會差在 `daily` 物件的鍵順序(值不變;前端以券商名查表,不依賴順序)。上線前可在 VPS 用週備份快照跑 `export_parity.py SNAPSHOT SNAPSHOT --old-code <main> --new-code <本分支>` 一次核對(兩次全量 export,約 30–35 分 CPU,不持鎖、不碰正式庫)。
- active_warrants 的同額退路:判斷是「前 13 名內有沒有同額」,保守(寧可多跑舊查詢)。
- 不重寫:與 `mid-backfill-publish.sh` 的並行 export 交錯時,結果與「另一個 export 後寫」相同;core 仍在 hist 之後寫,core 指到的 hist 一定存在。
- 記憶體:合成庫峰值 −1.5 GB;新的權證窗口掃描常駐只有入選配對的整數陣列(舊程式是全部組的 dict)。

**第二段 export 增量(提案,未實作;需人類決定)**:`daily-branches.sh` 第一段上線後,第二段之前只跑 `compute-branch-stats`,它只寫 `branch_stock_stats`、`branch_rankings`、`tracked_branches`(自動增減)。export 讀這三張表的地方:`branches/rankings.json`、`branches/track/*`、`branches/today.json`(追蹤名單)、chips 的 `branch_tags`(追蹤/隔日沖)、radar.json/home/core 的口袋名單(`pocket`,讀追蹤名單＋最新排行 ≥ 70)。**完全不讀**這三張表的:權證分點全部輸出(`warrant_branches.json`、`warrant-stock-details/*`、`warrant_positions.json`)、K 線/hist、法人/資券/集保、`branch_days`、`branch_pnl_est`、`branch_pctile_counts`(那張表是 00:05 夜間作業才算)。所以:
  - **低風險一步**:`export-json --skip-warrant-shards`,只給第二段用(第一段有上線時;`FAST_PUBLISH=0` 的那條路第一段沒有 export,第二段必須全量)。第一段與第二段之間這輪持著 DB 鎖、沒有別的寫者,權證輸出會與第一段逐位元相同。預估再省 ~90–120 s/晚。
  - **較大一步**:第二段只重算 chips 的 `branch_tags`、core 的 `pocket_*` 與 radar/home、branches 三份,其餘沿用第一段的檔。省下大半個 export(~600 s),但要把「哪些輸出依賴哪些表」寫成可測的清單並逐位元比對兩段;改動面大,建議等本節上線、新計時看清楚後再議。
  - 兩者都會動 `vps/scripts/daily-branches.sh` 的上線流程,屬「仍須人工確認」範圍,這裡只提案。

**Fugle 抓取搬出 DB 鎖(2026-10-19;程式在分支,未合 main;詳見 `docs/50` §3.1)**:新計時(2026-10-15 起的 `export timing:`)看得出 `intraday` 段(spark_day 當日 1 分 K + 分K 補缺日,逐檔打 Fugle)是握鎖時間裡唯一的網路等待:14:05 輪 242 s、晚上第一次 export 71–122 s、沒東西可抓時 ~5 s(整個 export 660–973 s)。現在各日更輪在 export 前一步放 DB 鎖跑 `radar fetch-intraday`(唯讀選聯集 → 抓進 `data/spark_day.json`、`data/intraday5/`),export 預設只讀快取。同一個快取狀態下輸出逐位元相同(`test_intraday_prefetch.py`)。

| 輪 | 以前 export 裡的 intraday 段 | 預估每輪少握鎖 | 這輪多出來的牆鐘時間(不握鎖) |
|---|---|---|---|
| 14:05 daily-market(當天第一次抓,~150–200 檔分時 + 新進聯集補缺日) | 242 s | **~235 s**(該輪 export 少約 235 s) | fetch-intraday 的聯集選取(與 export 開頭同一段唯讀查詢,`radar` 段的一部分)+ 容器啟動,估 20–60 s;分時/分K 本身的 ~240 s 只是從鎖內搬到鎖外 |
| 16:30 分點輪第一次上線(晚上第一次 export) | 71–122 s | **~65–115 s** | 同上 20–60 s |
| 14:45 / 16:00 / 20:45、分點輪第二段 | ~5 s(只有新進聯集的幾檔) | ~0–20 s | 同上;分點輪第二段不再抓(每輪只在第一次上線前抓一次) |

- 合計一個交易日約少握 **~5–6 分鐘**的 DB 鎖,主要在 14:05(上櫃輪 14:45 起等鎖時最直接受益)與分點輪第一段(20:45 資券輪等鎖)。
- 代價:每輪多一次聯集選取(不握鎖)與一次放/拿鎖。放鎖的 1–4 分鐘裡等鎖的下一輪可能先跑——它的 export 一樣帶著本輪已寫入的資料上線;本輪 export 因此晚一點。`flock -n` 型的伺機寫入者(warrant-backfill、adjust-*、repair-window)都先問安靜窗/距下一個排程寫入者,與既有的輪詢放鎖、分點抓取放鎖是同一種暴露,沒有新增種類。
- 以第一個交易日的 `step fetch-intraday … elapsed=` 與 `export timing: … intraday=` 回填本表。

### 3.6 compute-branch-stats 提速＋第二段順序(2026-10-21;verifier CONFIRMED,已合 main)

> **正式機第一輪(2026-10-21)**:`branch stats timing: read=219s read-wait=83s per-stock-compute=138s aggregate=2s write=17s total=240s`(前三日 638–656 s)。分點輪:股票抓 18:32→19:13、第一段上線 19:30、統計 19:30→19:34、權證寫入 19:34、第二段 export 720 s、第二段上線 19:47:57(10-20 為 19:52、10-19 為 20:24)。20:45 資券輪準時開工(只等資料公布)。

**問題**:晚上分點輪第二段上線(權證＋排行統計)之前,第一段上線之後還要走 `import-warrant-branches`(5 s)→ `compute-branch-stats`(**658 s**)→ 第二次 `export-json`(660 s)→ deploy。正式機 2026-10-20:第一段 deploy 19:29、統計 19:29:07 起 658 s、export 19:40→19:51、第二段 19:52。權證抓取 19:13→19:28(第一段上線之前就收工)。

**這一步讀什麼、寫什麼**(`pipeline/radar/compute/compute_branch_stats.py`):
- 讀:`branch_trades`(view)的 `MAX(date)` 當 as_of;`tracked_branches`;`stocks`(`type='stock'`、名稱不含「指」、有分點列)逐檔:`daily_prices` 主鍵範圍＋`branch_trades WHERE stock_id=?`(`SEARCH r USING PRIMARY KEY (stock_id=?)`＋`branch_dim` 整數主鍵,沒有 TEMP 表、沒有日期索引)。逐檔依 stock_id 遞增 = 沿著 WITHOUT ROWID 表的主鍵順序掃一遍**全部現股歷史**(正式 ~3,300 萬列)。**不讀權證分點列**(6 碼的 stock_id 不在 `type='stock'` 裡)。
- 寫:`branch_stock_stats`(整表刪除重寫,入榜 ∪ 追蹤分點 ~114 萬列)、`branch_rankings`(只換 as_of 那一天的快照)、`tracked_branches`(自動增減)。
- **每天全量重算,不做增量**:每個 (分點, 個股) 的事件數、勝率、隔日沖觀察都是全期歷史的函式;as_of 每天往前走(90 日／2 年 cutoff、近 90 日金額),前 5 日事件的前瞻報酬每天補齊,除權息會讓整段還原價改變。要增量就得把這些逐一做成可更新的狀態,正確性風險遠大於剩下的時間,不做。

**改了什麼**(結果逐位元不變;SQL 與改前逐字相同)
1. **逐列不再組 dict、不再每列走 `merge_by_date`**(`_merge_rows_by_branch`):每列直接存成 `(net, sell, pct)`;只有「同名同日多列」才收集起來走同一個 `combine`(依讀取順序,fsum/sum 與改前同一份)。分點先後 = 第一次出現的順序(改前 `defaultdict` 的順序;它決定兩張表的寫入順序)。
2. **隔日沖觀察**仍呼叫唯一那份 `daytrade_observations`,吃一個 `_DaytradeView`:只對資格日與次一交易日組 `{"net","sell"}`。
3. **前瞻報酬與買點分位依 (個股, 事件日) 快取**(`_StockPrices`):同一檔的各分點常在同一天成為事件,改前每個分點各算一次。算法本身不動(照舊呼叫 `forward_returns`,同一份 candle;分位同一個 20 日視窗)。
4. **讀取在背景執行緒預讀**(`_read_stocks`,最多先讀 2 檔):sqlite3 在 step(含等磁碟)時放掉 GIL,主執行緒算這一檔、背景讀下一檔。正式機 1.7 GB RAM、表 ~5 GB,讀取大半是等磁碟,改前讀與算輪流、時間直接相加。背景用 engine 自己的連線(同一組 PRAGMA);改前的 SELECT 本來就各自是自動交易(pysqlite 不為 SELECT 開交易),所以快照語意與改前相同,而這一步在 DB 鎖內跑、沒有其他寫者。背景出錯在主執行緒重新拋出;主執行緒出錯時背景會被叫停、不會卡住。
5. **計時**:`branch stats timing:` 原本的鍵不動,`read=` 仍是讀取總時間(現在是背景執行緒的,可與歷史比),多一個 `read-wait=`(主執行緒真的停下來等讀取的時間);`per-stock-compute=` 改成扣 `read-wait`。`read − read-wait` 就是重疊省下的時間。

**量測**(本機 Windows,Python 3.11 / SQLite 3.38.4;合成庫 `make_synthetic_branch_db.py --stocks 800 --days 500 --branches 300 --warrants-per-stock 10 --stock-rows 22 30 --warrant-branch-days 150` → `convert_branch_raw_without_rowid.py --analyze`:現股分點 1,040 萬列＋權證 240 萬列,1.8 GiB;每次獨立行程、各自一份 DB 副本、`PYTHONHASHSEED=0`)

| 段(秒) | 舊(73c5401)兩次 | 只做 1–3 | 1–4(最終) |
|---|---|---|---|
| read | 38 / 36 | 25 | 48(背景;GIL 競爭讓它變長,但與計算重疊) |
| read-wait | — | — | 19 |
| per-stock-compute | 112 / 106 | 35 | 29 |
| write | 2 / 2 | 2 | 2 |
| **total** | **152 / 144** | **62** | **50(−65%)** |
| 行程記憶體峰值(Peak Working Set) | 300 MiB | 296 MiB | 299 MiB |

- **逐位元一致**:三張寫入的表依**實體(rowid)順序**逐列比對(`branch_stock_stats` 240,000 列、`branch_rankings` 300、`tracked_branches` 80,`updated_at`/`added_at` 除外)PASS;`tools/compute_parity.py` 的全庫 PK 順序雜湊 PASS;兩份 DB 各跑一次 `export-json` 再 `export_parity.py`:3,439 檔 IDENTICAL,0 TIMESTAMP/ORDER-ONLY/VALUE/MISSING。
- **單元層**(`pipeline/tests/test_branch_stats_parity.py`):把改前的逐檔迴圈原文當基準,在刻意帶麻煩的隨機庫(同名不同 branch_key 同日多列、NULL 淨額/pct/賣張、缺開盤與開盤 0、還原因子、沒有日K的分點日、停業分點、追蹤/自動/muted)三個種子上比 `last_seen`、`branch_aggs`(插入順序＋每個累加欄位)、`stock_stats`(插入順序＋值)全等;`_merge_rows_by_branch` 對 `merge_by_date` 隨機 200 組(含型別);背景讀取的錯誤傳遞與提前關閉。突變測試(同名同日改成「留最後一列」)會被抓到。
- 合成庫的資格比例偏高(pct 均勻 0–8%),同名同日多列也比正式機多;正式機逐列的固定成本(第 1 點)佔比更大。

**正式機預估(誠實區間;以合併後第一輪 `branch stats timing:` 為準)**:10-20 的 658 s 怎麼分成 read / compute / write,要看當晚那一行(本工作沒有連正式機)。本機舊程式 compute ≈ 3 × read(全在 OS 快取);正式機讀取是冷的。
- 偏 CPU(read ~150、compute ~480、write ~25):compute ×0.27 ≈ 130 s,與讀取重疊 → **約 170–220 s**。
- 偏 I/O(read ~400、compute ~230):讀取本身省不了,compute 被讀取蓋掉 → **約 420–450 s**。
- 所以 **658 s → 約 170–450 s(省 3.5–8 分)**;`read-wait` 小 = 讀取已被計算蓋住,`read-wait` ≈ `read` = 純等磁碟(那時下一步只能是減少讀取量,見下面「沒做的」)。

**第二段順序(`daily-branches.sh`)**:`compute-branch-stats` 改排在 `warrant_phase_finish` **之前**(第一段上線之後)。它不讀權證分點列,as_of = `MAX(branch_trades.date)` 此時已是今天(今天的現股列已寫入,權證列的日期不會更晚),所以先算後算結果相同;好處是背景的權證抓取還沒收工時,統計與它重疊,而不是先空等權證(等的時候放 DB 鎖)再算統計。10-20 權證 19:28 收工、第一段 19:29 才上線,這種日子省 0;加了上櫃權證(+171 檔,~+3 分,`docs/47` §8.10 第 5 點)之後權證約晚於第一段 1–3 分收工 → 省 1–3 分;只剩 3 站的慢夜(權證 ~22 分)省到統計的全長。第二段匯出照舊在權證寫入之後。代價:統計失敗中止本輪時,權證這一輪不寫(EXIT trap 收掉抓取,暫存檔留著),由 22:30 續抓寫入——以前統計失敗時權證已經寫進去了。邊界:股票段離開碼 76(這一輪一筆現股都沒抓到)而權證段抓到今天的列時,以前 as_of 會被權證列推到今天、現在是前一個有現股列的日子(現在的比較對:當天沒有現股列);兩個來源是同一批鏡像站,幾乎不會只死一半。

**預期第二段上線時間**:19:29 第一段 + 統計(3–7.5 分,與權證尾段重疊)+ 權證寫入 5 s + export 660 s + deploy ~1 分 ≈ **19:44–19:49**(以前 19:52;省 3.5–8 分)。

**沒做的(提案;需人類決定)**
1. **第二段匯出只重算會變的部分**(省最多;**2026-10-25 以「輸入照讀、只省計算」的方式實作,見 §3.7**——下面是當時的提案原文):第一段與第二段之間只有兩件事改了資料——今天的權證分點列、三張統計表。export 讀它們的地方:權證分點輸出全部(`warrant_branches.json`、`warrant-stock-details/*`、`warrant_positions.json`、`warrant_movers.json`、`branches/watch/*` 的權證欄)、個股 chips 的 `branch_tags`(追蹤＋`branch_stock_stats` 的隔日沖配對)、個股 `active_warrants[].branches`(當天權證列)、口袋名單(`pocket_*`,radar/home/core)、`branches/rankings.json`、`branches/track/*`、`branches/today.json`。**一個位元都不會變的大項**:`branch_history`(10-14 實測 220 s)、`pnl`(116 s)、`pctile`(78 s,那張表 00:05 才算)、`candles`/`levels`(22 s)、hist。做法:第一次 export 把每檔這幾項的中間結果落一份快取(`data/` 下,以「現股分點列＋日K」的指紋為鍵,例如 `branch` 那列 import_logs 的 id＋`daily_prices` 的 MAX(date)＋筆數),第二次 export 指紋相同就直接用。估計第二段 export 660 → **約 220–300 s(再省 6–7 分;第二段約 19:38–19:42)**。風險在「依賴清單」寫漏:要用 `export_parity.py` 對「快取路徑」與「全量」兩棵樹逐位元比對,並把依賴清單寫成測試。改動面在 `json_export` 的個股主迴圈,不小,這次不做。
   - `docs/44` §3.5 舊提案的 `--skip-warrant-shards` 在兩段式之後**不成立**:第一段與第二段之間權證列會變。
2. **排行統計移出晚上那條鏈**(產品決定):第二段只帶權證,統計留給 00:05 夜間作業算＋上線 → 第二段 ≈ 19:29 + 11 分 ≈ 19:41,代價是排行榜晚幾小時才含今天。
3. **統計與第一段 export 並行**(唯讀計算,寫入延到第一段上線之後):要先量 VPS 的 `nproc` 與兩者同時的記憶體峰值(export ~700 MB＋統計 ~300 MB,1.7 GB RAM);單核機上會拖慢第一段,不建議在沒量之前做。
4. **再減讀取量**(若 `read-wait` ≈ `read`):讀取的是全部現股歷史;唯一的辦法是讓分點×個股的全期統計可增量更新(見上面「不做增量」),目前不值得。

### 3.7 export 記憶:第二段匯出沿用第一段的純計算(2026-10-25;程式在分支,未合 main;不動 crontab、不動 VPS 腳本)

**問題**:正式機 2026-10-21 第一段 export 728 s(19:16→19:28)、統計 240 s、權證寫入 5 s、第二段 export **720 s**(19:34→19:46)、19:48 上線。兩次 export 之間只變了今天的權證分點列(＋新分點名)、`branch_stock_stats`/`branch_rankings`/`tracked_branches`;現股分點列、日 K、`branch_stock_pctile_counts`(00:05 才換)都沒變,但個股迴圈裡最貴的純計算每次從頭算:`export timing:` 正式機 branch_history≈170–190、pnl≈93、pctile≈66–74、levels≈6、write≈50。

**做法(輸入照讀,只省計算)**:`pipeline/radar/export/export_memo.py`。每一段的輸入**每次照舊從 DB 讀出來**,對讀到的值算摘要(blake2b-128 over `marshal` 版本 2:同值同型別 → 同位元組,int/float/str/None 分得開),與上一次 export 記下的相同就沿用上一次的輸出,不同就照算。所以不必猜「誰可能寫過」(rowid/筆數/MAX(date) 這類表層指紋抓不到 UPDATE、`adj_factor` 改寫、修復窗重寫)——讀到的列本身就是指紋。依賴清單(每段另加:整個 `radar/` 套件原始碼雜湊＋Python 版本,程式一改全部不命中):

| 段 | 摘要涵蓋的輸入 | 沿用來源 |
|---|---|---|
| `branch_days` | 資料日 d ＋ `branch_trades_raw` 該檔 730 日主鍵範圍原始列 (date, branch_id, buy, sell, net) ＋ 分點名查表條件(下) | 上一次的 `chips/{id}.json` 切那段文字 |
| `branch_pnl_est` | 同上 ＋ 該檔 K 線全欄位 | 同上(上一次沒有這鍵 = None) |
| `branch_pctile_counts` | 該檔 `branch_stock_pctile_counts` 全部列(讀取順序)＋ 快照中繼資料 ＋ 表在不在(計算不看 d) | 同上 |
| `price_levels` | d ＋ 該檔 K 線全欄位 | 記憶檔(很小,JSON 往返逐位元相同) |

- **分點名**:摘要是 branch_id 不是名字。上一次記下的整份 id→名稱,在這一次開頭的查表裡任何一個改了或不見 → 這一輪分點段全部不命中(新增 id 不影響:新 id 若出現在某檔的列裡,那檔的原始列摘要就變了)。迴圈中途只要發生過一次查表重讀(有查不到的 id,`_BranchNames.reloads`)→ 之後的個股分點段不命中、記憶檔不寫(重讀可能帶進並行改名;測試 `test_rename_seen_by_mid_run_reload_stops_reuse` 模擬了這個時序)。沒重讀 ⇒ 上一次每一列的 id 都查得到 ⇒ 原始列相同時名字也相同。
- **沿用的段不解析**:chips 檔的文字整份雜湊記在記憶檔,讀回來雜湊對得上才用(並行 export 改寫過、被截斷、被刪 → 當沒記錄,`chips_bad=` 計數);各段在文字裡的位置也記著,直接切下(`stock_parts.RawJSON`)原樣拼進這一次的 chips(`compose_chips`:緊湊模式的物件 = `{` + 逐項 `鍵:值` + `}`,與整份 `dumps` 逐位元相同,300 組隨機 payload 驗過)。`branch_tags` 要的分點名表只解析 `names` 那一小段(位置在寫出時就以「切下來的文字 == dumps(names)」核對過)。本機量到「讀回整份 chips 再 json.loads」與重新編碼一樣貴,所以才切文字。
- **記憶檔**:`config.DATA_DIR/export-memo/<輸出目錄路徑雜湊>.json`,一個輸出目錄一份、每次整份 tmp+rename 覆寫(正式 ~2,400 檔約 3 MB;合成庫 800 檔 0.93 MB);同目錄超過 7 天沒更新的別份順手刪。export 中途失敗 → 不寫,舊記錄的 chips 雜湊對不上新檔 → 自動不命中。`RADAR_EXPORT_MEMO=0` 關掉(照舊全算、不寫);`--legacy-stocks`/`--verify-split`/`--size-report` 自動關(它們要完整 payload 物件)。
- **不限第二段**:它是通用的「同輸入不重算」,任何一輪都可能命中:14:05 換日那輪分點/損益/價格位置全部重算(摘要含 d),但分位計數照樣沿用;14:45/16:00/20:45 同一資料日,現股分點列沒變 → branch_days 命中,K 線沒變的檔 → 損益/價格位置也命中。第一段 export 多付摘要成本(本機 +2–3 s/800 檔)。
- **log**:`export timing:` 末尾多 `memo=`(載入＋存檔);新的一行 `export memo: enabled= loaded= names_ok= stocks= branch= pnl= pctile= levels= chips_bad= reloads=`(後四個是命中檔數)。

**驗證**
- `pipeline/tests/test_export_memo.py`(12 項):小合成庫照晚上分點輪跑——第一次 export → 寫入今天權證分點列(含新分點名 `branch_dim` 9001)＋刪自動追蹤後重算 `compute_all` → 第二次 export 寫同一目錄,與 `RADAR_EXPORT_MEMO=0` 在空目錄全量重算逐檔比:**位元組相同,或只差 `generated_at`(以保留鍵序的 (鍵,值) 串列比,鍵序不同也算錯)**,並斷言每檔四段全部命中;第三次(沒變)仍全命中。失效:改一列舊現股分點列(只有那檔 branch_days/損益重算)、改一天收盤(那檔損益/價格位置重算)、改 `adj_factor`、改分位表一列、分點改名(`names_ok=0`,分點段全重算)、孤兒列觸發重讀(記憶檔刪掉)、中途重讀時並行改名、竄改 chips 檔、程式雜湊不同、新的資料日;每一項都與全量重算逐檔比對。另有 compose_chips 與 dumps 逐位元相同、摘要對型別/順序敏感。
- 突變測試(各自單獨套用、跑一次測試檔):拿掉 names_ok、拿掉重讀守衛、價格位置不看 K 線摘要、分位不看摘要、chips 不驗雜湊、分點摘要不含 d、損益不看 K 線摘要 → 全部有測試失敗。
- **合成大庫**(§3.5 同一份:`make_synthetic_branch_db.py --stocks 800 --days 500 --branches 300 --warrants-per-stock 10 --stock-rows 22 30 --warrant-branch-days 150` → `convert_branch_raw_without_rowid.py --analyze` → `compute-branch-stats` ＋ `branch-stock-pctile-counts`;現股分點 1,106 萬列/2 年窗、1.8 GiB;`PYTHONHASHSEED=0`、各自獨立行程)。今天的權證分點列(17,097 列)先移開 → 第一次 export → 放回＋刪自動追蹤＋`compute-branch-stats` → 第二次 export(同目錄)→ 空目錄全量(記憶關)＋舊程式(HEAD 3cb3499)空目錄全量:

| 段(秒) | 第一次,記憶關 | 第一次,記憶開(兩次) | **第二次,記憶開(兩次)** | 全量重算,記憶關 | 舊程式全量 |
|---|---|---|---|---|---|
| branch_history | 28.1 | 30.6 / 27.1 | **17.2 / 17.5** | 24.9 | 26.3 |
| pctile | 5.9 | 6.2 / 5.4 | **2.0 / 2.0** | 4.9 | 5.1 |
| pnl | 23.2 | 20.4 / 17.5 | **0.0 / 0.0** | 17.0 | 16.5 |
| levels | 1.0 | 1.0 / 0.9 | **0.0 / 0.0** | 0.8 | 0.9 |
| write | 23.9 | 23.5 / 20.6 | **13.3 / 13.4** | 20.1 | 20.9 |
| watch | 3.3 | 3.4 / 3.2 | **2.1 / 2.1** | 3.4 | 2.9 |
| warrant_shards(不沿用) | 33.1 | 27.5 / 28.1 | 29.3 / 29.8 | 27.9 | 28.7 |
| **total** | 134.6 | 126.8 / 116.8 | **77.4 / 78.7** | 112.3 / 114.8 | 114.4 |
| 行程記憶體峰值 | — | — / 874 MiB | 885 / 886 MiB | 880 MiB | 878 MiB |

  - **逐位元一致**:第二次(記憶)vs 全量(記憶關),兩輪各比一次:3,423 檔 = 3,415 IDENTICAL + 8 只差 `generated_at`(鍵序保留比),0 DIFF/MISSING/多出;全量(記憶關)vs 舊程式全量:同樣 3,415 + 8 / 0。第三次(什麼都沒變)`unchanged=1600`(core/chips 一個都沒重寫)。
  - 第二次本機 **−31%(112 → 77 s)**:pnl/levels 歸零;branch_history 剩的是讀取本身(`fetchall` 1,100 萬列 ≈ 13–17 s,摘要 ≈ 2.6 s);pctile 剩讀取＋摘要;write 少了 chips 三段的序列化。記憶體 +~5 MiB(記憶檔的 dict;遠低於 50 MB 上限)。

**正式機預估(誠實區間;以合併後第一個分點輪的 `export timing:` / `export memo:` 為準)**

| 段 | 正式第二段(10-21) | 預估 | 依據 |
|---|---|---|---|
| pnl | ~93 s | ~0 | 純計算,全命中 |
| levels | ~6 s | ~0 | 同上 |
| pctile | 66–74 s | ~25–35 s(省 ~40) | 本機剩 ~40%(讀取＋摘要) |
| branch_history | 170–190 s | ~120–150 s(省 ~30–60) | 本機剩 ~70%(讀取為主);正式機若更偏讀盤,省得更少 |
| write | ~50 s | ~30–35 s(省 ~15–20) | 本機剩 ~66% |
| watch | ~15 s | ~10 s | 命中時只查近 60 日名字 |
| 其餘(warrant_shards、tracked、radar、side…) | ~300 s | 不變 | 權證列與統計表真的變了 |

- 合計第二段 export **720 → 約 500–540 s(省 ~3–3.7 分)**;第一段 export 多付摘要成本,依本機比例約 +10–20 s。整輪淨省約 3–3.5 分 → 第二段上線約 **19:44–19:45**(10-21 是 19:48)。
- 比 §3.6 提案估的「220–300 s」保守:那個估計假設 branch_history 整段可省,但不讀列就無法**確定**列沒變;剩下的 ~120–150 s 是讀 3,300 萬列本身。要再省只能**不讀**——例如由 `daily-branches.sh` 告訴第二段「兩段之間一直握著 DB 鎖、沒有別的寫者」就跳過讀取(信任鎖紀律,不是驗證),或在 DB 加變更計數(schema 變更)。兩者都屬「仍須人工確認」,本次不做。

**風險**
- **寫漏依賴**:每段的輸入清單在 `export_memo.py` 開頭與上表;任何人改這四段的計算,若引入新的輸入(新查詢、新表),必須同時加進摘要,否則會沿用舊結果。緩解:程式雜湊含整個 `radar/` 套件,**部署新程式後第一輪一定全算**;新輸入若是 DB 讀取,只要沒進摘要,同一程式版本內才會出事——`test_export_memo.py` 的失效測試是這份清單的守門員,改段落時要補對應測試。
- 摘要碰撞:blake2b-128,可忽略。
- 並行 export(`mid-backfill-publish.sh`,不持鎖、同一輸出目錄、同一份記憶檔):各自記自己讀到的摘要與自己寫的 chips 雜湊,最後寫的那份記憶檔生效;另一個 export 改寫過的 chips 雜湊對不上 → 不命中。最壞是少命中,不會沿用錯的。
- 磁碟:每個輸出目錄一個檔(正式 ~3 MB),7 天沒更新的自動刪。

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
