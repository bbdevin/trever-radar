# 20 產品與策略簡化計畫(B 方案,2026-07-10 定案)

> 本文件記錄使用者於 2026-07-10 確認的 B 方案,供後續 Planner / Executor / Reviewer 接手。
> 這是目前功能整合與刪減工作的 source of truth。若與 `docs/04_signal_rules.md`、
> `docs/07_frontend_pages.md` 或 `docs/STATUS.md` 的舊待辦衝突,以本文件為準;
> 既有 Python + SQLite + 靜態 JSON + Next.js 架構不翻案。

## 1. 決策摘要

目前優先目標不是增加頁面或策略,而是建立可信度閉環:

1. 減少重複頁面與重複訊號。
2. 將獨立策略與綜合評分解耦。
3. 用既有 `daily_scores` 前瞻報酬決定策略是否值得顯示。
4. 暫停資料證據不足、容易誤讀的功能擴張。
5. 最後才另案評估排程與部署簡化。

在本計畫完成前,**不新增第 14 個策略、不補做 `/explore` 原規劃的四個 tab、
不啟動五年分點擴容、不開始 LINE Bot 或 V2 盤中功能**。

**例外(已另案規劃、仍非本文件 Phase 內實作)**:使用者於 2026-07-10 確認
`docs/22_armed_tracking.md` 為 B 方案之後的產品下一刀——用 Armed/Triggered
狀態池追蹤「未發動」與「已發動」,重用既有 S12/W3/B3,不新增策略 code、
不抬綜合分。該文件程式尚未實作;不得借本文件 Phase 1–4 之名義提前開做,
也不得與 Access/R2/排程簡化混在同一任務。

## 1.1 Phase 狀態

| Phase | 狀態 | 備註 |
|---|---|---|
| Phase 0 文件化 | ✅ 完成(2026-07-10) | 本文件及共同記憶入口已更新 |
| Phase 1 UI 刪減與合併 | ✅ 完成(2026-07-10) | 低風險,但仍須先看現有 diff;完成後為 `docs/22` 騰出首頁空間 |
| Phase 2 策略/分數解耦 | 🔄 進行中 | 解耦程式+測試已完成(2026-07-10);差異報告 CLI 已完成並於 2026-08-31 hardened 為真正唯讀;VPS 最新日報告+正式重算待使用者批准 |
| Phase 3 策略績效閉環 | ⏳ 待確認 | 客觀報表產出器已於 2026-08-31 hardened 為真正唯讀；仍須人類看過報告才可決定策略治理，有助判斷 S12 是否適合作 Armed 主訊號 |
| Phase 4 排程簡化 | 📝 提案稿已改寫(2026-08-20) | 對齊 VPS cron+Worker 資料層;cron/script **未改**,待另確認目標態或變體 B |
| 之後 → `docs/22` Armed | 📝 規劃定案 | 見該文件 A1–A3;不屬本 B 方案 Phase 編號 |

## 2. 審計依據與核心問題

### 2.1 策略與技術分目前混在一起

`pipeline/radar/compute/indicators.py::score_technical()` 先依 T1-T5 計算技術分,
之後 S1-S10 又透過同一個 `add()` 加 15-20 分。多數策略重複使用均線、突破、
量能、MACD 等已給分條件,因此會重複推高 `tech_score`。相反地,S11-S13 在
`compute/scores.py` 只加入 reasons,不改法人分或分點分,13 個策略的計分語意不一致。

**定案方向**:T1-T5 才是技術分來源;S1-S13 改為獨立的 setup/tag 偵測結果,
不得直接增加任何分項分數或綜合分。既有 S code 保留,避免歷史追蹤失去對照。

### 2.2 有績效回填,但沒有策略淘汰閉環

`daily_scores` 已有 `entry_price` 與 `fwd_1d/3d/5d/10d/20d`,但目前沒有輸出
各 S code 的樣本數、勝率與平均報酬。後續不得只看「今日出現幾檔」判斷策略好壞。

**定案方向**:先輸出客觀績效,再由使用者決定哪些策略升為 Active。未達足夠成熟
樣本前一律視為 Shadow,不宣稱有效。

### 2.3 `/explore` 與既有頁面重複

- 題材 tab 使用首頁既有的 `radar.themes`。
- 集中度是分點 B3 / S12 已使用的同一組資料。
- 分點績效、關鍵分點應屬 `/branch`。
- 權證異動首頁已有榜單;地緣模型尚無足夠可靠資料。

**定案方向**:題材只留首頁;集中度併入 `/branch` 的「今日動向」區;
之後移除 `/explore` 路由與導覽。原規劃剩餘四個 tab 取消,不是待完成項目。

### 2.4 權證大戶的證據不足

免費權證分點多為發行商造市/避險,現行聚合也可能在缺價格時以 1.0 估值。

**定案方向**:在能排除發行商並標示價格完整度前,前端改稱
「權證分點異動(實驗)」,不得以「大戶卡位」作確定性描述,也不得納入綜合分。

### 2.5 登入是體驗層,不是資料安全層

`radar.json` 是公開靜態檔,即使前端未登入時隱藏策略 tab,資料仍可直接讀取。

**2026-07-10 後續定案**:使用者已選 A 私人測試版,依
`docs/21_private_beta_access_r2_plan.md` 啟用 Cloudflare Access 整站白名單;
Supabase Auth / watchlist 保留作跨裝置個人化,不再擴張假性會員資料閘門。

## 3. 目標資訊架構

### 保留

- 首頁:市場狀態、資金流、綜合榜、基礎市場榜、策略觀察。
- `/stock`:K 線、分點、權證、理由與風險。
- `/branch`:可信度排行、今日動向、集中度、權證分點實驗資料。
- `/watchlist`:Supabase 跨裝置自選。

### 合併或移除

- 題材探索 → 首頁 MoneyFlow。
- 集中度探索 → `/branch` 今日動向。
- `/explore` → 完成遷移後刪除。
- 尚未實作的盤中雷達導覽 → 功能真正進入 V2 開發前先隱藏。

### 暫停/延後

- 地緣分點、關鍵分點人工名單 UI。
- 五年分點歷史、R2 / `branch_hist.db` 架構擴張。
- LINE Bot、V2 盤中、完整 admin 後台。

## 4. 策略治理模型

### 4.1 四個 UI 類別(不改既有 S code)

| 類別 | 初始包含 | 說明 |
|---|---|---|
| 突破發動 | S2 / S3 / S4 / S6 / S7 / S8 | 條件高度相近,UI 先分群,績效足夠後再判斷是否合併或淘汰 |

> **S4 V2（2026-08-27，程式與測試完成、未宣稱正式資料回算）**：同一 S4 家族改為
> `S4_COMPRESSION_SETUP_V2`（壓縮蓄勢）→ `S4_COMPRESSION_BREAKOUT_V2`（壓縮突破），
> `S4_VOLATILITY_CONTRACTION` 凍結為 legacy。三者績效分開；setup 連續日依完整 `daily_prices`
> 交易日曆按 episode 去重（不從成熟 fwd/daily_scores 日期推估）；績效視窗左界用前一有收盤交易日 warm-up 後才裁回。
> 對外 `strategies.S4_VOLATILITY_CONTRACTION` 仍為三者聯集，phase 只提供排序與標示，不改分數或 Armed 語意。
| 趨勢續強/回踩 | S1 / S5 / S9 | 已有強勢背景後再次發動或回踩 |
| 低檔反轉 | S10 | 與突破型態不同,獨立觀察 |
| 籌碼事件 | S11 / S12 / S13 | 法人、分點集中、融券回補 |

這只是 UI 分群,不得在沒有績效證據前合併或改寫歷史 S code。

### 4.2 生命週期

- **Candidate**:新規則,只有測試資料,不得上正式主介面。
- **Shadow**:正式每日計算並記錄績效,但不宣稱有效。
- **Active**:成熟樣本與績效報告完成後,由使用者明確核准顯示。
- **Retired**:績效不佳、失效或與其他策略高度重複;停止主介面顯示,歷史 code 保留。

**2026-08-19 Phase 3 的歷史決議**曾將 S2、S5 設為 Retired；其餘 S1–S13 及 S4 V2 phase 為
Shadow，沒有 Active。Retired 的 frozen reason code、`strategies` JSON key 與歷史績效都必須保留。

**使用者覆寫（2026-08-27，現行治理真相）**：S2、S5 自 Retired 恢復為 **Shadow**；其餘策略
亦為 Shadow，**無 Active／Retired**。這是恢復觀察的 metadata 決策：Shadow 回主要策略選擇器，
但不宣稱有效，且**不改任何策略公式、分數、權重、`final`、selector cap 或 DB**。不得由 Executor
自訂勝率門檻後自行升級；先交付樣本數、5/10/20 日勝率、平均/中位報酬與時間區段穩定性，再由使用者選擇。

**A2 lifecycle contract（2026-08-27）**：`radar.strategy_meta[code]` 以 additive、版本化欄位
輸出 `status / effective_date / rationale / decision_ref / version` 加既有績效欄位；這是 repo 內
可審查的顯示治理資料，不寫 DB、不改分數或既有 selector。舊 JSON 缺 lifecycle metadata 時，前端
必須保留所有既有 selector，不能把缺值誤判為 Retired；lifecycle v2 對 S2／S5 的 Shadow 覆寫不影響
frozen reason code 或任何歷史績效資料。

## 5. 分階段執行清單

### Phase 0:文件化(本次任務)

- 新增本文件。
- 在 `AGENTS.md`、`project-context.md`、`STATUS.md` 加入入口與優先順序。
- 在 04/07 舊規格加上 superseding notice,避免後續模型照舊擴張。

### Phase 1:低風險 UI 與死碼整理

預計檔案:

- `web/app/layout.tsx`
- `web/components/BottomNav.tsx`
- `web/app/explore/page.tsx`
- `web/app/branch/page.tsx`
- `web/package.json` / `web/package-lock.json`
- 必要前端測試或 build 驗證

工作:

1. 隱藏尚未實作的盤中導覽。
2. 將集中度內容併入 `/branch` 今日動向,確認手機/桌機可讀。
3. 題材只留首頁,移除 `/explore` 導覽與頁面。
4. 「權證大戶」改名「權證分點異動(實驗)」並補資料限制說明。
5. 移除確認未使用的 `recharts` 及未引用 UI primitive;不得順手換 UI 框架。

驗收:`npm run build` 通過;首頁、branch、stock、watchlist 靜態路由仍可用;
無資料時有教育性空狀態。

### Phase 2:策略與技術分解耦(高風險資料語意變更)

預計檔案:

- `pipeline/radar/compute/indicators.py`
- `pipeline/radar/compute/scores.py`
- `pipeline/radar/compute/phase2_diff_report.py`（✅ 2026-08-19,CLI `phase2-diff-report`）
- `pipeline/radar/cli.py`
- `pipeline/tests/test_indicators.py`
- `pipeline/tests/test_scores.py`
- `docs/reports/phase2_score_diff_*.md`（差異報告輸出,不寫 DB）
- 可能新增獨立純函式模組及對應測試,但不得重構整個 compute 目錄

工作:

1. 將 S1-S10 偵測抽離技術分加總;仍輸出相同 S code 與理由。
2. 統一 S1-S13 為「只產生 tag/reason、不改分數」。
3. 補 S2-S13 各自的正例、反例與邊界測試。
4. 驗證 T1-T5 在移除策略 bonus 後仍符合 `docs/04` 原技術分規則。
5. 產出舊/新 `tech_score` 差異報告,交 Reviewer 與使用者確認。(✅ 工具已完成:`python -m pipeline.radar.cli phase2-diff-report [--date YYYYMMDD] [--out path]`;本機樣本見 `docs/reports/phase2_score_diff_2026-07-06.md`;**VPS 最新資料日重跑仍待確認**)

> **G-RO 唯讀硬化（2026-08-31）**：Phase 2 diff 與 Phase 3 strategy-performance 兩個報表入口不再呼叫 `init_db()`；只開既存實體 SQLite 的 URI `mode=ro`，先驗檔頭與必要表，缺 DB／非 SQLite／缺表立即 fail closed。`--out` 不可指向 DB、`-wal/-shm/-journal` 或其既有 symlink／hardlink alias。為看見 active writer 的最新 WAL frames，SQLite 可能改寫 `-shm` reader-lock/read-mark 協調 metadata；報表本身不改 DB／WAL 內容、不做 DDL/DML／migration。完整 pipeline pytest **278 passed、58 subtests**，Luna High review **APPROVE**；**未跑正式 VPS 報表、未作正式 DB 回算或動 cron。**

**禁止事項**:完成程式碼不等於可重算正式資料。全市場 `compute-indicators --all`
與重新部署會改變正式榜單,必須先由使用者另外確認 VPS / Actions 重算與回灌方式;
不得自行 push `main`、觸發 `task=adjust` 或清 Actions cache。

### Phase 3:策略績效閉環

預計檔案:

- `pipeline/radar/export/json_export.py`（Phase 3 進一步接 UI 時使用）
- `pipeline/radar/compute/strategy_performance.py`（✅ 2026-08-19:只讀策略績效報告產出器）
- 對應 pytest
- `web/app/page.tsx` 與必要型別

工作:

1. 依 frozen S code reasons 連結 `fwd_5d/10d/20d`（由 `strategy_performance.py` 產出）。
2. 輸出每策略成熟樣本數、勝率、平均/中位報酬及最近區段表現（先以 markdown 報告形式落檔）。
3. 首頁策略 UI 先按四類分群,顯示 Shadow/Active 狀態與樣本不足提示（下一步接 UI；需要同步新增 JSON/型別）。
4. 不以「出現檔數」代替績效;不隱藏失敗樣本。
5. 使用者看過報告後才決定 Active / Retired 清單。

> **2026-08-27 勝率統計唯讀稽核摘要**：策略事件定義為 D 日收盤訊號，D 後第一根有效的還原開盤進場；`fwdN` 是第 N 根有效還原收盤，`win` 嚴格採報酬 `> 0`。統計只涵蓋 `daily_scores` 評分池及近 180 個成熟評分日，不代表全市場；一般策略每日觸發各算樣本，S4 setup 連續日依 episode 去重。已知債務為 NULL K 線壓縮 horizon 與評分池 selection bias，另案處理。

### Phase 4:排程與部署簡化(獨立高風險任務)— **提案稿(2026-08-20 改寫,尚未執行)**

> **背景校正(WP-B3 後)**:舊稿假設 GitHub Actions 每日最多 5 次完整 build/deploy + cache/release DB 續存鏈。**現行真相**(`docs/08` §0、`docs/31`):`radar.db` 常駐 VPS 單一寫者;每日多輪 VPS cron 各自 `export-json` + `wrangler deploy`(資料 Worker 資產);GitHub `deploy.yml` 只在 push `main` 時部署**程式碼/前端**,不碰資料。WAL checkpoint 在 `vps/scripts/weekly-backup.sh`,不在 Actions。

#### 4.1 目標(不變的產品意圖)

保留各資料源取得時點(行情 14:00、法人 16:00、分點晚間補抓),但降低「全量 JSON 匯出 + Worker 資料部署」的尖峰次數與重疊風險,避免多輪搶 `flock` / 重複 Fugle spark 抓取。

#### 4.2 建議目標態(待使用者確認後才改 cron / script)

| 台北時間 | 仍跑資料取得 | export-json + Worker deploy | 備註 |
|---|---|---|---|
| 平日 14:10 | 日K+權證+指標+分數(+週一 geo) | **是**(行情快照版) | 首頁資料日當天變今天;含 spark_day |
| 平日 16:10 | 法人+權證主檔+重算分數 | **否**(只寫 DB) | 法人 freshness 可在前端標「暫用前日」直到晚間 deploy |
| 平日 17:40 | 融資券+分點+分數+績效 | **否**(只寫 DB) | 與現行 `daily-branches` 同源 |
| 平日 21:00 | 分點第二輪(冪等補抓) | **否**(只寫 DB) | |
| 平日 22:10 | 融資券保底+重算 | **是**(完整資料版) | 合併當日所有晚公布資料後一次匯出 |
| 每天 01:10 / 週六備份 | 不變 | 備份腳本不變 | 不得移除 `wal_checkpoint` + `integrity_check` |

可選變體(若使用者寧願法人一到就上站):

- **變體 B**:14:10 + **16:10** + 22:10 三次資料 deploy(法人優先於分點)。

#### 4.3 明確不在本 Phase 自動執行

- 不改 `.github/workflows/*.yml`(資料 workflow 已無觸發,刪檔另案依 `docs/31` §9)。
- 不改 Cloudflare Pages / DNS / secrets。
- 不碰正式 `radar.db` destructive 操作。
- 執行時只動 `vps/scripts/*.sh` 與 `vps/scripts/crontab.example`,並同步 `docs/08` §0 / `vps/README.md`。

#### 4.4 執行前檢查清單(獲確認後)

1. 讀 `vps/scripts/lib.sh` flock 行為與各 daily-*.sh 尾段 `export-json`/`deploy_data` 呼叫點。
2. 確認 16:10–21:00「只寫 DB」時,前端 `freshness.stale` 文案仍誠實。
3. 確認 22:10 一輪能涵蓋法人+分點+融資券,失敗有 ntfy。
4. 回滾:把各 script 尾段 deploy 加回即可(cron 時間表可暫不變)。

#### 4.5 狀態

📝 **提案已落檔,程式/cron 未改**。需使用者另確認「目標態或變體 B」後才開 Executor 實作包。

此階段會碰 VPS cron 與資料部署頻率,必須另走 `docs/17` 高風險流程。執行前完整閱讀 `docs/08` §0、`docs/31`、`vps/README.md`、各 `vps/scripts/daily-*.sh`;不得移除 WAL checkpoint。

## 6. Reviewer 必查項目

1. S code 是否仍可追蹤,且不再影響任何分項分數。
2. 是否有 S2-S13 測試,而非只測 S1。
3. 策略績效是否使用次一交易日開盤為 entry,沒有偷看未來。
4. UI 是否誠實顯示樣本不足、免費分點裁剪及權證造市限制。
5. 是否真的減少頁面/導航,而非把 `/explore` 原樣複製成新的大頁。
6. 是否誤動 `adj_factor`、WAL checkpoint、DB cache/release 續存鏈。
7. 是否在未獲使用者批准前重算、回灌或部署正式資料。

## 7. 成功標準

- 一級導航不再顯示空殼 V2 功能或重複探索頁。
- 題材只有一個主要入口;集中度屬於分點工作流。
- S1-S13 不再改變 `tech_score` / `final`,但歷史 code 仍可對照。
- 每個策略都有可讀的樣本數與前瞻績效,使用者可做 Active / Retired 決策。
- 權證分點不再被描述成已證實的主力卡位。
- 排程簡化若執行,資料續存鏈與 WAL 安全性不得退步。

## 8. 給下一個 agent 的固定起手式

接手本計畫時:

1. 先讀 `AGENTS.md`、`project-context.md`、`STATUS.md`、`docs/17`、`docs/18` 與本文件。
2. 查看 `git status`、`git diff`、目前 branch 與前一階段 handoff。
3. 只執行使用者明確確認的單一 Phase,不得一次跨多階段。
4. 先列目標檔案、測試與正式資料影響,等待確認再改。
5. 完成後更新 `STATUS.md` 與本文件的 Phase 狀態,留下可接手 handoff。
