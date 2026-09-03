# 專案狀態（2026-08-31）

> 單一進度真相。每完成一個里程碑就更新本檔。規格細節看各編號文件,別寫在這裡。

## 2026-09-02 權證分點 export 資料日修正與分點文案一致（程式／測試完成，未跑正式 export）

- [x] `_export_warrant_branches` 先用與主查詢完全相同的條件（`LENGTH(stock_id)=6`、`warrants`／`stocks` join、`type='stock'`、排除含「指」）求出「不晚於報價日、且在近 120 個報價日窗口內」的實際最大權證分點交易日 `bd1`，再以 `bd1` 為 1d anchor，2d／5d／30d 改由嚴格早於 `bd1` 的報價日推導，主查詢另加 `b.date <= :d1` 上界。分點比報價晚一輪公布時，1d 桶不再被清空。
- [x] `branches/warrant-stock-details/index.json` 與 `{stock_id}.json` 的 `data_date` 改為 `bd1`（實際分點資料日），不再是 `daily_prices` 最新日。池內完全沒有符合條件的權證分點時 `data_date` 為 `null`，不拿報價日充數；此時主查詢直接跳過，市場檔仍輸出五個空 timeframe，stale shard 照舊清除。這與 `branches/today.json` 的 `as_of` 是同一種錯，本輪對齊。
- [x] 前端 `WarrantBranchPanel` 的 index／shard `data_date` 型別放寬為 `string | null`，只在非 null 時驗 ISO 格式（否則空池會被誤判成「索引格式錯誤」）；資料日原本就是條件顯示，null 時不顯示，其餘契約（version、threshold、index 為權威、shard 一致性）不變。
- [x] 文案：`BranchTrackView` 表頭「淨買超張」→「淨買賣張」——該表由買超／賣超分頁餵入 sign-filtered rows，賣超分頁顯示的是負值，舊標籤錯。`/branch` 的 tab「今日動向」／hint「買超明細」→「最近動向」／「買進／賣出與淨買賣明細」，與既有標題「分點最近交易日進出」及表格四欄一致。tab key 仍是 `today`（僅內部 state，無 URL 相依）。
- [x] 驗證：targeted `test_warrant_branch_export.py` **3 passed**（新增「分點落後報價一日」與「空池報 null」兩案）；完整 pipeline pytest **314 passed、70 subtests**；`web npx tsc --noEmit`、`git diff --check` 通過。未改 schema、cron、workflow、secrets、評分、門檻或正式 DB；正式站要等下一次 VPS `export-json` 才會反映。
- 環境註記（2026-09-02 已修）：完整 pytest 只需 `cd pipeline` 後執行，不必再設 `PYTHONPATH`。原因是 `test_json_export.py` 兩處用 `from pipeline.radar.importer import …`，與其餘測試檔一律用 `from radar.…` 不一致，才逼出額外的 path 需求；已改為 `from radar.importer`，實測 `PYTHONPATH` 為空時 **314 passed、70 subtests**。在 repo root 跑仍會 collection error（`radar` 不在 path），那是預期。
- 刻意取捨：`b.date <= :d1` 對五個 timeframe 一體適用，所以 120d 桶也收斂到 `bd1`。分點若領先報價日（正常排程不會發生），那些列會被排除而不是計入 120d。選一致性（payload 每個數字都不晚於宣告的 `data_date`）而非完整性。
- [x] **全市場檔補資料日（同日第二輪）**：`branches/warrant_branches.json` 改為 `{version:1, threshold, data_date, timeframes}` v1 wrapper，形式沿用 `today.json` 的既有先例而非另創形狀。`/branch` 權證分頁新增 `normalizeWarrantBranchPayload`，wrapper 與舊的裸 mapping 都能讀，舊檔不捏造日期；分頁顯示「分點資料日 X；各區間由該日往前推算，不含更新的分點資料」。`WarrantBranchPanel` 的 404 fallback 同樣雙讀，只有快照真的帶 `data_date` 才顯示，否則維持「該快照未提供資料日」。500 萬門檻、排序、by_stock／by_branch 檢視均未改。
- [x] 資料與程式碼是分開的發布鏈（push→Pages 幾分鐘；JSON→VPS export 之後才更新），所以新舊組合會並存；雙讀 normalize 就是為此。`docs/07` §個股／branch 段已同步新 payload 形狀。
- [x] `WarrantBranchPanel` 的 fallback 順手收斂兩個不一致：壞掉或非物件的 body 一律變成空 mapping（原本 `null` body 會讓面板永遠停在骨架屏，既不顯示資料也不顯示錯誤，此洞在改動前就存在）；wrapper 的 `data_date` 現在也要通過 `ISO_DATE` 才顯示，與 index 路徑同標準。
- ⚠️ 已知並接受的空窗：**舊 bundle + 新 JSON** 時，舊程式碼對 wrapper 取 `payload["1d"]` 會得到 undefined，畫面顯示「此區間內無淨買賣超 500 萬以上之權證大戶」——這是誤導性空狀態而非誠實空狀態。正常發布順序下不會發生（Pages 幾分鐘、下一次 export 在數小時後）；只在 Pages build 失敗或使用者停在舊分頁時出現，重新整理即修復。這與 `today.json` v1 wrapper 當初接受的是同一種取捨；沒有任何前端修法能讓已載入的舊 bundle 認得新形狀。
- [x] 第二輪驗證：完整 pipeline pytest **314 passed、70 subtests**；`npx tsc --noEmit` 通過。Fable 唯讀 review 走完四種發布組合、13 組畸形輸入、共用常數 mutation 與 `isWrapped` 收斂，結論 **CONFIRMED、0 defect**。

## 2026-09-02 VPS 唯讀查核（16:07–16:15 +08）

- [x] VPS `~/trever-radar` HEAD 已是 `bf65dd0`（日更腳本自行 pull），16:10 `daily-insti.sh` 執行中（`import-warrant-master` 階段），持有 `/tmp/radar-db.lock`。本輪的 `data_date`／anchor 修正會由這條既有排程自然發布，**未手動觸發任何正式 import／export／deploy，未改 cron**。
- [x] 既有四個未追蹤檔（`cloudflare-data-worker/package-lock.json`、`data/`、`radar-quick-catchup.sh`、`run-backfill.sh`）仍在且未阻斷本次 pull。磁碟 `29G` 中已用 `19G`、free `8.1G`（71%）；仍低於 20GB gate，禁止自行啟用全市場權證輪。分點回補 `backfill-branches --top 0 --days 490` 仍單實例執行中，guard／supervisor 各一，未重啟。
## 2026-09-03 稽核方法：找出「指令寫好了，但沒有任何排程呼叫它」的功能

> 今天連續三個問題都屬同一類：程式碼、CLI、匯出、前端型別都在，但**沒有任何在跑的腳本呼叫它**，所以資料永遠不會出現。這個稽核可重複執行，成本很低。

- **方法**：把 `pipeline/radar/cli.py` 的所有 `add_parser("…")` 子命令列出來，與 **`vps/scripts/*.sh`**（真正在跑的那條路徑）比對。**不要把 `.github/workflows/*.yml` 算進去**——那 5 支資料 workflow 已退役、沒有觸發源，卻會讓子命令看起來「有被引用」，`compute-adjustments` 第一次就是這樣被漏掉的。
- **2026-09-03 結果**：34 個子命令，10 個未被任何在跑的 vps 腳本呼叫。其中**設計上就是手動工具**（合理，非缺口）：`branch-point-in-time-report`／`branch-point-in-time-series`／`branch-ranking-v2-shadow` 三支唯讀 shadow、`phase2-diff-report`／`phase3-strategy-performance-report` 兩支唯讀報表、`init-db`、以及 `docs/37` E1 明定為手動 CLI 的 `import-buybacks`。
- **真正的缺口三項**：①`compute-adjustments`（見下節，影響最大）；②`import-stock-info` 最後成功為 2026-07-07、僅 2 次，**2,494 檔 active 股票中有 19 檔沒有產業別**，且**新上市個股將永遠沒有**——產業別餵首頁族群資金流 treemap 與個股頁；③`import-descriptions` 為 **0/2,494**。
- **③ 的實際影響低於文件宣稱**：`stocks.description` 只出現在 `web/lib/types.ts:385` 的型別宣告，**前端沒有任何元件渲染它**（`json_export` 仍會帶出）。所以它是休眠的程式碼路徑，不是使用者看得到的缺口——但本檔完成清單寫「股票卡資訊優化…新增公司基本業務說明 (Description)」，該宣稱**不成立**，很可能是 `docs/37` B 的 `company_profiles`（1,985 筆、1,984 筆有地址）取代它之後沒有回頭修文件。
- **反向驗證**：`branch-point-in-time-persist` **沒有**出現在未呼叫清單中，因為它今天剛被接進 `safe-branch-stats.sh`——這確認了該稽核確實反映真實連線狀態。

## 2026-09-03 ⚠️ 重大資料缺陷：`adj_factor` 全市場從未計算，還原價實際上不存在

> 唯讀稽核發現，尚未修復，**需人類決定**。這是目前已知影響面最大的資料問題。

- [x] **事實**：2026-09-02 有報價的 **2,393 檔全部 `adj_factor = 1.0`**；整個資料庫**只有 1 檔股票（2330）**有非 1 的還原因子。`import_logs` 的 `adj_factor` 只有 **1 次** ok 紀錄（2026-07-07）——就是 STATUS 完成清單裡那句「**已用 2330 實測**」。**crontab 與所有 `vps/scripts/*.sh` 都沒有任何地方呼叫 `compute-adjustments`**。
- [x] **成因**：`db.py:31-33` 以 `ALTER TABLE ... ADD COLUMN adj_factor REAL NOT NULL DEFAULT 1.0` 加欄位，所有列因此停在預設值 1.0；只有 2330 那次測試被更新。另本檔早先記載「週六全市場還原因子+指標全重算已於 2026-07-10 停用，改 VPS 跑後回灌」——**雲端那條停了，VPS 這條從未接上**。
- [x] **消費端確認**（所以影響不是理論的）：`indicators.py:232-235` 把 OHLC 全部乘 `adj_factor` 後才算指標；`performance.py:99-100` 的前瞻報酬用 `open * COALESCE(adj_factor,1.0)`／`close * …`；`compute_branch_stats.py:264` 取還原 candle 算分點勝率；`json_export.py:1333/1338` 把 `adj_factor` 帶進個股 K 線 JSON。
- [x] **具體證據（真實正式資料）**：緯穎 6669 於 **2026-09-02** 由 7,800 → 2,610（**−66.5%**）、寶雅* 5904 於 08-20 由 677 → 75.9（**−88.8%**）、群益臺灣加權正2 00685L 於 07-07 由 306 → 12.23（**−96.0%**）、中美晶 5483 於 08-20 −32.9%，全部 `adj_factor = 1.0`。這些是分割／減資／除權息，不是真實跌幅（股名帶 `*` 即當日除權息；08-20 為除權息集中日）。2026-06-01 以來單日跌幅 ≤ −3% 共 **15,219 筆，其中 adj_factor 未變者 15,219 筆（100%）**。
- [x] 對照 2330 的正確樣貌：`0.97807 → 0.98264 → 0.98682 → 0.99078 → 0.99409 → 0.99733 → 1.0` 逐段累乘——全庫僅此一檔正確。
- ⚠️ **影響鏈**：技術指標（走還原價）→ `tech_score` → 綜合分 `final`（技術佔 20%）→ `compute-performance` 的 `fwd_1d`…`fwd_20d` → **分點 `win_rate`／`avg_ret5`** → `rank_score` 與排行。**注意：2026-09-03 上線的隔日沖重新定義不受影響**（它只用 `net_lots`／`sell_lots`，不碰價格），但同一張表的 `win_rate`／`avg_ret5`／`rank_score` 受影響。
- ⚠️ **修復代價（尚未執行，待人類決定）**：`compute-adjustments --all` 對 2,494 檔各發一次 FinMind 請求，CLI 預設 `--sleep 7.0` → 約 **4.8 小時**；其後需重算指標、重算 `compute-performance`、重算 `compute-branch-stats` 與 scores，再 export。整串是多小時等級的正式 DB 回算，且 VPS 正在跑 490 日分點回補、free 僅 8.0GB。依 `AGENTS.md` 屬「正式 DB 全市場重算」，**必須人工確認**。

## 2026-09-03 題材匯入「永遠不可能成功」的缺陷（線上已壞 3 天，非「尚未執行」）

- [x] **症狀**：個股名稱區的「活躍題材」自 **2026-08-31 起完全不顯示**。正式 DB 的 `themes` 832 筆**全部是 `stale`**，且 `data_date`／`source_updated_at` **0/832 從未被寫入**。文件先前記為「`import-themes` 尚未執行」是錯的——它每週一都有跑（`daily-market.sh:15`，`taipei_date +%u = 1` 時觸發），歷史 7/08 起每週 ok 約 6,869 列。
- [x] **根因**：`importer.py` 的完成條件要求 `empty == 0`。8/31 的紀錄是 `failed=0, empty=230`——**抓取全部成功**，只是 1,062 個分類中有 230 類沒有成分股。讀那些分類名即可確認它們**合理為空**：白酒、煙草、槍枝、麻紡、葡萄酒、咖啡相關、瀝青、氨綸、芳綸、羊毛、絲織品、皮革製品、製帽、樂器、農用機械、運動服、球場……富邦分類法是通用的，台股本來就沒有這些產業。
- [x] **為何從 8/27 起才壞**：`empty == 0` 是 docs/37 C 的 lifecycle 那批（2026-08-27）帶進來的。8/24 那次成功是舊規則下的結果；新規則第一次執行（8/31）就必然失敗，**且只要富邦清單裡永遠有空分類，它就會永遠失敗**。`data_date`／`source_updated_at` 只在成功路徑寫入，所以從未被寫過——這解釋了 0/832。
- [x] **修法（commit `c6f4e22`）**：`empty` 不再阻擋完成。抓得到、解析成功但沒有成分股，是**已觀測到的事實**，不是不完整；真正的來源異常會計入 `failed`（例外），本來就分開計數。新條件為 `limit is None and failed == 0 and not empty_sweep and len(staged) + empty == len(theme_list)`——staged 與 empty 相加必須等於清單長度，故「既未 staged 也未計入」的分類仍會擋下。
- [x] **保留原本 fail-closed 的用意**：新增 `THEME_EMPTY_MAX_SHARE = 0.5` 防「來源整體壞掉、每頁都回傳格式正確卻空白」的情形——那會看起來像一次乾淨的全空。門檻取「超過清單一半」：實測 230/1,062 ≈ **22%**，距 50% 有兩倍以上餘裕，足以容納正常年度波動而仍擋得下全面空白。partial 的 `reason` now 明示是哪條規則觸發（`empty sweep` / `fetch failed` / `limit` / `unobserved categories`）。
- [x] 空分類**不會被標 active**：前置 pass 先把所有非 retired 的 fubon 列設為 `stale`，只有 staged 的會 upsert 成 `active`，所以空分類自然維持 `stale` 且不新增 `stock_themes`。`retired` 的保護未動——已明確 retire 的分類不會被一次完整抓取復活。
- [x] 以 8/31 的實際數字驗算新規則：`limit=None`、`failed=0`、`empty_sweep = 230 > 531` 為 false、`832 + 230 = 1062`（= 清單長度）→ **complete = True**，那一輪在新規則下會成功。
- [x] 驗證：完整 pipeline pytest **381 passed、74 subtests**（基線 376 ＋ 5，含「有空分類但無失敗 → 完成且空者維持 stale」「單一失敗仍走 partial」「全空掃描擋下」「門檻兩側 5/10 與 6/10」「retired 不被復活」）；`git diff --check` 通過。
- ⚠️ **仍待執行**：修好之後**必須手動跑一次 `import-themes`** 才會生效——排程只在週一，否則要等 9/07。將在 14:10 日更結束、DB 鎖釋放後執行。
- 已知並接受：空分類若**先前**有成分股，其舊 `stock_themes` 會保留。刪掉它們等於做出「缺席即退役」的推論，正是本模組要避免的；而該分類維持 `stale`，前端的活躍題材不會顯示它。

## 2026-09-03 庫藏股正式機首次匯入（`import-buybacks`）

- [x] 使用者授權後於 12:21 執行，前置檢查通過（無日更程序、`/tmp/radar-db.lock` 未被持有、free 8.0G、MemAvailable 1,294MB），並以 `flock -n` 取同一把鎖避免與回補寫入交錯。
- [x] 結果：**23 個計畫、23 檔股票**（上櫃 13／上市 10），`board_date` 2026-08-05～2026-08-24，`report_date` 2026-09-03，`import_logs` 記 `mops/buybacks ok rows=23`。這是 `buybacks` 表**首次有資料**（先前 0 列）。
- [x] 雖以 `--days 366` 查詢，回傳的 `board_date` 僅到 8/05——MOPS `t35sc09` 給的是**執行期間仍在進行中**的計畫，不是一年歷史；`execution_pct` 為 None 亦屬正常（尚未執行完畢）。這符合 E1 KB1「只呈現 MOPS 事實」的設計。
- [x] **未手動 export／deploy**：14:10 的 `daily-market.sh` 本來就會 export 並上線，少一次人工發布即少一份風險。

## 2026-09-03 E2 持久化已實作，三項上線前量測全數通過（決策一完成；正式 DB 未動）

- [x] **實作**（commit `b933ab3`）：新表 `branch_pit_stats`，PK `(branch_name, as_of, window_market_days)` 加 `ix_branch_pit_stats_as_of`，**全表無任何 rate 欄位**——每個分子都帶分母與 unknown 計數，`fwd5_sum_pct` 存總和而非平均以保 pooled 精確。新模組 `branch_point_in_time_persist.py` 與 CLI `branch-point-in-time-persist --as-of YYYY-MM-DD [--window-days N]`（預設 60）。`prune.py` 加註此表**刻意永不清理**。兩支唯讀 shadow 工具行為未變。
- [x] **記憶體約束已解**：不呼叫會保留全部 episode 的 `build_branch_point_in_time_report`（單一 as_of 約 913k 個，與 2026-08-25 那次 1.7GB OOM 同形狀），改為 **stock-major 串流**——分點計數器與順序無關，故以 `stock_id, branch_name, date` 排序並 `yield_per` 串流，一支股票的價格切片用完即丟；價格只抓 `window_from` 前 19 個市場日至 `as_of`（任何分位或 fwd5 讀得到的完整範圍）；價格查詢走第二條連線以免擾動串流游標。
- [x] **量測一：記憶體與時間（對 WP-B4 還原出的 4.8GB 正式副本實跑）**：peak working set **63 MB**（行程基線 42MB，計算本身約 +21MB），每個 as_of **31–50 秒**。對照 `compute-branch-stats` 當初的 **1.7GB** OOM，相差約 **27 倍**。Fable 的放行條件是「RSS 須明顯低於 `compute-branch-stats`」→ **通過**。
- [x] **量測二：實際容量**：5 個 as_of 共寫 4,104 列，DB 成長 **155,648 bytes** = **38 bytes／列**；每個 as_of **30 KB**、每 245 交易日 **7.3 MB**。Fable 原估 200KB／as_of、50MB／年，**實際小約 7 倍**。
- [x] **量測三：分點間離散度（決定它能否上 UI）**：as_of 2026-08-28、分母 `buy_pctile_known >= 30` 者 **816 個分點**，`low_buy_count / buy_pctile_known` 的 p10 **0.4941**、p50 **0.5546**、p90 **0.6037**、min 0.3587、max 0.6702，**p90−p10 = 10.95 個百分點**、stdev 4.63pp。Fable 的規則是「差距若不到約 3 個百分點，只能當帳本、不得在 UI 呈現得像它能區分分點」→ **10.95pp 遠高於門檻，該表確有區辨力**，日後可考慮上 UI（本輪不做）。
- [x] **unknown 的質量再次獲證**：該 as_of 共 912,015 個 buy episode，已知分位 690,052、**未知 221,963（24.3%）**；`fwd5` 已成熟 684,768、未成熟 227,247。pooled `low_buy_rate` = **53.8054%**。與先前序列量到的 23% 未知、53.29% 一致。**這就是「只存 rate 會藏起四分之一資料」的實證。**
- [x] 每個 as_of 寫 **821** 列（與序列工具數到的 821 個分點一致），`window_truncated` 皆為 false。模組對非交易日 **fail closed**（實測 2026-08-22 週六被正確拒絕）。
- [x] 驗證：完整 pipeline pytest **372 passed、74 subtests**（基線 363／70 ＋ 9 測試 4 subtests）；`git diff --check` 通過。`create_all` 能在既有 DB 上建表**經測試證實**（在已填資料的 DB 上 drop 該表、呼叫 `init_db()`、斷言它回來），不需 `_migrate_sqlite` 條目。
- [x] **順帶修掉既有效能缺陷**：`_price_observation` 原本**每個 episode 都重算一次 `sorted(market_index)`**，在 913k episode 下是 O(n·m log m)。改為可傳入預先算好的 `market_days`／`row_by_date`（不傳則與原行為逐字相同），並把 `0.40`／`0.60` 具名為 `LOW_BUY_MAX_PCTILE`／`HIGH_SELL_MIN_PCTILE`（值不變）。既有 report 測試未改動且全過。
- [x] **已排入夜間作業（使用者授權後，commit `818f0eb`）**：折進既有的 `safe-branch-stats.sh`（23:30），**不新增 cron、不新增第二個寫入者**。理由：該腳本已完成此步需要的全部守衛——安靜窗、`/tmp/radar-db.lock`、mid-publish flag、磁碟與記憶體門檻，以及 backfill 容器的 pause；獨立排程等於把五道保護重寫一遍並遲早漂移，而且對單一寫入者的 DB 多加一個搶鎖者。位置在 `compute-branch-stats` **成功之後**（帳本讀的是它剛更新的資料）、`compute-scores` 之前。
- [x] **失敗不中止本輪**：沿用 `compute-scores` 既有的 `set +e`／捕捉 rc／`set -e`／`notify_warn` 後繼續的形狀。這張帳本次要於分數／匯出／上線，不得因它擋住當天價格上線。結果寫入 `$STATE_FILE` 的 `pit=`（`ok`／`failed_rc_N`／`skipped_env`），並提供 `SKIP_PIT=1` 環境變數關閉。
- [x] **預設 as_of 取自 `daily_prices` 而非 `branch_trades`**：`compute_branch_stats` 用的是 `MAX(date) FROM branch_trades`，但 `plan_as_of_window` 要求 as_of 必須存在於 `daily_prices`。**若某天分點資料先落地而行情匯入失敗（8/31 的 TPEx 520 即為此類），沿用分點慣例會讓預設值每晚失敗。** 故改用 `daily_prices`，與 `adjustments.py`／`importer.py`／`performance.py` 一致；無可用交易日時 fail closed（CLI 非零退出），不會靜默寫零列。
- [x] 驗證：完整 pipeline pytest **376 passed、74 subtests**（基線 372 ＋ 4）；`bash -n vps/scripts/safe-branch-stats.sh` rc 0（本機 WSL GNU bash 5.2.21，執行前先確認該 bash 確實可用而非只信 rc）；`git diff --check` 通過。
- ⚠️ **歷史回補待執行**：決定先 seed **60 個交易日**（約 40 分鐘）。理由是回補列**不具備當初證成持久化的性質**——`computed_at` 誠實標示它們是「今天對過去的看法」，而非「當天看得到什麼」，價值弱於每日新增的列；60 日正好等於窗口長度，序列即刻可用，日後隨時可加深（重跑同一 as_of 會取代該列，可中斷續跑）。將以 `flock` 取同一把 `/tmp/radar-db.lock`、暫停回補容器、執行後恢復，紀律比照 `safe-branch-stats.sh`，不新增檔案。

## 2026-09-03 隔日沖重新定義已實作並端到端驗證（決策二完成；正式 DB 未動）

- [x] **實作範圍**（commit `0821f04`）：`DAYTRADE_MIN_OBS` 4→**8**、新增 `DAYTRADE_MIN_PAIRS = 20`／`DAYTRADE_PAIR_SHARE = 0.20`；`daytrade_flag` 觀察數不足時回 **`(None, None)`** 而非 `(False, None)`；`branch_stock_stats.is_daytrade_suspect` 未判定寫 **NULL**，並新增 `daytrade_obs`／`daytrade_paybacks` 讓 pair 比率自帶分母；`_BranchAgg` 由 pooled 回吐比率改為 `dt_pairs_determined`／`dt_pairs_flagged` 兩個 pair 計數，`is_daytrade()` 回 `bool | None`；`branch_rankings` 新增 `matured_samples`／`daytrade_pairs_determined`／`daytrade_pairs_flagged`；`AUTO_IN` 抽成具名的 `auto_in_blocked_by_daytrade()`，**只被 `is True` 擋、NULL 不擋**，並在註解明寫不得「修正」成真值測試。
- [x] **匯出端的真 bug 已修**：`json_export.py` 的 detail-set 查詢原為 `AND is_daytrade = 0`，SQL 三值邏輯會**靜默丟掉 NULL 列**；改為 `AND COALESCE(is_daytrade, 0) = 0`（`pocket.py` 既有慣用法）。rankings 主榜／隔日沖切分原為 Python falsy 判斷，路由本來就正確但屬隱含，改為顯式 `!= 1`／`== 1` 以免日後被改壞。全 repo 其餘 `is_daytrade` 分支已逐一檢視。
- [x] **前端**：`Ranking` 的三個新欄位**全為 optional**（程式碼走 Pages 幾分鐘上線、JSON 要等下次 VPS export，舊 payload 必然配新程式碼）；`effectiveSamples()` = `matured_samples ?? samples` 套用於卡片／摘要計數／警告條／篩選**四處**，避免表頭與卡片數字打架；徽章呈現證據而非判決——flagged 顯示「隔日沖 615/1951 檔」、`determined < 20` 顯示「隔日沖未判定」、舊 payload 退回既有「隔日沖」標籤。tooltip 明寫**此比例是下限**。
- [x] **端到端驗證（對 WP-B4 還原出的 4.8GB 正式副本實跑 `compute-branch-stats`，本機，正式 DB 未動）**：additive migration 五個欄位**全部成功加到真實生產形狀的 DB**；831 分點、938,177 筆 stock-stat 列、auto-in/out 皆 0。結果與先前獨立精確重算**逐項吻合**：`is_daytrade=1` **3 個**（凱基-台北 **615/1951 = 0.3152**、群益金鼎-大安 **57/197 = 0.2893**、元大-三峽 **23/80 = 0.2875**）、pair `suspect=1` **2,236**、`daytrade_obs >= 8` **164,569**、`determined >= 20` **799**、最接近落選者 元大-竹科 0.1799／凱基-宜蘭 0.1569／群益金鼎-台北 0.1500。內部一致：2,236 + 162,333 = 164,569；938,177 − 164,569 = **773,608 個未判定 pair**（過去被靜默寫成 False）。
- [x] **`samples != matured_samples` 的分點有 819 個**，證明 §8 稽核指出的混淆確實存在且現已分離；`matured_samples` 無 NULL。`is_daytrade NULL` 為 32 而先前獨立腳本算 28，非分歧——腳本只走到 827 個有合格日的分點（827−799=28），排行表為 831（831−799=32）。
- [x] 驗證：完整 pipeline pytest **363 passed、70 subtests**（基線 350 ＋ 13 個新測試，含 19/20 配對與 0.19/0.20 比例邊界、NULL 不擋 `AUTO_IN`、NULL 列不被 detail-set 丟掉）；`npx tsc --noEmit`、`git diff --check` 通過。
- [x] **`branch_ranking_v2_shadow` 的歷史被刻意凍結**：該報表是本次決策的稽核紀錄，若跟著改門檻就會變成描述新程式而非它當初佐證的歷史。作法是給 `daytrade_flag` 加 opt-in 的 `min_obs` 參數（預設仍為 `DAYTRADE_MIN_OBS`，線上路徑不變），shadow 模組用自己的 `V1_DAYTRADE_MIN_OBS = 4` 並顯式重申歷史上的 `False`。
- 已知但**刻意不動**：`branch_rankings.style` 對未判定分點仍寫 `"swing"`。它與 `is_daytrade_suspect` 同屬「寫了沒人讀」——前端只在型別宣告出現、無任何渲染處，故改它零效益且屬資料契約變更。若日後 `style` 要上 UI，須一併處理未判定狀態。
- [x] **使用者已批准正式上線（2026-09-03 02:3x +08）**。此為 `AGENTS.md`「仍須人工確認：schema migration」所要求的人工放行，非自動 push 的延伸。批准當下 VPS HEAD 為 `d3949f5`（01:10 `data-backfill` 拉的，僅文件），實作尚未進入正式機。預期時序：**14:10** `daily-market.sh` pull 後由 `init_db()` 在正式 `radar.db` 執行五個 `ALTER TABLE ADD COLUMN`；**17:40** `daily-branches.sh` 呼叫 `compute-branch-stats` 使新定義生效並 export／deploy 上線（**23:30** `safe-branch-stats.sh` 亦會重算）。使用者可見的變化：3 個分點被標記並移入隔日沖清單、32 個顯示「未判定」。回滾路徑為 `git revert` ＋ 下一輪 cron；已加的欄位為 additive，留著無害，且舊快照的 NULL 即版本標記。**本輪未手動在 VPS 執行任何 import／export／deploy／migration，未改 cron。**
- ⚠️ **尚未做**：決策一的 `branch_pit_stats` 計數帳與串流持久化模組（與本次同樣會改 `schema.py`，故分開進行）。

## 2026-09-02 Fable 5.1 決策：E2 持久化粒度與隔日沖訊號重新定義（決策紀錄）

> 依 `AGENTS.md`「單一模型不得獨自拍板 schema 大改」，使用者將這兩題委由 Fable 5.1 定奪。以下為決策內容；**程式尚未實作，正式 DB 未動**。

- [x] **Fable 另外查出、我方已獨立驗證的三個事實**：①`branch_stock_stats.is_daytrade_suspect` **寫了但沒有任何消費者**——全 repo 只有 schema 欄位定義、`compute_branch_stats.py:367` 的寫入與本輪文件，沒有 export 或 UI 讀它，所以真正會觸發的 pair 層級訊號目前完全不可見；②分點層級的布林值 gate 了三處（`json_export._export_branches` 的主榜／隔日沖切分、detail set 的 `AND is_daytrade = 0`、`compute_branch_stats.py:381` 的 `AUTO_IN`），而三者今天都是 no-op；③E2 report builder 把每個 episode 保留在記憶體（單一 as_of 約 913k 個），與 **2026-08-25 OOM** 同一種形狀——該 OOM 屬實，見 `vps/README.md:219`、`compute_branch_stats.py:199` 註解與 `crontab.example:45`「避免 1.7G RAM OOM」。故任何持久化路徑**不得**照原樣呼叫 `build_branch_point_in_time_report`，必須在 pair 迴圈內串流累加。
- [x] **決策一：E2 只在分點層級持久化，且只存整數計數，永不存 rate。** 新增 additive table `branch_pit_stats`，PK 為 `(branch_name, as_of, window_market_days)`（把窗口納入 PK，日後換窗口不必重寫）。欄位含 `window_from`／`definitions_version`（`'e2-v1'`）／`computed_at`／`observed_trade_rows`／`stock_count`／`buy_episodes`／`sell_episodes`／`buy_pctile_known`／`buy_pctile_unknown`／`sell_pctile_known`／`sell_pctile_unknown`／`low_buy_count`／`high_sell_count`／`fwd5_matured`／`fwd5_unknown`／`fwd5_positive_count`／`fwd5_sum_pct`。**每個分子都有對應分母與 unknown 計數，所有比率一律讀取時再除**；存 `fwd5_sum_pct` 而非平均，pooled 平均才精確。約 821 列／as_of、約 200KB／as_of、約 50MB／年，對 5.5GB 的 DB 是雜訊。**保留期限：永久不 prune。**
- [x] **不做分點×個股表**（~140GB，算術上排除）、**不做市場層級表**（它就是分點列的欄位加總，讀取時 pool 即可）。持久化而非每次重跑的理由是：工具讀的是 `branch_trades WHERE date <= as_of`，而 490 日回補**正在改變過去日期的查詢結果**——帶 `computed_at` 的列是「我們在第 X 天看得到什麼」的唯一紀錄，半年後重算是另一個觀測，不是同一個。
- [x] **決策二：分點層級隔日沖旗標保留，但改以「已判定 pair 中被標記的比例」定義，退休 pooled 回吐比率。** pooled 比率結構上已死——涵蓋約 1,128 檔股票的分點不可能在總體上達到 60% 次日回吐，831/831 一致即為證明。pair 層級 `DAYTRADE_MIN_OBS` 改 **8**，觀察數不足時 `daytrade_flag` 回 `(None, None)`、`is_daytrade_suspect` 寫 **NULL 而非 False**；`branch_stock_stats` 增 `daytrade_obs`／`daytrade_paybacks` 讓 pair 比率自帶分母。分點層級以 `daytrade_pairs_determined`／`daytrade_pairs_flagged` 兩個計數表達，**分母必須是已判定 pair 而非全部 pair**——平均每 pair 僅 4.97 個事件，把未判定當成「非隔日沖」正是 E2 fixture 證明過的分母錯誤。`AUTO_IN` 只被 `is_daytrade = 1` 擋，NULL 不擋（否則幾乎沒有新分點能自動入選）。
- [x] **成熟度級距兩個層級都不採用**：分點層級惰性（漂移 0、只差 1 個分點）；pair 層級不排名、不評分、不顯示，加級距只是裝飾且依構造會有約九成落在 insufficient。改為在 `branch_rankings` 增 `matured_samples`，這才是 §8 稽核指出的真正缺陷（`samples` 混合成熟與未成熟），前端 `MIN_SAMPLES` 徽章改讀 `matured_samples ?? samples`——即 shadow 的讀法 (a)，榜單集合不變、只多一個誠實標記。
- [x] **校準已定案（Fable 第二輪，依實測重訂）**：`DAYTRADE_PAIR_SHARE = **0.20**`、`DAYTRADE_MIN_PAIRS = **20**`、`DAYTRADE_MIN_OBS = **8**`。規則：`determined < 20` → `is_daytrade = NULL`；`determined >= 20 且 flagged/determined >= 0.20` → `1`；其餘 `0`。初擬的 0.5 實測會標記 **0 個**分點（見下節），等同重現它要修的缺陷，故重訂。
- [x] **關鍵重新詮釋：0.33 是「可觀測性上限」，不是行為上限。** 一個 pair 只有在該分點當天擠進該股**前 15 大賣方**時，次日翻單才被看見。真正的隔日沖分點每筆都翻，但截切把大多數翻單藏起來了。凱基-台北是台股最公認的隔日沖分點，兩種分母下都只到 0.31–0.32——那不是它的行為，是資料來源的天花板。因此**分點層級的 share 活在 0～約 0.33 的尺度上**，常數必須按該尺度訂，且徽章語意必須寫成「**在每日前 15 大可見範圍內翻單的比例**」，**絕不可說成「多數時候翻單」**。
- [x] **兩個常數各買到什麼**：`0.20` 高於 p99（0.12）且約為 p90（0.025）的 8 倍，與主體差一個數量級而非毫釐；約為觀測上限的三分之二，是在受截切限制的尺度上最誠實的「多數」類比。選 0.20 而非 0.15 是刻意保守——布林值只驅動榜單切分與 `AUTO_IN` 阻擋，而 share 與其分母**無論如何都會匯出並顯示在每張卡上**，所以保守不會讓資訊消失（元大-竹科 80/408 仍顯示為「隔日沖 80/408 檔」讓使用者自行判斷）；反之偽陽性會把分點逐出主榜並擋掉自動追蹤。`20` 則是讓常數不被機率淹沒的最小分母：pair 層級基準率約 1.5%，`min_pairs=10` 時只需 2 個 flagged 就跨過 0.20，`P(>=2/10)≈0.94%`、乘約 800 個分點約 **7.5 個偽陽性**（多於真陽性）；`min_pairs=20` 需 4 個，`P(>=4/20)≈2.4e-4`、全榜期望約 **0.2 個**。**此機率推算已由主協調獨立驗算，數字正確。**
- ⚠️ **文件語意要求（Fable 指定，實作時必須同步寫入 `docs/13` §8）**：徽章意義為「**可判定的分點×個股 pair 中、在每日前 15 大可見範圍內次日翻單的比例**」；須載明今日資料的可觀測上限約 0.33，以及 0.20／20 是由 **2026-08-28 的分布**推導而來、不是行為定義。同一段落須**撤回**先前「min-obs 8 是 no-op」的說法，並附上 5,118 → 2,100 的數字。
- [x] **上線前驗收已通過（2026-09-03 精確重算，102 秒，唯讀）**：以真實規則重算——observations 為合併前的合格買超日（`net > 0` 且 `pct >= 1.0`）、次一交易日同分點賣出張（無紀錄以 0 計）、`determined` 為 `observations >= 8`、`flagged` 為回吐比率 `>= 0.6`。結果：min_obs=4 有 determined **366,098**／flagged **5,120**（base rate 1.40%）；min_obs=8 有 determined **164,569**／flagged **2,236**（**1.36%**）。分點層級 `determined >= 20` 者 **799** 個、落入 NULL 者 **28** 個；share 分布 p50 **0.0000**、p90 0.0213、p99 0.1221、max **0.3152**。
- [x] **`share >= 0.20` 標記出恰好 3 個分點**：凱基-台北 **615/1951 = 0.3152**、群益金鼎-大安 **57/197 = 0.2893**、元大-三峽 **23/80 = 0.2875**。Fable 的驗收規則為「flagged 落在 2–10 且含凱基-台北」→ **通過，常數照案實作**。最接近的落選者為元大-竹科 84/467 = 0.1799、凱基-宜蘭 8/51 = 0.1569、群益金鼎-台北 9/60 = 0.1500。
- [x] **兩項交叉驗證**：①min_obs=4 的 flagged 精確值 **5,120**，與直接讀既有 `branch_stock_stats` 得到的 5,118 幾乎相同，證明重算邏輯與正式管線一致；②determined pairs 164,569 **大於**先前代理指標的 139,076，方向與已標註的「`events_count >= 8` 比 `observations >= 8` 更嚴格」一致。Fable 假設的 1.5% base rate 實測為 **1.36%**，其偽陽性推算成立。
- 歷史備註（原文保留）：Fable 要求以真實規則精確重算後才實作（observations = 合併前的合格買超日、determined 為 `observations >= 8`、flagged 為回吐比率 `>= 0.6`），**驗收規則：flagged 分點數落在 2–10 之間且含凱基-台北才可照案實作**；若不符**不得自行調整常數**，須帶數字回送 Fable。放棄的部分：0.10–0.20 區間（代理指標下約 9 個，含元大-竹科 0.196、群益金鼎-台北 0.19）不會被標記，它們仍留在主榜並顯示自身 share。

## 2026-09-02 隔日沖 pair-share 校準實測：0.5 門檻會標記 0 個分點

- [x] 對還原副本的 `branch_stock_stats` 依分點分組（831 個分點）。**分母＝全部 pair**（既有旗標，min-obs 4），取 pair 數 ≥10 的 829 個分點：share p50 **0.0018**、p90 0.0080、p99 0.0496、**max 0.3117**；`>=0.5` **0 個**、`>=0.3` 1 個、`>=0.2` 1 個、`>=0.1` 3 個、`>=0.05` 8 個。前五名：凱基-台北 615/1973 = 0.3117、群益金鼎-大安 151/1046 = 0.1444、新加坡商瑞銀 245/1862 = 0.1316、元大證券 174/1934 = 0.0900、元大-竹科 136/1623 = 0.0838。
- [x] **分母＝`events_count >= 8` 的 pair**（min-obs 8 的代理指標），808 個分點：p50 **0.0000**、p90 0.0250、p99 0.1223、**max 0.3433**；`>=0.5` **0 個**、`>=0.3` 3 個、`>=0.2` 3 個、`>=0.1` 12 個、`>=0.05` 32 個。前三名：元大-三峽 23/67 = 0.3433、凱基-台北 614/1947 = 0.3154、群益金鼎-大安 48/160 = 0.3000。
- [x] **pair 層級 min-obs 由 4 提到 8 不是 no-op**：pair 池由 937,856 縮到 **139,076（14.83%）**，flagged 由 5,118 降到 **2,100（-59%）**。**先前「改 8 零代價」的結論只在分點層級成立**（該層規則本來就是死的），不得引用為 pair 層級的證據；此更正由 Fable 指出，我方接受。
- ⚠️ **代理指標的兩個保守偏誤**：①`events_count` 是合併後的事件數，而隔日沖觀察數是合併前的合格日，故 `observations >= events`，用 `events_count >= 8` 篩比真正的 `observations >= 8` **更嚴格**，真實已判定池大於 139,076；②既有 flag 是在 min-obs 4 下算的，分子中可能含在 min-obs 8 下未判定的 pair。要精確數字需完整重算（約 20 分鐘），已告知 Fable 可依需要執行。

## 2026-09-02 E2 穩定度序列真實資料結果：全粒度持久化在硬體上不可行

> 對 WP-B4 還原出的 2026-08-28 正式副本執行 `branch-point-in-time-series --as-of-from 2026-07-01 --as-of-to 2026-08-28 --step 5 --window-days 60`（本機、唯讀、未碰正式 DB）。

- [x] **輸出量級直接否決了全粒度持久化**：9 個 as_of 點涵蓋 821 個分點與 **945,131 個分點×個股實體**，產生 **5.07 GB** JSON（1 個 as_of 無資料）。若做歷史回算約 250 個 as_of，同粒度將達 **~140 GB** 級。VPS 僅 29G 總量／8.0G free，且 `docs/12` 零成本原則排除需綁卡的代管儲存。**在分點×個股粒度持久化 point-in-time 結果不可行，這不是門檻問題而是量級問題。**
- [x] **市場層級的 rate 穩定到近乎常數**：`low_buy_rate` 在 as_of 2026-08-20 為 **53.283864%**、2026-08-27 為 **53.292160%**（相差 0.008 個百分點）；`high_sell_rate` 為 34.392680% → 34.075746%。穩定是好事，但也代表**市場層級彙總資訊量極低**——真正的變異在小分母的分點×個股。
- [x] **unknown 的質量在真實規模上很大，證實「只存 rate 不存分母不可還原」**：某個 as_of 的 913,078 個 buy episode 中，`fwd5` 已成熟 686,722、**未成熟 226,356（25%）**；缺已知 20 日分位者 **212,140（23%）**。亦即任何裸 rate 都藏起了約四分之一的資料。同一 `low_buy_rate` 在 fixture 上各日平均 75% vs pooled 66.7%，差距純由分母加權而來。
- [x] 其他實測：某 as_of 的 `observed_branch_stock_rows` 780,485、`observed_branch_trade_rows` 3,295,177、`universe_branch_count` 831~832、`window_truncated` 為 false、`trade_rows_missing_pct` 為 0。
- ⚠️ 持久化的粒度與欄位設計、以及分點層級隔日沖訊號的存廢，已依使用者指示交由 **Fable 5.1** 決策（`AGENTS.md` 禁止單一模型自行拍板 schema）。結論落定前不得實作。

## 2026-09-02 排行 V2 真實資料結果：兩個「待人工確認」的問題被證明是空的，但挖出一個真的

> 對 WP-B4 還原出的 2026-08-28 正式副本執行 `branch-ranking-v2-shadow`（本機、唯讀、未碰正式 DB）。fixture 給不出量級，真實資料給出了，而結論與 `docs/13` §8 的預期相反。

- [x] **成熟度門檻在分點層級是惰性的**：831 個分點中，`matured_samples` 中位數 **3,708**（min 5、p10 1,574、p90 7,975、max 132,015、平均 5,514）。落在 `<10` 的只有 **1** 個、`<30` 只有 **5** 個。`docs/13` §8 提的 10／30 門檻比實際中位數低了三個數量級，篩不掉任何東西。
- [x] **三種讀法幾乎無差異，名次漂移全為 0**：(a) 評分並標記 → 831 列／831 評分；(b) 列榜但無分數 → 831 列／830 評分；(c) 不列入 → 830 列（刷掉 1 個）。三者 `rank_drift mean_abs` 皆為 **0**，退榜／進榜除那 1 個外皆為 0。**這個歧義在現行資料規模下實際影響 1 個分點。**
- [x] **V1 的 `samples` 混淆真實存在但比例極小**：`events_count - matured_samples` 中位數 62、p90 139、max 2,044、平均 91.17，819／831 個分點有落差；但相對於中位 3,708 的分母約僅 **1.7%**。全體 total_events 4,657,863、matured 4,582,098、immature 75,765。
- [x] **隔日沖 4 → 8 完全沒有差別**：831 個分點在兩種最低觀察數下**全部判定得出**，`unknown_min8 = 0`、`verdict_differs = 0`。兩種門檻下被標記為隔日沖的都是 **0** 個。
- [x] **與正式快照交叉核對，證明工具無誤**：還原副本的 `branch_rankings` 2026-08-28 快照 `is_daytrade=1` 也是 **0**、`is_daytrade=0` 為 831，與 shadow 完全一致。往前查所有快照，8/25 起為 0，8/21 及更早也僅 **1**（共 830）。
- ⚠️ **真正的問題（新發現，不在原本三題之內）**：`branch_stock_stats.is_daytrade_suspect` 在**分點×個股**層級有 **5,118 / 937,856（0.55%）** 為真，該層級 `events_count` 平均僅 **4.97**（min 1、max 150）。也就是說 **`docs/13` §8 的 10／30 門檻與隔日沖最低觀察數，在分點×個股層級才有意義；套在分點層級會被稀釋掉**——一個分點平均涵蓋約 1,128 檔股票（937,856 ÷ 831），聚合後任何門檻都失效。同理前端 `MIN_SAMPLES = 10` 的「樣本不足」徽章，在正式資料上只對 1 個分點生效（`branch_rankings.samples` min = 7）。
- [x] **據此已可定案的兩題**（有數據支持，非取捨）：①「成熟樣本 <10」三種讀法皆可，**建議 (a)**——保留與 V1 完全相同的榜單集合、只多一個誠實標記，代價為零；②隔日沖最低觀察數 **改為 8**，與 `docs/13` 原始規劃一致且實測零影響，消除文件與程式長期不一致。**兩者都不改分數公式、不改 `final`、不改權重。**
- ⚠️ **仍待決定**：分點層級的隔日沖訊號是否還該存在（實測近乎恆為 false，而真正有訊號的是分點×個股層級），以及成熟度門檻是否應改在分點×個股層級重新校準。這是產品語意問題，不是可由實測直接推出的結論。

## 2026-09-02 排行 V2 與 E2 穩定度：兩支唯讀 shadow 工具（決策證據，未改 schema、未寫 DB）

> 依 `AGENTS.md` 高風險流程，schema 大改與正式回算不得由單一模型拍板。這兩支工具的目的是**先把人類要做的選擇量化**，不是先實作 V2。兩者都不呼叫 `init_db()`、不建表、不 migration、不寫任何欄位，皆以 `mode=ro` 讀既存 DB，`--out` 沿用既有守衛拒絕寫到 DB 或其 `-wal/-shm/-journal`（含 symlink／hardlink alias）。

- [x] **`branch-ranking-v2-shadow --as-of --out`**：一次輸出 V1 與 V2 的對照。`docs/13` §8 的「成熟樣本 <10 不評分」語意含糊，本報表**不替人類選**，而是同時量化三種讀法——(a) 仍評分並保留名次、只標記樣本不足；(b) 仍列榜但 score／rank 皆 null；(c) 直接不列入。每種讀法各報 listed／scored／進榜／退榜數與存活者的名次漂移統計。隔日沖同時給 V1 的 4 筆與 `docs/13` 原規劃的 8 筆最低觀察數：**V1 在觀察數不足時回 `False`（未判定卻預設為否），V2 明確記為 `unknown` 且 verdict 為 null**。回吐比率一律由既有 `daytrade_flag` 產生，不重新推導公式；名次以「分數降冪、同分依分點名稱升冪」決定，V1／V2 兩側用同一規則，確保漂移來自成熟度規則而非決勝方式差異。
- [x] **`branch-point-in-time-series --as-of-from --as-of-to --step --window-days --out`**：把既有 E2 單日 shadow 沿多個 as_of 交易日推進並彙總，回答「這個訊號跨時間穩不穩，還是只是我們剛好挑到那一天」。`--window-days` 數的是**市場交易日**而非日曆日（日曆窗口會在假期靜默縮短、使各 as_of 不可比）；歷史不足的窗口逐一標記、不補值。彙總**由 `episode_samples` 重算而非平均各日 rate**，並同時輸出 `pooled_numerator`／`pooled_denominator`／`pooled_rate` 與各日分母序列。單一觀察的 `stdev` 為 null 而非 0.0。缺席的 as_of 明列於 `absent_as_of_dates`，不前向填補；輸出另註明連續窗口會重複觀察同一批 episode，是重疊視角而非獨立樣本。`buy_sell_pairing: false`、`trade_profit_attribution: false` 明寫在 metadata，沒有任何欄位被命名或計算為勝率。
- [x] **對 schema 決策最有用的一項觀察**：fixture 中同一個 `low_buy_rate`，各日平均為 **75%** 而 pooled 為 **66.7%**，差距純粹來自分母加權（分母序列 2,2,1,1）。這具體證明**只存一個 rate、不存分母的 schema 是不可還原的**。另 `fwd5_positive_rate` 在分母恆為 1 個成熟 episode 時於 0↔100 之間擺盪、`high_sell_rate` 對稀疏分點多數 as_of 未定義——存成裸 nullable float 之後將無法與「真的是 0」區分。相對地，出席與否、episode 數軌跡、known／unknown 與 evidence／insufficient 計數在每個出席日都有定義且可重現。
- [x] 驗證：完整 pipeline pytest **350 passed、70 subtests**（基線 314 ＋ 兩工具共 36 個新測試），`git diff --check` 通過，`schema.py` 未被改動。排行 V2 的作者 agent 在跑完整套件前因 session 額度中斷，其程式碼與測試由主協調接手審核（唯讀 engine、無 schema import、無寫入路徑）後才合併，非逕行採信。
- ⚠️ **fixture 能證明什麼、不能證明什麼**：兩者的測試都是合成且刻意極端的（少量分點／股票、收盤在 100／200 間交替使分位數可精確驗算）。它們能證明彙總確實會把不穩定、稀疏與缺口呈現出來，**不能**給出真實世界的量級——真實分點一年下來 `low_buy_rate` 波動多大、生產規模下每個窗口的成熟 episode 分母是 3 還是 300、真實分點多常掉出前 15 大截切，都要對非正式環境的真實 DB 副本跑過才知道。`--window-days` 與 `--step` 的取值本身也是 fixture 無法代為判斷的。
- ⚠️ **待人類決定**：①「成熟樣本 <10」採 (a)／(b)／(c) 哪一種；②隔日沖最低觀察數維持 4 或改回 `docs/13` 原規劃的 8；③是否把 E2 結果落成 schema，以及若要落，是否連分母一併存（依上述觀察，只存 rate 不可還原）。三項都尚未實作，也不得由 agent 代選。

## 2026-09-02 DB 瘦身可行性：已到期權證資料不是空間所在（唯讀實測，結論為「不要做」）

> 起因是「權證會過期，那些資料是否可移除以瘦身」。方向合理，但實測顯示可回收量與需求差兩個數量級，**不建議實作按到期日的清理**。留此紀錄以免後續再探同一條路。

- [x] **年齡型 prune 一直有在跑**：`disk-cleanup.sh` 每日 07:40 呼叫 `radar prune`（`prune.py`：`indicators_daily` 400 日、`warrant_daily` 150 日、`import_logs` 180 日，皆以 `daily_prices` 的第 N 個最近交易日為界）。log 顯示穩定刪除約 **45,000 列／日** 的 `warrant_daily`。所以權證日行情早已被壓在 150 交易日內，`warrant_daily` 5,765,963 列依 `docs/29` 的 ~88 bytes／列估約 **0.5GB**。改成按到期日刪，最多再省約 0.2GB。
- [x] **權證分點列的窗口外殘留幾乎為零**：`branch_trades_raw` 總計 **22,920,549** 列，其中權證列（`LENGTH(stock_id)=6`）**1,482,024**（6.5%），而**早於 120 日匯出窗口界（2026-03-11）的權證列只有 10,529 列**（約 1.6MB）。原因是全市場權證分點是近期才開始每日收集，尚未累積。日期範圍 2024-07-01～2026-09-02。
- [x] **沒有廢表、沒有可回收頁面**：`sqlite_master` 只有 22 個實表加 1 個 `branch_trades` view（`docs/29` 的 `branch_trades`→`branch_trades_old` migration 已完成且未留殘表）；`PRAGMA freelist_count = 0`、`auto_vacuum = 0`，代表 **`VACUUM` 一個位元組也回收不到**。`page_count 1,352,813 × 4,096` 與檔案大小相符。
- [x] **質量在刻意保留的資產上**：窗口外的**股票**分點列有 **14,779,714**（64%，依實測 156 bytes／列約 2.3GB），而那正是 `backfill-branches --days 490` 正在建立的兩年歷史。刪它等於廢掉回補本身的目的。
- ⚠️ **結論**：可回收總量約 0.2GB 級，對 Phase 2 所需的 8.4GB 是雜訊。**WP-B6 Phase 2 的空間只能來自更大的磁碟或更短的窗口，沒有靠瘦身解決的路徑。** 不實作按到期日的權證清理。

## 2026-09-02 WP-B6／M4 容量分析：20GB gate 在現有硬體上無法達成（唯讀）

- [x] **實測佔用**：磁碟 `29G` 總量、已用 `19G`、free `8.0G`（71%）。`radar.db` 5,523,030,016 bytes ＋ WAL 97,903,592 bytes；repo 內 `data/` 5.3G、`web/` 894M、`cloudflare-data-worker/` 201M；另有 `/swapfile2` 2.0G；Docker images 3.023GB。
- [x] **清理救不了**：`docker system df` 顯示可回收僅 images 175.2MB ＋ local volumes 28.24MB ＋ build cache 691B，合計不到 210MB。家目錄除 repo 外最大者是 1.2M 的 log。
- [x] **gate 數學上不可達**：`docs/30` §5 要求開跑前 free ≥20GB、跑完仍 ≥10GB。29G 的磁碟要 free 20G，等於全機用量須 ≤9G，而 `radar.db` 單檔就 5.5G，再加 OS、Docker images 3.0G 與 swap 2.0G 已然超過。**這不是「等使用者按下去」的問題，是現有硬體無法滿足該門檻。**
- [x] **關鍵前提**：`docs/30` §5 自己寫明舊估計「+0.7–1.0GB」已作廢，**必須先跑 1 日與 5 日 PoC** 量測每千次請求的 DB＋WAL＋索引成長，再據以推估 120 日總量。換言之 **20GB 是等待該量測期間的保守佔位值，不是實測需求**。目前沒有任何實測數字可以支持或推翻它。
- [x] **Phase 1 其實正在跑**：`docs/30` 的 WP-M4 Phase 1 目標是 `backfill-branches --top 2500 --days 490`，而 VPS 上此刻執行中的正是 `backfill-branches --top 0 --days 490`（`--top 0` = 當日全部有量普通股，範圍不小於 2500 的安全上限）。被磁碟擋住的只有 Phase 2（權證全市場 120 日，`docs/30` §5 估 ~1.44M 請求、約 20 天連續執行——**估計值，非實測**）。
### 實測數字（2026-09-02，使用者授權後取得，全程唯讀）

- [x] **每日目標數是實測值，不再是估計**：以 `daily-warrant-branches-poc.sh` 的 `WARRANT_BRANCH_DRY_RUN=1` 唯讀模式（該模式明確不暫停回補、不取鎖、不寫入、不發布）得到 2026-09-02 全市場 **19,109 檔（TWSE 15,513＋TPEx 3,596，cap 25,000）**。`docs/30` §5 原估 ~12,000／日，**低估約 37%**。
- [x] **執行時間隨之上修**：以腳本的 `--sleep 1.0` 計，一日約 19,109 秒 ≈ **5.3 小時**（腳本 `MAX_MINUTES` 480、硬逾時 30,600 秒，塞得下但不寬裕）；120 日約 **2.29M 請求 ≈ 26.5 天連續執行**，較 `docs/30` §5 估的 ~20 天更久。以上未計每次請求本身的延遲，故仍偏樂觀。
- [x] **bytes/row 以既有基準回推，未做任何寫入**：`branch_trades_raw` 由 8/31 13:05 的 21,522,284 列增至 22,801,922 列（**+1,279,638**），同期 DB 由 5,324,414,976 增至 5,524,545,536 bytes（**+200,130,560**），得 **≈156 bytes／列（含索引）**。這是**上界**——期間 `daily_prices`（+7,175）、`warrant_daily`（+36,822）等表的成長也被一併算進分子。`page_count 1,348,768 × page_size 4,096 = 5,524,553,728` 與檔案大小相符，數據自洽。
- [x] **120 日容量推估：約 8.4 GB，裝不下。** 以 8/31 22:00 那輪 2,619 目標→61,687 列的實測比率（≈23.6 列／目標）推，19,109 目標／日 ≈ 45.1 萬列／日，120 日 ≈ 5,410 萬列 × 156 bytes ≈ **8.4 GB**，而現有 free 僅 **8.0 GB**。即使全市場平均列數只有該比率的一半（全市場含大量冷門權證，確有可能），仍需 ~4.2 GB、跑完僅剩約 3.8 GB，遠低於 gate 要求的「完成後 ≥10 GB」。**23.6 列／目標取自高成交額池，對全市場而言偏高，此為明確標示的不確定來源。**
- [x] **結論：不是門檻訂太嚴，是這個工作量在 29G 磁碟上真的放不下。** 可行的形狀是縮短窗口：以同一保守速率估，30 日約 2.1 GB（跑完約剩 5.9 GB、約 6.6 天連續執行）、60 日約 4.2 GB。若要維持 120 日，就必須擴充磁碟。
- ⚠️ **未執行、待人類決定**：①縮短窗口跑（例如先 30 日，第一日結束即可用實測列數修正推估，state-file 支援續跑）；②擴充 VPS 磁碟後再跑 120 日；③不做 Phase 2。寫入型 PoC 未執行——唯讀量測已足以判定 120 日不可行，再花 5.3 小時與數 GB 去精修一個已經指向「放不下」的數字並不划算；若選①，第一日的實際寫入本身就是最好的 PoC。

## 2026-09-02 週備份鏈唯讀稽核：先前「備份狀態不明」的判斷是錯的

- [x] **備份正常運作，有證據。** Drive `gdrive:trever-radar-backup/` 現有 6 份：`radar-20260829.db.gz`（1,162,065,971 bytes，2026-08-29 05:12）、`0824`（12:59，臨時跑）、`0822`（05:10）、`0815`（05:09）、`0814`（17:47，臨時跑）、`0725`（05:18）。最近一次週六排程備份為 **8/29 成功**。
- [x] **該次 `integrity_check` 必然回 `ok`。** `weekly-backup.sh:18-22` 在 `CHECK != ok` 時 `notify` 後 `exit 1`，早於 gzip 與上傳；快照存在本身即證明檢查通過。不需另跑 `integrity_check` 去確認過去那一輪。
- [x] **先前三個「症狀」全部是誤判**：①「主機未見 `.db.gz`」是 `weekly-backup.sh:29` 上傳後 `rm -f "$SNAP"` 的正常行為；②「log 無備份痕跡」是正常路徑幾乎不輸出（`db_sql >/dev/null`、rclone 靜默、只有 `notify_ok`）；③「8/22 Drive quota 403」不是持續阻斷——8/22 當天 05:10 的快照確實存在，且 Drive 為 **5 TiB 總量、已用 13.376 GiB、free 4.987 TiB**（Trashed 2.558 GiB），容量從來不是瓶頸，該 403 應發生在上傳成功之後的 retention 刪檔階段。
- [x] **最新快照已做不落地的串流驗證**：`rclone cat | gunzip -c` 全程串流、不寫磁碟，`gunzip` exit 0（gzip CRC 完好、未截斷），解開後前 16 bytes 為 `SQLite format 3\0`，解壓總長 **4,819,320,832 bytes（約 4.49 GiB）**，與 8/29 當時規模相符。耗時 37 秒，前後磁碟同為 8.0G free。
- [x] retention 現況與 `weekly-backup.sh:32-35` 規則一致（保留最近 4 份，更舊者每月留最新一份）：0829／0824／0822／0815 為最近四份，0814（202608）與 0725（202607）各為其月份代表。
- [x] **WP-B4 還原演練已完成（2026-09-02，專案首次）**，在本機進行，對正式機零影響（未動 VPS 磁碟、未取鎖、未碰正式 DB）。自 Drive 取回 `radar-20260829.db.gz` **1,162,065,971 bytes**（與 Drive 列出的大小逐位元相符），解開得 **4,819,320,832 bytes**（與先前串流量測完全一致）。
- [x] **還原結果可用，不只是檔案完好**：`PRAGMA quick_check` = **ok**（12.4 秒）、完整 `PRAGMA integrity_check` = **ok**（231.8 秒）、`foreign_key_check` **0 違規**、`page_count × page_size` 精確等於檔案大小、`journal_mode=wal`。內容抽查：22 表、`stocks` 2,491、`daily_prices` 10,205,766、`branch_trades_raw` 18,380,545、`warrant_daily` 5,729,141、`daily_scores` 19,341、`tracked_branches` 47，且 `daily_prices`／`branch_trades_raw`／`daily_scores`／`branch_rankings` 的最新日期一致為 **2026-08-28**（快照 8/29 05:12 取，涵蓋至 8/28，時序自洽）。
- [x] **與已知正式狀態交叉核對通過**：`daily_prices`、`warrant_daily`、`daily_scores` 的列數與本檔 8/31 12:16 稽核紀錄完全相同；`branch_trades_raw` 較少（18,380,545 vs 21,522,284）正是因為分點回補持續在寫入。**至此備份鏈為端到端已驗證，不再只是「快照存在」。**
- [x] 這份還原副本另作為兩支 shadow 工具的真實資料基準（fixture 給不出量級，見上節），跑完即可刪除；它不是第二份正式資料，不得回寫 VPS。

## 2026-09-02 VPS 金鑰改走 docker --env-file（使用者授權後執行）

- [x] **問題**：`vps/scripts/lib.sh` 的 `radar()`／`radar_timeout()` 與 `bf-supervisor.sh` 的 `start_job()` 以 `-e RADAR_FINMIND_TOKEN=…`、`-e FUGLE_API_KEY=…` 傳金鑰，完整值因此進入 argv。實測該主機 `/proc` **未掛 `hidepid`**，任何本機 uid 都能由 `/proc/<pid>/cmdline` 讀走兩把金鑰。`daily-margin.sh`、`weekly-backup.sh` 的 `docker run` 不含金鑰，未動；`crontab.example` 的 radar-worker 早已是 `--env-file`。
- [x] **修法**：改由 `radar_secret_env_new` 現產 `mktemp` 0600 檔（明確再 `chmod 600`），以 `--env-file` 傳入，呼叫一回來即刪，另掛 EXIT trap 兜底 `set -e` 中止／被 kill 的殘檔。值來源仍是既有 `vps/.env`／`pipeline/intraday/.env`，**不需在 VPS 預先建任何檔**，所以沒有「腳本先更新、檔案還沒建」的順序風險。容器內拿到的仍是同樣兩個環境變數，而 `/proc/<pid>/environ` 只有 owner 可讀。
- [x] **契約細節**：`--env-file` 的值是第一個 `=` 之後的整行原文，不去引號、不去空白，所以一律不加引號；變數為空時仍寫 `KEY=`（省略整行會變成改由 host 環境查找，語意不同）；值含換行則 fail closed（`notify` + `exit 1`），不默默截斷金鑰。既有 trap 以 `trap -p` 讀出後串接而非覆蓋；子 shell 內不串接，避免提早跑掉父層的 flag 清理／unpause。
- [x] **離開碼語意逐字保留**：`( exit "$rc" )` 後再 `return "$rc"`——`set -e` 生效時就地中止（維持函式內失敗不觸發 ERR trap 的舊行為，否則每次失敗會多噴一則 High 通知），`set -e` 被抑制時（`if radar …`／`radar || …`）忠實回傳 docker 離開碼，`daily-insti.sh` 的 exit 75 分支靠這個碼。
- [x] **驗證（VPS 上以 `/tmp/secfix` 的複本執行，掛零 volume、只跑 `python -c`，未碰 DB／lock／cron）**：兩把金鑰的 host shell 值與容器內值長度與 sha256 前綴完全一致（197 bytes／`75b2d82a645e7c5d`；100 bytes／`5208eb09c98a5a08`），`-d` 分離容器亦同，證明刪檔時機正確。env 檔為 `600 huang:huang`、無引號無填充。實測新 argv 為 `docker run --rm --env-file /tmp/radar-env.XXXX …`，金鑰命中數 0。合成值另證引號不會被剝除、空值等價於 `-e KEY=`。`bash -n`（VPS bash 5.1.8）與 `git diff --check` 通過。VPS checkout 僅四個既有未追蹤檔、HEAD 未動、無殘留 `/tmp/radar-env.*`。
- [x] **正式管線首次執行已驗證**：17:40 那輪自行 pull `bf65dd0..4bc4712`（含本修正）後照常完成 twse quotes 34,034／tpex quotes 10,813／twse insti 1,312／tpex insti 889／indicators 185 列／分點池 2,789 targets。以 stdin 傳入樣式（金鑰不進 argv）掃描 `radar-cron.log`，兩把金鑰命中數皆為 **0**；主機無殘留 `/tmp/radar-env.*`。至此 `--env-file` 已在真實 cron 路徑上運作，不只是測試環境。
- [x] `vps/.env` 與 `pipeline/intraday/.env` 已由 `644` 收為 `600`（`/home/huang` 本即 `700`，故此層屬縱深防禦）。
- [x] **金鑰不輪換：2026-09-02 使用者定案。** 理由：該 VPS 為單一操作者、只有使用者本人能登入，argv 可讀的對象實際上不存在第二個。此決定已知悉「本次修正只堵未來通道、不能撤銷過去每輪 cron 期間的可讀狀態」，仍選擇不重簽。**後續 agent 不要再把輪換列為待辦或自行執行。** repo 端另已確認乾淨：`vps/.env`、`pipeline/intraday/.env` 均在 `.gitignore:28`，git 全歷史無此二檔，無任何 tracked `.env`，所以暴露面從未擴散到 public repo。
- ⚠️ 未評估（另案）：主機另有 `portainer`／`appsec-agent`／`npm-attachment`／`watchtower` 等第三方容器，若任一以 `--pid=host` 或掛 host `/proc` 執行仍看得到 argv；portainer 持 docker socket 本身即等同 root。

## 2026-09-01 TPEx 520 結構化重試與 16:10 安全降級（已同步正式機程式碼）

- [x] HTTP 層新增 `RadarHTTPError(status_code, url, attempts, original_error)`。一般端點仍維持既有三次、線性無 jitter 的預設；TPEx `dailyQuotes` 僅在**從第一次起全為 HTTP 520**時提高到五次（5／10／20／40 秒＋0–2 秒 jitter）。任何 502／timeout 等非 520 一旦出現，整段序列立即維持至多三次，後續 520 也不延長；最後一次失敗不再多 sleep。成功 JSON 的空表仍是 `NoDataError`，JSON／parser／DB 例外不會偽標 HTTP。
- [x] `_run` 對有 HTTP status 的耗盡失敗 additive 回傳 `error_kind='http'`／`status_code`，無 status 的 timeout／connection 則為 `error_kind='transport'`；兩者均保留既有 `import_logs.error` 文字。`import-daily --datasets quotes` 僅在 TWSE quotes 成功、TPEx quotes 是唯一 HTTP 520 error 時 exit **75**。empty 為 0；TWSE／雙錯、非 520、transport 或 combined datasets 一律 1。
- [x] `daily-insti.sh` 是唯一消化 75 的日更腳本：先 warn，仍跑獨立法人與 best-effort 權證主檔，接著明示「本輪不發布」並跳過 aggregate／compute／export／deploy、exit 75 等待 17:40；權證主檔失敗只提示後續重試，不假稱資料會上線。非 75 維持 High 失敗通知與原 exit code，不能發成功。未改 cron、schema、workflow、secrets 或正式 DB。
- [x] 驗證：targeted HTTP／CLI／動態 shell harness 加既有權證 import 共 **29 passed、12 subtests**；完整 pipeline pytest **312 passed、70 subtests**；本機 `bash -n vps/scripts/daily-insti.sh` 與 `git diff --check` 通過。
- [x] commit `e9ce054` 已 push `main`。2026-09-01 13:13 +08 確認正式 VPS 無 DB／分點來源鎖、無日更程序、無 tracked dirty，保留既有四項 untracked 後由 `1e11345` ff-only 同步至 `e9ce054`；正式檔已驗有 520 五次政策與 exit 75。同步只更新版本控制程式碼，**未手動執行正式 DB／import／export／deploy，未改 cron**；真實 520 降級路徑仍待自然事件驗證。
- [x] 2026-08-31 **22:00** 正式分點輪已成功採用 100 萬池：2,619 targets、61,687 rows、0 failed，`23:53:26 CMDEND`，Worker=`5548186b-8d40-4fae-a00b-a596dee59564`。這是已知成功事實；今日端點穩定性仍 unknown。

## 2026-08-31 日常分點權證過渡池：上市成交額門檻（已同步正式機）

- [x] `import-branch-trades` 新增可選 `--warrant-turnover-min N`：未提供時仍完全沿用 legacy `warrants=200` Top-N 與其他既有呼叫；提供時只取標的是 active 普通股的當日 TWSE 認購／認售 `turnover >= N`（含等於；`N=0` 合法、負值 fail closed），並明確取代、不疊加 legacy Top-N，避免同一權證重複入列。TWSE 限制是權證 market，標的可為 TWSE／TPEx 普通股。
- [x] 受版本控制的 `daily-branches.sh` 改為普通股 `--top 0`（不含 ETF）加 `--warrant-turnover-min 1000000`。這不是 TPEx 全市場獨立輪，也沒有改 schema、cron、workflow、評分或正式資料庫。
- [x] fixture 覆蓋 999,999 排除、1,000,000 包含、call／put 皆可、TPEx 權證與 ETF／inactive／未映射標的排除、TWSE 權證連結 TPEx 普通股保留及舊 Top200 相容；targeted `test_warrant_branch_import.py` **13 passed**，完整 pipeline pytest **296 passed、58 subtests**，Luna High review **APPROVE**。
- [x] 為避免半途切換，先等待 17:40 舊版日輪完成（1,199 ok／952 empty／0 failed／29,467 rows；19:21 前完成 export/deploy，Worker version `36874b4b-492e-4862-92a7-66ee69b1933a`）且 DB lock 釋放。確認 VPS 無 tracked dirty 並保留四個既有 untracked 後，才 ff-only 由 `1fefb09` 同步至 `ae1ad45`；正式腳本已驗只含 `--warrant-turnover-min 1000000`、不含 `--warrants 200`。同步本身未手動執行 DB／import／export／deploy，未改 cron／schema／workflow。

## 2026-08-31 分點明細正式發布與上櫃日 K 鎖事件

- [x] 使用者授權後，以不刪未追蹤檔、不重啟回補、不改 cron、不寫 `radar.db` 的受控方式，確認遠端 diff 不與未追蹤檔衝突，再將 VPS `main` 由 `ef4c50c` fast-forward 至 `591c09e`；既有 `cloudflare-data-worker/package-lock.json`、`data/`、`radar-quick-catchup.sh`、`run-backfill.sh` 均保留。重建 `radar-pipeline` 後只執行唯讀 `export-json` 與 data Worker deploy，Worker version=`ca3eff26-680c-4e14-81ca-d3accde31a21`。
- [x] 正式輸出 `branches/track` 共 **138** 個可下鑽分點；`華南永昌-大安` 為 candidate，shard `211de88ea0827fd0.json`，**4,824 rows**、實際日期 2026-05-04～2026-08-28。已登入正式站實測可點開，顯示「分點資料日 2026-08-28」「可用交易日數 83」及近 20 日買／賣超表格，不再進入無紀錄空頁。
- [x] 15:00「上櫃日 K · 略過」已定位：14:10 `daily-market.sh` 因週一題材／公司資料流程一路執行至 15:11，仍持有 `/tmp/radar-db.lock`；15:00 `daily-tpex-quotes.sh` 依 `flock -n` 契約約 6 秒安全退出。15:43 後 `fuser` 無持有者，留下的 0-byte lock path 不是 stale lock，不可刪除。16:10 `daily-insti.sh` 再抓時 `dailyQuotes` 三次 HTTP 520，16:11 提前結束；其後三次完整手動腳本（共 9 次 Python HTTP 嘗試）也都 fail closed。HTTP 520 response 明示 `server: cloudflare`／SJC `cf-ray`、body 16 bytes，同 URL／IP／分鐘內交替 200/520，且不是 429；可判定為 Cloudflare edge 到 TPEx origin 的間歇異常，但沒有 TPEx／Cloudflare 內部 log，不能再斷言更深層 origin 原因。
- [x] 使用者授權手動補抓後，透過同一官方 `dailyQuotes` URL 以 curl 長退避取得一次成功 payload；寫 DB 前驗 `date=20260831`、`stat=ok`、19 欄、10,713 rows，再交回既有 `tpex.fetch_daily_quotes` parser 與 `_run` transaction 匯入。後續權證彙總 845 rows、指標 5,078 rows、scores 750 檔、export 2,410 stocks 與 Worker deploy 均成功，version=`51b690a4-9b50-407d-b981-1d6c26e9533c`。正式 DB 8/31 TPEx=888 stocks／119 ETF／6 ETN／1 other；登入正式站抽查 6488 顯示行情 2026-08-31。暫存檔已刪、lock 已釋放、回補由 guard 自動恢復；**未改 cron／程式碼／workflow**。

## 2026-08-31 個股／首頁 UI 最終正式站 QA（HEAD `8603f3a`）

- [x] `052e0e0`…`8603f3a` 五個 commits 已部署，`8603f3a` deploy 成功。它們**覆寫**本檔與舊 handoff 中所有 `f323f95`「Decision 預設收合／可展開收合」和舊 4／7 homepage tabs 的敘述：Decision 現為固定完整顯示、無收合 button、四 pills 可見；觀察／失效價屬右側行情摘要下方，不在 Decision。
- [x] 個股 header：代號與名稱分離、44×44 Watchlist 固定右上、價格在名稱下方、行情去框；行情摘要的開高低有方向時才顯示 `▲`／`▼` 及紅／綠，持平／缺昨收時為中性色且無 glyph。個股一級 tabs 是 K線／籌碼日報／三大法人／資券／大戶／基本資料／技術／權證。
- [x] 首頁一級 tabs 順序為綜合／策略／未發動／已發動／資券／市場掃描／追高風險／失效／口袋／權證。ThemeToggle 已存在，不是待做項。
- [x] 已登入 in-app browser 390×844 實測：`clientWidth=375 / scrollWidth=375`；`stock-context-grid=347/347`、header `202/202`、price `154/154`、market `135/135`；基本資料地址、股務、來源、3 題材與庫藏股誠實空態可達，且無 console error。Design QA comparison 來源、實作與歷程見根目錄 `design-qa.md`（final result: passed）。

## 2026-08-31 G-RO 策略報表／Phase 2 diff 真正唯讀

- [x] `phase2-diff-report` 與 `phase3-strategy-performance-report` 不再呼叫 `init_db()`、不建表／migration／切 WAL；只接受既存實體 SQLite，驗 DB header 與必要表後以 URI `mode=ro` 的 `SELECT` 讀取。不存在、非 SQLite、缺必要表均 fail closed，保持既有 CLI／報表輸出契約。
- [x] `--out` 在寫檔前拒絕 configured DB、精確 `-wal/-shm/-journal` 路徑，以及既有 symlink／hardlink alias（含 sidecar hardlink）；輸出不會覆寫資料庫或 SQLite sidecar。
- [x] active-WAL fixture 證明可讀到未 checkpoint 的最新策略列；SQL 為 SELECT、無 DB DDL/DML／DB 或 sidecar 檔案建立／migration，DB、WAL 與 journal 內容不變。SQLite 為正確併發 WAL 讀取，可能更新 `-shm` 的 reader-lock/read-mark 協調 metadata；這不是 DB／WAL 內容寫入，且測試確認 SHM 未刪除或截斷。
- [x] 完整 pipeline pytest **278 passed、58 subtests**；Luna High 最終 review **APPROVE**。**未跑正式 VPS 報表、未讀寫正式 DB、未改 cron／workflow。**

## 2026-08-31 F-STATE 權證分點 state 安全續跑（code／測試完成，未啟用正式輪）

- [x] `backfill-warrant-branches` 新增可選 `--state-file BASE`：未給參數時 legacy 行為不變；給定時 BASE 僅為命名種子，每個 `(date, market)` 各有 atomic `stem-YYYY-MM-DD-market.json`，不會反覆改寫全市場×120 日的巨型 JSON。state 以 date＋market＋target hash 分 scope；`ok`／合法 `empty` 跳過，`error`／`pending` 重試，目標池變動只失效對應日期；既有 DB rows 視為 `ok`。
- [x] state mode 只要任一日期未完整即 fail closed：回傳 `resume required`、寫 error import log，CLI nonzero；全部完成才寫 ok。daily import 與 backfill 的明確 state path 均在任何 `init_db`／`get_engine` 前拒絕 configured DB、精確 `-wal/-shm/-journal`、以及 symlink／hardlink alias；write 以同目錄獨占 temp、flush/fsync/replace，並在建立與替換前重驗最終路徑，舊惡意 `<state>.tmp` 不會被使用。
- [x] 個股權證分點面板使用 `index.data_date` 顯示資料日；文案改為「已匯入且符合條件的權證／涵蓋依已匯入池」。舊 500 萬 fallback 不宣稱資料日或全市場涵蓋；100／500 萬門檻、前 15 大限制與既有資料契約未改。
- [x] 完整 pipeline pytest **288 passed、58 subtests**，`npx tsc --noEmit`、`git diff --check` 通過；Luna High 最終 review **APPROVE**。**未跑正式 VPS PoC／DB／export，未改 cron／workflow；VPS free 7GB <20GB gate，禁止自行啟用全市場權證輪。**

## 2026-08-31 分點最近交易日進出契約與 VPS 唯讀續查（13:05–13:06 +08）

- [x] `branches/today.json` 改為向下相容 v1 wrapper：`{version:1, as_of, movements}`。`as_of` 是價格日以前 tracked 分點的實際最大 `branch_trades.date`，再取該日全部 tracked movement；無資料為 null／空 mapping。`/branch` 同時接受舊 bare mapping，顯示「分點最近交易日進出」與新 payload 資料日；買進／賣出為中性 gross、淨買賣正紅負綠零中性、缺佔比為「—」。未改 schema、評分、threshold、排程或正式資料。
- [x] 驗證：exporter targeted **11 passed**；完整 pipeline pytest **290 passed、58 subtests passed**；`web npx tsc --noEmit` 與 `git diff --check` 通過。未跑正式 VPS／DB／export，未改 cron／workflow。
- [x] VPS 唯讀：分點回補仍單實例，最後完成 `2025-05-09`、`fetched=118,264`、至少 `320/490` 日期；DB `5,324,414,976` bytes、WAL `115,298,232` bytes、可用約 7.0GB（75% 使用）。近期未見 import error；最新成功 backup／`integrity_check` 無現有證據可確認，8/22 log 有 Drive quota 403，主機未見 `.db.gz`。dirty tree 仍會阻擋 pull。**未重啟、未改 cron、未執行正式 DB。**

## 2026-08-31 分點排行 bounded detail union（已正式發布）

- [x] `branches/track` detail set 改為全部 tracked 分點聯集最新 ranking snapshot 的非隔日沖 Top100（`rank_score DESC, samples DESC`）；同名以 tracked source 優先，ranking-only 保留 candidate／auto。三層 hard cap 為 Top100、最多 200 branches、每 shard 最多 20,000 rows；tracked 自身超過 200 即 fail closed，ranking 只填剩餘額度。query 只讀 bounded names，嚴格限制 `date >= 120日窗 AND date <= export date`；不改 rankings、stats、score、schema 或 tracked seed。
- [x] shard `as_of`／index `first_date`／additive `last_date` 均為實際 row 日期；tracked 無 rows 仍有 null shard。`/branch` 僅在 index ready 且命中時開明細；loading／index error／shard fetch-or-contract error／valid empty 皆分開呈現，候選、資料日、可用交易日數與每日前15大裁剪限制可見。舊 index/shard 保持可讀。
- [x] 發布前 evidence：正式站 ranking 831、舊 history index 47；`華南永昌-大安` 排名第8、VPS 近120日依舊口徑估 4,887 rows，原為 candidate 未 tracked。2026-08-31 受控發布後正式 index 為 138 分點；該分點實際 shard 為 4,824 rows／83 交易日／2026-05-04～2026-08-28。Worker version=`ca3eff26-680c-4e14-81ca-d3accde31a21`，已登入正式站下鑽驗收通過；未改 DB／cron／workflow。
- [x] 驗證：exporter targeted **16 passed**；完整 pipeline pytest **295 passed、58 subtests passed**；`web npx tsc --noEmit`、`git diff --check` 通過。`npm run build` 已啟動 Next 15.5.20，但長時間無後續 stdout（Node 持續有 CPU）後依協調指示中止，故 **build 未完成，未宣稱通過**；現有 node verifier 僅驗個股 mobile，與本次 `/branch` 契約不適用。

## 2026-08-31 VPS 唯讀稽核（12:16–12:26 +08）

- [x] 本機與 VPS `main` 均為 `8603f3a`；可用 alias 為 `trever-vps`（`trever_vps` 無法解析）。正式 crontab 已核對 14:10／15:00／16:10／17:40／21:20／22:00、01:10、03／09／12／20、23:30、TDCC 週六 06:30、董事每月 16 日 07:00。
- [x] `radar-bf-branches`、`radar-worker` 皆活躍且各有一個 guard/supervisor；權證歷史 done=`2026-08-27T00:25:33+08`。分點為長 in-flight：319 日期、最後完成 2025-05-12、fetched=116,891，03:56–12:26 雖無完成行但 DB 持續成長，故不重啟。
- [x] DB 5.32GB／WAL 115MB／free 7.0GB（75%）、WAL mode；writer 活躍，未跑 `integrity_check`，所以最新 weekly backup 成功與 integrity 為 unknown。主表最新 2026-08-28；`branch_trades_raw` 21,522,284、`daily_prices` 10,205,766、`daily_scores` 19,341、`warrant_daily` 5,729,141。
- [x] 8/28 日更可見成功：TPEx 10,657、margin TWSE 1,291／TPEx 920、branches 56,508；TDCC 8/29 成功（as_of 8/28，3,375／50,625），董事 8/26 成功（2026-07，1,975／45,045；下次 9/16）。
- ⚠️ VPS 有未追蹤 `data/`、`package-lock.json`、`radar-quick-catchup.sh`、`run-backfill.sh`，歷史上會阻斷 `git pull`；不得自行刪除／pull／重啟／改 cron。僅待唯讀確認 weekly backup+integrity 與 completeness／ETA；free <20GB，禁止自行啟用全市場權證輪、正式 DB 寫入或任何回補操作。

## 2026-08-28 權證分點全市場 code-ready（歷史；日常上市 100 萬池已於 2026-08-31 同步）

- 富邦／MoneyDJ `zco` 五鏡像可抓上市與上櫃權證，舊「上櫃無免費來源」說法已更正。`import-warrant-branch-trades --market all` 已以當日有量有額、認購／認售、普通股活躍標的組成合併池，ETF／指數排除；atomic state 會區分 ok／empty／error／pending，錯誤可續跑，cap 超限 fail closed。
- 此段原本的「上市 Top 200／未同步」只屬當時歷史：現行 `daily-branches.sh` 已改為上市、active 普通股標的的認購／認售 `turnover >=100萬` 過渡池，且已於 8/31 22:00 正式成功；**上市＋上櫃全市場** PoC／cron 仍未啟用。`daily-warrant-branches-poc.sh` 未加正式 cron，20GB gate 與人工 benchmark 要求不變。
- 驗證：權證 targeted pytest **12 passed**；完整 pipeline pytest **273 passed、58 subtests passed**；`compileall`、`git diff --check` 通過；另把 PoC script 與 `lib.sh` 經 SSH stdin 交由 VPS `bash -n -s` 唯讀解析，兩者 exit 0（未 pull、未寫 DB、未動 cron）。

## 2026-08-28 個股資訊補強與權證更新修正（歷史；UI 現況由本檔頂部 `8603f3a` 覆寫）

- [x] **個股頁 browser annotation 收斂（歷史 HEAD `f323f95`）**：身份三層、44px 自選星號、行情／基本資料／題材 compact 與絕對 URL guard 的基礎均保留；該輪的 Decision 展開／收合驗收已由 `8603f3a` 的固定完整 Decision 覆寫。當時 390×844（client 375）無水平 overflow 的證據仍作歷程保留。
- [x] **個股手機首屏 UI 校正（`55beda9`／`c26ea04`／`f323f95` 均為歷史基準）**：舊「名稱與報價同行」格式不再適用；當時的 identity 三層、活躍題材嚴格 2+N、八個一級 tab 與 `scrollY=0` regression 修正仍有效。**Decision 預設收合已廢止**；勿依舊截圖恢復被移除的概況列或下方行情卡。
- [x] 個股名稱／報價區保留開高低收、量額與行情資料日；行情目前位於 Decision 右側。完整公司地址、代理電話／地址、官方來源、題材 lifecycle 與庫藏股事實仍在「基本資料」一級 tab（技術左側）；首屏 compact 公司概況因資訊重複已移除，未改回 bottom sheet 或內部分頁。
- [x] 個股權證分點與全市場探索拆成雙層資料契約：既有 `warrant_branches.json` 維持 `>=500 萬`；新增 `branches/warrant-stock-details/index.json` 與 `{stock_id}.json` 分片供個股顯示 `>=100 萬`，100–499 萬標「觀察」、500 萬以上標「大額」。W5 500 萬、首頁／Armed 2,000 萬及 `/branch` 契約均未改；個股權證摘要新增資料日與裁剪限制說明。
- [x] `daily-insti.sh` 修正為權證主檔先於當日彙總；主檔失敗仍沿用既有 mapping 彙總，不阻擋法人／日K 上線。16:10 crontab 時間不變、未新增獨立腳本或 cron。
- [x] 驗證：完整 pipeline pytest **263 passed、58 subtests passed**；Terra 初版 `npm run build` 通過；分片版由主協調重跑 build 時停滯中止，未宣稱通過；分片版 `npx tsc --noEmit` 與 targeted pytest 通過。手機 verifier 因 repo 未安裝 `playwright` 無法執行，未假冒通過；正式 `import-themes`／`import-buybacks`、正式 DB 寫入與資料 deploy 未執行。

## 2026-08-27 個股基本資料 UI 整併

- [x] 個股頁新增「基本資料」一級 tab，順序在「技術」左側；公司資料／題材／庫藏股為同一連續三 section 面板，集團鑽取、官方來源日、MOPS 事實與舊 JSON safe fallback 均保留。
- [x] 名稱區移除 bulky 公司／題材／庫藏股區塊；活躍題材只在 `eligible + active + 報價日一致` 時顯示，最多 2 個加 `+N`，所有 stale／retired／unknown／日期不一致狀態留在基本資料面板；題材每筆另顯示分類日、來源更新與來源／缺值，維持可稽核性。
- [x] 個股一級 tab、集團與來源連結維持 44px touch target；既有手機驗證擴充基本資料／無內部分頁／無橫向溢位檢查。純前端，未改 JSON、API、pipeline、schema、分數、VPS 或 workflow。

## 2026-08-27 Lifecycle v2 與正式 geo 發布

- [x] `strategy_meta` lifecycle v2（effective date 2026-08-27）依使用者恢復觀察決策，將 `S2_BREAKOUT20`、`S5_PULLBACK_SUPPORT` 自 Retired 恢復為 Shadow；兩者回主要策略選擇器，但不宣稱有效，未改策略公式、權重、`final`、selector cap、DB 或正式回算。JSON export targeted pytest **9 passed**，`npx tsc --noEmit` 通過。
- [x] 16:58 已受控完成正式 VPS geo 發布：`import-geo` 1,985 筆、股務代理 1,985／1,985、3376 驗證、`export-json` 2,410 檔，Worker version `b377bc68-3c19-42eb-86f5-4e3c20d977d4`；回補 pause 後已 resume，發布前備份為 `/home/huang/geo-before-import-20260827-1658.sql.gz`。`import-themes`、`import-buybacks` 與正式全市場重算仍未執行。

## 2026-08-27 17:34 快速正式發布

- [x] 依使用者要求快速發布：VPS 以 ff-only 更新至 `9d1dd69`，使用新版 source-controlled `_build_strategy_meta` 僅原子更新 `radar.json.strategy_meta`；未重算、未改 DB、未做全量 `export-json`。驗證 `S2`／`S5` 為 Shadow、`version=2`、`retired_count=0`；data Worker version `d4f7df6a-dcaf-40be-b033-3c9a901971cb`。
- [x] cleanup 已移除 flag、釋放 lock 並恢復歷史回補；17:35:50 發現 container 仍 running，根因是 cleanup 在 guard 記錄 `STATE=paused` 後 unpause，guard 只看內部 state 未重驗 container，形成 state-cache race。17:36 已手動 pause 並確認 `paused=true`；本輪未改 guard 程式，19:30 應由既有 guard 依 state 自動 unpause，待後續驗證。GitHub Actions Pages code deploy 已成功。

## 上線資訊

| 項目 | 值 |
|---|---|
| 正式網址 | https://radar.techtrever.com(= https://trever-radar.pages.dev) |
| 公開狀態 | **已鎖站(私人測試版)**:門禁 = 站內 Google 登入 + `/data` Worker 驗 JWT/核准狀態(或 `RADAR_SERVICE_KEY`)。Cloudflare Access 已於 2026-08-20 關閉(裸 curl `/data/radar.json` 直接 401;無痕開站為站內 Google 登入,管理員登入後資料正常)。noindex + robots.txt 保留。 |
| 自動排程 | **2026-07-18 WP-B3 cutover 後:資料 = VPS cron(`vps/scripts/` 五條每日輪 + weekly-backup,時間表見 `docs/31` §3)直接 `wrangler deploy` Workers 靜態資產到 `/data/*`**;GitHub Actions 只剩 push main 觸發 `deploy`(純 build+deploy,無資料步驟)。5 支資料 workflow 檔案保留但已無觸發源(Worker cron 已停),回滾窗兩週後刪(`docs/31` §9)。`docs/08` §0 已改寫為 VPS cron 表(WP-B5,2026-07-18) |
| Repo | github.com/bbdevin/trever-radar(**公開**;2026-07-18 cutover 時曾轉 private,但 private 觸發 GitHub Actions 帳戶 Billing 阻斷,修復需綁付款方式——使用者依免綁卡原則決定改回 public。GitHub 自 WP-B1 起零資料,docs/10 §3 合規紅線不受影響) |
| DB | SQLite。**2026-07-18 WP-B3 cutover 完成:VPS 主本 = 唯一寫者與唯一真相**,備份 = VPS 本機 + Google Drive 週快照(`docs/31` §4)。雲端鏈(Actions cache 續存)已退役,回滾窗兩週內保留 workflow 檔案不刪 |

## AI Workflow Status

2026-07-09 起,本專案開發流程改為**不依賴 Fable 或任一單一模型**的多 agent 協作,完整規則見根目錄 `AGENTS.md`、`docs/17_no_fable_workflow.md`、`docs/18_handoff_template.md`。

- 流程為**模型中立、角色導向**:Planner / Executor / Reviewer 由本次任務指定,不由模型品牌永久決定;規則見 `AGENTS.md` 與 `docs/17_no_fable_workflow.md`。
- 工具清單:Claude Code、AGY/Gemini、Codex、GPT/Grok 等高階模型均可任三角色;Cursor 為 IDE / 確認介面;人類使用者為唯一決策者。

下一步:**資料架構 B 案剩餘項**(`docs/31` v3)：WP-B0～B3、B5、B7 已完成，repo 依免綁卡定案維持 public；尚餘 WP-B4 加固／還原演練，以及需人工確認才可啟動的 WP-B6／WP-M4。策略解耦與績效閉環現況見下方未完成清單，不得把本段解讀為重新遷移或轉 private。

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
- [x] `import-branch-trades`:富邦公開頁分點進出(每股前15大買/賣超,張+佔比;每晚評分池80檔;2026-07-07 起累積)
- [x] `import-themes`:概念股分類爬蟲(富邦 zha/zhc,~1,060 類含矽晶圓/AI晶片等細分)→ themes/stock_themes;每週一自動更新;首次全量走 data-backfill task=themes
- [x] 首頁資金流向改版:**Treemap 熱力圖**(大小=金額、紅綠=漲跌、▲▼=vs20日量能流入/流出)+ 產業/題材雙模式 + 流入/退潮領頭 chips + 點格下鑽成分股 + **資金量能與漲跌幅排序切換** (可秒看族群性大漲/大跌)
- [x] 股票卡資訊優化:移除干擾性的評分細項、新增動態 **概念股題材標籤 (Themes)** 與 **公司基本業務說明 (Description)**，並採用 `UI/UX Pro Max` 設計美學。
- [x] 波段二(docs/14):**日K/週K/月K 切換**(前端重取樣,指標自動變週/月線)、**全站搜尋**(/ 快捷鍵,索引 2,470 檔,個股 JSON 池擴至評分池 959 檔、非榜單裁 600 根)、**權證分點張數**(每晚抓成交前 15 大上市權證,個股頁權證列可展開分點進出;上櫃權證無免費來源)
- [x] K 線圖升級:均線 5/10/20/季/半年/年 + 布林(預設開、可勾選關、localStorage 記偏好)、副圖 MACD/KD/RSI 切換、十字游標 OHLC+均線 legend、指標以全歷史計算再切區間
- [x] `compute-scores`:盤後綜合分數(分點35/權證20/技術20/法人15/題材10 加權;風險扣分:短線過熱/爆量長上影/開高走低/RSI過熱/外資連賣/融資過熱;法人買超設佔成交量1%顯著性門檻)→ `daily_scores` + 理由/風險 JSON;首頁「綜合」榜(預設 tab)
- [x] `branch_score`:分點籌碼分 V1 接入綜合分(04 §2):連買、多分點同步、買方集中度、大戶淨流、反手倒貨風險;使用富邦公開頁前15大買賣超裁剪資料,地緣/關鍵分點待人工名單
- [x] `compute-performance`:訊號績效回填,以次一交易日還原開盤價為 entry,回填 `daily_scores` 的 fwd_1d/3d/5d/10d/20d 報酬;nightly/push 皆會更新已成熟訊號
- [x] upsert 只更新帶入欄位(防止日常匯入洗掉補充欄位)
- [x] SQLite WAL + busy timeout(回補與匯出可並行)

### 前端(web/,Next.js 15 靜態輸出)
- [x] 今日雷達:市場總覽卡、**族群資金流面板**(產業別金額佔比 / vs20日均 / 廣度 / 龍頭)、**綜合/熱門/爆量/強勢/權證/Mark策略六榜**
- [x] 股票卡:權證認購成交金額、20日倍數、購售比、成交檔數摘要
- [x] 個股頁:上市以來 K 線 + 成交量(lightweight-charts)、區間切換 1月/3月/1年/5年/全部、**權證 Tab**(60 日認購/認售金額趨勢 + 當日熱門權證明細)
- [x] 個股頁:**分點 Tab**(分點分、分點觸發理由/風險、當日前15大買賣超分點明細:買張/賣張/淨張/佔比)
- [x] 個股頁 K 線疊加 MA5/20/60,下方顯示技術分、MA20/60、RSI14、量比與觸發理由
- [x] 現代 fintech UI:深色、玻璃頂欄、手機底部導航、SVG 圖示、Manrope 數字字體、骨架屏、RWD 375–1440
- [x] 台股慣例紅漲綠跌、免責聲明常駐
- [x] **觀察價/失效價**(2026-07-10,04 §10):`daily_scores` 新增 `watch_price`/`stop_price`,股票卡與個股頁技術面板顯示
- [x] **自選股**(2026-07-10):Supabase `watchlist` 表 + RLS(見 `docs/sql/20260710002358_create_watchlist.sql`,需人工在 Supabase 執行一次);全站 Context 只查一次、卡片與個股頁 ★ 按鈕、新頁 `/watchlist`
- [x] **探索頁**(2026-07-10,部分):新頁 `/explore`,先做**集中度**(前5大買超分點佔量躍升排行,新純函式 `buy_concentration` 從既有 B3 評分邏輯抽出)與**題材**(重用首頁資金流 `themes` 資料)兩個 tab;地緣/關鍵分點/分點績效榜/權證異動因需人工名單或與 `/branch` 重疊,暫緩
- [x] **分點追蹤視角**(2026-07-11,docs/24 Part B B1+B2):export 為每個 tracked branch(manual+auto)產 `branches/track/{hash}.json`(近 120 日曆日的緊湊 `[date,stock_id,net_lots,pct]` 列 + 股名/期末收盤對照;檔名為 branch_name 的 sha1 前 16 碼,index.json 列對照)+ 種子 DB 單元測試;前端 `/branch` 排行榜點分點卡片(或「分點追蹤視角」鈕)切入同 tab 視圖,近 1/5/10/20/自訂日 pills(自訂 clamp 可用交易日數),客戶端純函式 `aggregateBranchRows` 加總出淨買超/反向賣超表(語意化 table、估算金額 net×1000×close、平均佔比),誠實限制標注;`npm run build` 過、pytest 全過、聚合 3 案例 node 驗證通過,未新增依賴/未改 token。
- [x] **WP-V1 首頁/自選 5 秒掃讀優化**(2026-07-11,docs/23 §2 V1):股票卡次要細項(金額/量比/外資/投信)由 4 欄堆疊收斂成一行小字降層級(不刪資料);卡片左側 3px inset 狀態色條(有明顯風險扣分→destructive/風險紅、綜合分≥65 觀察門檻→warn/琥珀、其餘→中性 line,僅用既有 token 且色條非唯一訊號);自選/branch 可點列補 `min-h-11`+`cursor-pointer`+`transition-colors`,★ 鈕與 branch 展開鈕補 `aria-label`/`aria-expanded`;首頁教育性空狀態文案、`/watchlist` 載入改多列 Skeleton;`npm run build` 過,未新增依賴/未改配色 token 語意。
- [x] **UI 全面遷移 Tailwind CSS v4 + shadcn/ui**(2026-07-10):全站 6 頁 + 所有元件從手刻 CSS class 改為 Tailwind utility(僅保留 `.container`/`.num`/裸 `.up`/`.down`/`.flat`/`fadeUp` keyframe 等仍被動態或跨頁共用的少量 class);icon 除品牌 logo 外全改 `lucide-react`;搜尋面板改 shadcn `Command`,登入選單改 `DropdownMenu`,個股頁權證明細表改 **TanStack Table**(可排序 + 展開列);K 線圖仍為 lightweight-charts(未改動);deep design token 對照見 `docs/07_frontend_pages.md`。過程中修掉兩個遷移期間才會暴露的既有 bug:①舊 `.grid` class 與 Tailwind 內建 `grid`/`grid-cols-*` utility 同名碰撞(unlayered 規則蓋過 layered utility),導致多處 4 欄版面被壓成 3 欄;②`@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy token,深色模式因數值巧合未現形但會壞掉淺色模式。深色為預設主題,淺色 token 已備妥;**2026-07-11(docs/23 V3.1)已加頂欄 `ThemeToggle` 切換 UI**(接既有 `.dark` class 機制、`localStorage` 記偏好、`<body>` 開頭 inline script 防 FOUC,預設仍深色)。**淺色對比已於 2026-07-12 補強**:被當文字色用的 brand-extension token `--ink-2`/`--warn`/`--accent-2`/`--legacy-accent` 改為雙主題定義(`:root` 淺色可讀值對白 4.9–6.5:1、`.dark` 保留原深色調值,深色逐位元不變);`--up`/`--down` 刻意兩主題一致不覆寫。KChart 格線/軸/水印色亦補淺色組(`chartColors(isDark)` + MutationObserver 即時切換)。

- [x] **Armed 狀態追蹤**(2026-07-12 A1-A2;2026-08-20 A4 Extended/Faded):`derive_radar_state` 同日近似 Quiet→Armed→Triggered→Extended→Faded;`lists.armed/triggered/extended/faded`;首頁 tab + 卡片徽章。不新增資料表。正式 list 等下次 VPS `export-json`。延後:armed_days / 跨日持久。

### 基礎設施
- [x] **凌晨長任務常態化**:data-backfill 每天 01:10 深歷史增量(已拉深跳過,日常近零請求);週六 01:10 DB 備份(**週六全市場還原因子+指標全重算已於 2026-07-10 停用,改 VPS 跑後回灌,雲端 fallback=手動 task=adjust**);排程總表 = docs/08 §0
- [x] **分批即時更新**:14:10 收盤閃電更新(日K+權證+指標+分數→部署,資料日當天變今天)→ 16:10 法人+權證主檔 → 17:40 融資券+分點全量 → 21:00 補抓;各資料集「有效日」寫進 radar.json `freshness`,晚公布的前端標「今日尚未公布,暫用前一日」並以前一日數值填充
- [x] 管線效能優化(docs/15):指標增量計算(`--days 5`,全市場 26 秒,原全歷史重算數十分)、release 備份週五化(原三支 workflow 每日各 gzip 1GB)、修正 daily-warrants/branches 繞過 cache 的分岔 bug、pip/npm 快取
- [x] GitHub Actions 全自動管線 + Cloudflare Pages 部署 + 自訂網域（歷史管線；2026-07-18 cutover 後 GitHub Actions 只負責程式碼 build／deploy）
- [x] `main` push 觸發正式程式碼部署；2026-07-18 cutover 後不再讀 cache／release DB、匯出資料或碰正式 `radar.db`
- [x] FinMind 免費 token(600 req/hr,`RADAR_FINMIND_TOKEN`,GitHub secret 已設)
- [x] **排程觸發改用 Cloudflare Worker（2026-07-09 歷史里程碑）**：其後已於 2026-07-18 WP-B3 cutover 退役；正式資料排程現由 VPS cron 執行，Cloudflare trigger crons 已清空，資料 workflow 檔案只保留且無觸發源

## 未完成(依優先序)

0. **資料架構 B 案後續（遷移主鏈已完成）**：`docs/31` v3 的 WP-B0～B3、B5、B7 均已完成；VPS `radar.db` 是唯一寫者，資料走 Workers 靜態資產，備份走 Google Drive，repo 依免綁卡定案維持 public。尚餘 WP-B4 加固／還原演練，以及 WP-B6／WP-M4 全市場回補；後者雖已修妥 `backfill_warrant_branches` 前置 bug，但正式開跑仍須使用者確認。歷史 cutover 細節與回滾紀錄保留在 `docs/31`／`docs/32`，不得把本項解讀為重新遷移、轉 private 或自動啟動回補。
1. ~~**私人測試版 Access**(`docs/21` A0-A2)~~ ✅ **2026-07-13 完成**:使用者手動於 Cloudflare Zero Trust 設定(Google IdP + email 白名單,單一 Application 覆蓋三類入口),執行紀錄見 `docs/21` §4 A3;R2 部分見第 6 項,仍未動。
2. **B 方案 Phase 2—策略/分數解耦**(`docs/20`,高風險資料語意變更):S1-S13 只產生 tag/reason,不得再增加 `tech_score` 或其他分項;~~補 S2-S13 測試~~ **2026-07-10 完成**(S2-S13 正例/邊界反例 36 項 + 解耦回歸斷言,S11-S13 抽純函式零行為變化,pytest 91 全過,verifier 窮舉探針 CONFIRMED);~~舊/新分數差異報告~~ **2026-08-19 完成**(CLI `python -m pipeline.radar.cli phase2-diff-report`,模組 `pipeline/radar/compute/phase2_diff_report.py`,本機樣本 `docs/reports/phase2_score_diff_2026-07-06.md`——77 檔、該日 0 檔受 S1-S10 bonus 影響;**VPS 最新資料日重跑待使用者確認**)。仍缺:使用者批准後的正式全市場重算、回灌及部署。
3. **B 方案 Phase 3—策略績效閉環**(`docs/20`):✅ **工作 3 完成（2026-08-19）**。VPS 正式資料日（2026-08-19）報告已產出：180 日 lookback、1659 事件、508 matured 20d 樣本。lifecycle v2（2026-08-27）依使用者恢復觀察決策改為 **S2、S5 = Shadow**；其餘亦為 Shadow；無 Active／Retired。`strategy_meta` 欄位已新增至 `json_export.py`（含 status/h5/h10/h20/sufficient_samples）；前端首頁策略 Tab 加 Shadow badge 與績效摘要行。此為 metadata 觀察狀態，不改策略公式、權重、`final`、selector cap、DB 或正式回算。
4a. **盤中訊號雷達 + 分點追蹤視角**(`docs/24`,2026-07-11 使用者指定排入):~~Part B 分點追蹤視角~~ **2026-07-11 完成**(B1 export + B2 前端);~~Part A 盤中雷達~~ **2026-07-12 程式碼完成**(I1-I3 完成,含 `worker.py` 與前端 `IntradayPanel.tsx` 即時推播),部署方向為 VPS docker+cron(非本機,2026-07-12 使用者定案,`docs/vps_backfill_plan.md` Step 5)。Supabase SQL 已執行、Fugle 金鑰已備。排查發現 Step 5 手冊寫於 2026-07-13 Cloudflare Access 上線前,`.env` 缺 Access service token,worker 抓 `radar.json` 會被 Access 擋 403 fatal exit;已補 `pipeline/intraday/.env.example`(六變數)與 crontab 整合。2026-07-16 使用者建立 Access Service Token 並掛上既有 Access Application 原則後,VPS 首次 live smoke test 炸出 `fugle-marketdata` 套件 API 飄移(`connect()/subscribe()` 官方已改同步呼叫、WebSocket callback 給原始 JSON 字串非 dict),當晚修復(commit `fcb3aef`,回歸測試 pytest 104 全過)。2026-07-18 確認已跟上盤中實跑、cron 常態化,首頁盤中面板穩定 online,但**當天回報 online 卻始終沒有任何訊號推播**;查 07-17 全日 log 發現連續數百筆「Error processing trade: no running event loop」——Fugle SDK 的 `on("message")` callback 跑在背景執行緒(`connect()/subscribe()` 是同步方法),不是 `asyncio.run(main())` 那條主執行緒,`process_trade()` 用 `asyncio.create_task(push_signal(...))` 排程推播,在沒有事件迴圈的執行緒下 `create_task()` 本身就 RuntimeError,`push_signal()` 主體(真正寫 Supabase 那段)從未執行過,100% 靜默失敗;心跳不受影響是因為它跑在主執行緒事件迴圈。**✅ 2026-07-18 當天修復**(commit `c7ce175`):`push_signal` 改一般同步函式、`process_trade()` 直接呼叫,不再依賴事件迴圈;順便把 I-1~I-4 門檻判定抽成純函式 `evaluate_signals()`(docs/24 §2.2,方便單元測試)並補齊原本掛零沒接線的 **I-2(爆量)**——用 `adv20` 依開盤經過分鐘數等比例折算基準達 2 倍觸發(pipeline 尚未輸出「同時刻量能基準曲線」,先求有訊號可用,精確版待後補)。新回歸測試刻意先對照舊碼重現一模一樣的 production traceback 再驗證修正,pytest 115 全過。Part A 全流程完成上線,待下一個交易日觀察是否真的開始推播訊號。
5. **功能·視覺 backlog**(`docs/23`)：✅ **2026-07-12 F 系列全數完成**。已完成清單：V1/V2/V3.1/V3.2(2026-07-11)；F2 日報摘要、F3 訊號摘要（合入個股頁）、F1.1/F1.2 自選距關鍵價%+排序（合入 IA-4A）、V3.3 Sonner toast、**F1.3 一鍵加入今日 Armed**、**F4.1 掃描收斂（合入 IA-1B）+ F4.2 策略四類分群**（2026-07-12）。~~剩餘僅 V3 淺色 token 對比為「只回報未改」~~ **V3 淺色 token 對比已於 2026-07-12 補強(含 KChart 淺色主題)**。不得插隊，Executor 依 WP-* 工作包執行。
5a. **任務導向 UI 資訊架構**(`docs/25`)：IA-1A～IA-4B 已完成。**IA-5 / IA-3b / IA-5b（2026-08-20；頁籤現況更新至 2026-08-31）**：個股一級分頁為 `K線 | 籌碼日報 | 三大法人 | 資券 | 大戶 | 基本資料 | 技術 | 權證`；K 線不堆技術卡、手機圖區放大；籌碼與分點追蹤買方/賣方全寬對半切；點分點下鑽。**掃讀微優化（同日）**：K 線訊號摘要可收合、手機 sticky 一級 tab、修正「綜合評分」錯字；首屏 Decision 則依 2026-08-31 現況固定完整顯示，不可混為同一元件。
6. ~~R2 R0-R2(`docs/21`)~~ **2026-07-15 作廢**:R2 啟用需綁信用卡,不採用;快照職責改 Google Drive、還原演練併入 `docs/31` WP-B4。
7. **B 方案 Phase 4—排程簡化**(`docs/20`):📝 **2026-08-20 提案稿已改寫**（對齊 VPS cron + Worker 資料層;建議 14:10/22:10 兩次資料 deploy,中間輪只寫 DB）。**cron/script 未改**,待使用者確認目標態或變體 B 後另開實作。不得未確認就改 `vps/scripts` 或 workflow。
  5b. **首頁掃讀體驗+個股頁資訊架構統一**(docs/28,2026-07-12 規劃定案):WP-H2 語意色彩層次(已完成 2026-07-12)→ **WP-H4 個股頁分點統一(2026-07-12 完成,commit 83649ae)**→ **WP-H1 題材分組(2026-08-20 完成)**:綜合/市場掃描可切「分數|題材」,一檔只歸當日最熱題材、sticky header;桌機與分數榜同 2/3/4 欄且預設全開,手機前 3 組展開→ **WP-H3 卡片走勢改當日分時(2026-08-20 完成)**:Fugle 1 分 K → `spark_day`/`spark_open`,缺資料標「30日」→ **WP-H5 手機版(2026-07-12 完成)**。**docs/28 已全部完成**。
6a. **地緣券商+庫藏股分點+關鍵分點同買 → 口袋名單**(`docs/27`、總規劃見 `docs/37`):~~G0~~ / ~~G1~~ / ~~G2~~ / ~~**G4 口袋 UI 2026-08-20 完成**~~(首頁「口袋」tab + badges + 個股頁摘要 + `/branch` 關鍵徽章)。**G3 改分期**：G3a **官方 MOPS t35sc09／KB1 code、fixture、point-in-time export、個股事實區完成（2026-08-27）**；只接受 bounded 1–366 日手動 CLI、上市與上櫃全成功才 transaction upsert，`import-buybacks` 與排程尚未執行。16:58 `export-json`／data Worker deploy 已發布既有快照，但未更新庫藏股官方來源資料。G3b **KB2 不實作**；G3c 的 branch×stock point-in-time **唯讀 shadow CLI／JSON contract 已完成（2026-08-27）**，只含獨立 buy／sell episode，buy→sell 配對規則／coverage 未定；未跑正式 DB、未接 UI、未定門檻，schema／歷史回算仍待人工確認。地緣涵蓋度在 7a 全市場每日池後才完整。
7a. **全市場擴容**(`docs/26`,2026-07-12 使用者定案「有幾檔抓幾檔」):~~WP-M1 個股 JSON 池全市場~~ **✅ 2026-08-25**(`export-json` 全 active stock/etf 每日更新,不綁評分池) → ~~WP-M3 branch_hist.db 拆分~~(**2026-07-15 因 B 案取消**,見 docs/31 §9)→ WP-M2 一輪制與 WP-M4 全市場 march-back 併入 `docs/31` WP-B6,於 cutover 後執行。
8. ~~deep-backfill --all~~ **執行狀態需另行查證**:完成與否不得只信本檔舊紀錄;若需 `task=adjust` 或 VPS 回灌,先依 `vps_backfill_plan.md` 與高風險流程確認。
9. **分點排行資料累積**:可信度排行榜已完成,統計效力需 2–3 個月。地緣/關鍵分點人工名單、五年分點擴容、LINE Bot 依 B 方案延後;~~V2 盤中延後~~ 盤中已依 `docs/24` 重新規劃排入(見 4a)。
10. **資券／大戶／使用率排行**(`docs/34`):A0–A3 已上線；**A4 程式已 merge（2026-08-25）**——240 日回補 CLI + 顯示窗 `min(元旦,today−6月)` + MarginPanel；VPS 回補排程中。

## 已知債務 / 注意

- ~~分點 5 年全量的架構前置(release 2GB/cache 10GB 上限、R2 拆檔)~~ **2026-07-15 因 B 案(`docs/31`)大幅緩解**:cutover 後 DB 常駐 VPS 磁碟,雲端上限消失;P2 是否開跑改由 VPS 磁碟餘量與來源站禮貌率決定,仍待使用者另案確認。

- 個股 JSON 一檔約 0.5MB(全歷史);擴到數百檔時改「預設 5 年 + 按需載入」
- 權證榜目前是「認購成交金額 / 20 日均值」的異動排序,尚不是 04 定義的完整 0–100 權證分;完整分數與 reasons/risks 等評分模組一起做
- 權證 warrant_daily 約 1,000 萬列/年增速;彙總表已建,依 05 規劃明細僅留 2 年(清理排程未寫)
- 還原價資料層已完成,但尚未接 nightly 全市場自動跑;目前用 `compute-adjustments --ids/--top/--all` 手動或分批補。`TaiwanStockPriceAdj` 是付費資料,本案改用免費 `TaiwanStockDividendResult` 自算
- 技術指標已接 nightly `compute-indicators --all`;若某些股票尚未補還原因子,會先以 `adj_factor=1` 計算,之後補因子再重算即可
- 已下市權證不在主檔,kind 靠代號尾碼推斷可能誤標(認售尾碼不只 P,還有 T/Q/S 等)→ 歷史認購/認售比略失真;認售佔比極低,影響小
- 評分門檻(65 分觀察線、法人 1% 顯著性、權證倍數分段)為 04 起始值,待訊號績效回填後校準;目前寧缺勿濫,達標日常 0–5 檔屬預期
- 分點分 V1 只用「已抓到的前15大買賣超」,不是全市場全量分點;冷門股或未入評分池股票沒有分點史,地緣/關鍵分點/可信度分數尚未納入
- `compute-adjustments` 逐列 UPDATE,跑 --all 會慢;改 executemany 批次後再跑全市場
- Actions 有 Node 20 → 24 的 deprecation 警告(actions 版本升級,無急迫)
- ~~**排程觸發改 Cloudflare Worker,無備援(2026-07-09)**:Worker 或 `GH_TOKEN` 壞掉會靜默停止觸發~~ **已隨 WP-B3 退役(2026-07-18)**:該 Cloudflare Worker trigger 的 cron 已清空(排程觸發改由 VPS cron 自己執行,不再依賴這條鏈),此債務隨之消失;假日跳過邏輯仍**維持不做**——管線在非交易日已靠 `NoDataError` 安全空跑(`importer.py` 的 `_run()` 接住例外記 log,不會壞資料),手刻假日曆的「錯殺交易日」風險大於省下的請求數
- 雲端 DB 已退役,本機僅開發,正式真相 = VPS(`radar.db` 常駐 VPS 唯一寫者,見 `docs/31`)
- **策略/技術評分邏輯改動不會立即反映在正式資料**:S1-S10 的代碼存於 `indicators_daily.reasons`(S11-S13 在 `daily_scores.reasons`),而增量重算(`compute-indicators --days 5`)會直接跳過「指標日期已跟上價格日期」的股票,不會因程式改版重算。改了策略程式後:當日榜要等**下一交易日 14:10** 的 `daily-market` 增量才會用新邏輯產生當日 reasons;全歷史回補現改為 **VPS 全重算**(`vps/scripts/manual-catchup.sh` / docker,直接寫 VPS 主本;舊 `gh workflow run data-backfill -f task=adjust` 路徑已隨 WP-B3 死亡)。**注意:VPS 重算前務必 pull 最新 main**(策略邏輯在程式碼裡,舊碼重算出來還是舊 reasons)。2026-07-10 策略上線首日 S1-S10 全部 0 檔即此因(當日指標已算過、增量跳過),非邏輯錯誤。freshness 跳過機制本身不改

## 最近完成

- 2026-08-27 **E2 branch×stock point-in-time shadow contract（唯讀程式／測試完成，未跑正式 DB／VPS）**：新增 `python -m radar branch-point-in-time-report --as-of ... --from ... --to ... --out ...`，只接受既存實體 SQLite，以專用 `mode=ro` engine 的 `SELECT` 讀現有資料；DB 不存在與 out=DB 都 fail closed，不建表／migration、不寫 DB、不改排行／分數／UI。universe 誠實合併 as-of 前具 timestamp 的 manual tracked branches 與 ranking snapshots 可辨識候選，null timestamp 另列 coverage；JSON 報告列出來源／覆蓋率與前 15 大裁剪限制。buy/sell event 以 ±1% 門檻、`abs(pct)` 賣超及完整 `daily_prices` 日期日曆 episode 合併；20 日事件價分位只讀當日及過去資料，後續表現只為次一日 open 至第 5 市場日 close 的描述性成熟觀察，缺值均為 unknown。**只統計獨立 buy／sell episode，不做 buy→sell 配對或配對 coverage。** E2 targeted pytest **11 passed**、E2＋既有分點 targeted **39 passed**、完整 pytest **247 passed／55 subtests**（merge／全 null 日期、future-leak、未成熟、缺價／缺 pct、universe timestamp、固定 JSON、read-only DML、缺 DB、out=DB、CLI）。未執行正式 DB／VPS 報表，未定樣本或產品門檻；不宣稱分點交易獲利或勝率。
- 2026-08-27 **docs/37 C 題材 freshness／過時治理（程式、fixture、UI、typecheck、正式 build 完成）**：`themes` 保留舊欄並只增 `source_updated_at`／`data_date`／`status`，既有 SQLite runtime additive migration 不刪資料。`import-themes` 只有完整、非 empty、非 `--limit` 的來源成功才寫入 active；partial／empty／失敗／`--limit` 保留既有分類與成分並 stale，來源缺列不自動 retired，既有 retired 不自動復活；TTL 35 日逾期或未來資料日同樣 stale。`radar.json.themes` 維持既有欄位並補 lifecycle／`heat_date`／`freshness.themes`；同名題材以 stock／date 去重，未來資料不進當日熱度、歷史基期、產業子題材或 freshness 日期；個股 JSON 增 `company_themes`／`recent_theme_heat`。個股 UI 將分類與熱度分層，未知狀態明示，且只有 active、分類資料日不晚於 quote、熱度日等於 quote 才顯示「近期可能相關題材」或輸出既有 H1；不改 `final`／`theme_score`／`pocket_score`／H1 門檻，未新增導航。C targeted pytest **29 passed**、完整 pytest **236 passed／55 subtests**、`npx tsc --noEmit` 與乾淨快取 `npm run build`（12/12 static pages、2/2 export）均通過。`import-themes` 未執行；16:58 的正式 `export-json`／data Worker deploy 只發布既有快照，未更新題材官方來源資料。該 16:58 歷史事件未執行 migration、回算或程式碼部署，未動 workflow／secrets／`adj_factor`。
- 2026-08-27 **docs/37 B+D 公司資訊／集團鑽取（程式、fixture、UI、typecheck、正式 build 與 geo 發布完成）**：`company_profiles` 新增只增不減的公司產業碼、股務代理、來源與來源資料日欄位，既有 SQLite 由 runtime additive migration 補欄；TWSE／TPEx 官方欄位 mapping、空值與民國日期均有 fixture。個股 JSON 增加 optional `industry`／`company_profile`，名稱下方以 44px 可展開的 compact 公司資訊呈現，舊 JSON 安全 fallback。集團採 repo 版本化 mapping，不建 DB table；只 seed 華新麗華官方可驗證的 `1605/2344/2492/5469/6116`，輸出 `groups.json` 與個股 `company_groups`，`/group?id=` 不進主導航。群組摘要直接取 `stocks + daily_prices` 最新可用報價，無資料時誠實標示。B+D targeted pytest **30 passed**、完整 pytest **228 passed／55 subtests**、`npx tsc --noEmit` 與乾淨快取 `npm run build`（12/12 static pages、2/2 export）均通過；另將兩個既有盤中 worker regression tests 固定為交易時段，消除依執行時鐘造成的假失敗，未改 production worker。16:58 受控完成正式 `import-geo` 1,985、股務代理 1,985／1,985、3376 驗證與 `export-json` 2,410／data Worker deploy，Worker `b377bc68-3c19-42eb-86f5-4e3c20d977d4`；回補 pause 後已 resume、備份 `/home/huang/geo-before-import-20260827-1658.sql.gz`。該 16:58 歷史事件未執行 migration、全市場重算或程式碼部署，未改 workflow／secrets；17:34 已另完成正式策略 metadata 原子發布與 Pages code deploy。
- 2026-08-27 **A2 策略／首頁／勝率定義契約（程式／測試完成，未正式 DB 回算）**：首頁綜合榜改為嚴格 `daily_scores.final >=65`（不足 15 檔不再低分保底），同分依 `branch_score`（null 最低）再依成交額排序；S12 在缺 `concentration_avg20` 或基期 `<=0` 時 fail closed。`strategy_meta` 為版本化 additive lifecycle contract（`status/effective_date/rationale/decision_ref/version`）；lifecycle v2（2026-08-27）依使用者恢復觀察決策將 S2、S5 設為 Shadow，回主要策略選擇器但不宣稱有效，無任意 Retired；舊 JSON 缺 metadata 時前端完整 fallback。未改策略公式、`final` 權重、狀態門檻、selector cap、分點績效排行 V2、schema、workflow、VPS 或正式資料。
- 2026-08-27 **S4 V2／Armed A1 後續整體規劃落檔**：新增 `docs/37_company_theme_group_buyback_branch_plan.md`，永久記錄 Confirmed Scope A1（程式／測試完成）、A2（策略／首頁狀態／策略與分點勝率口徑對照，後續已完成 code-level contract）以及 B 公司地址／股務代理、C 題材 freshness、D 集團 mapping、E1 庫藏股 KB1、E2 關鍵分點與地緣 point-in-time shadow 的分期、契約、UI、測試與風險。**KB2 庫藏股執行分點不實作，E2 不做交易獲利歸因**；規劃本身未授權 schema／排程／正式資料異動或回算。
- 2026-08-27 **E1 庫藏股 KB1 code 完成**：MOPS `ajax_t35sc09` redirect→短效官方 HTML，以 stdlib parser 讀 20 欄；加性 `buybacks`、deterministic plan ID、手動 `import-buybacks --as-of --days`、雙市場 atomic fail-closed、`report_date/source_updated_at` point-in-time export、KB1 口袋 15 分與個股 compact 事實區完成。fixture tests 覆蓋網路／redirect／表格／數值／狀態／zero-write／future leak；Luna High 最終 review **APPROVE**，完整 pipeline pytest **262 passed／58 subtests**、`npx tsc --noEmit`、乾淨快取 `npm run build`（12/12 static pages、2/2 export）均通過。**`import-buybacks` 未執行、未加排程；16:58 的 `export-json`／data Worker deploy 只發布既有快照，未更新庫藏股官方來源資料。未動 workflow/secrets，KB2 runtime code 已移除。**
- 2026-08-27 **Armed A1 匯出契約補強（程式／測試完成，未正式 DB 回算）**：state list IDs 保證可由 `radar.stocks` 解析；stale warrant 保留 payload／freshness／權證榜但不再作今日 state source；任一 1 日或 5 日漲幅缺值時 state fail closed（含 T2、風險、失效價）。未改榜單門檻或排序、分數／schema／正式資料。
- 2026-08-27 **S4 V2 兩階段（程式／測試完成，未正式資料回算或上線）**：舊 `S4_VOLATILITY_CONTRACTION` 凍結為 legacy；新增 `S4_COMPRESSION_SETUP_V2`（adjusted OHLC 的壓縮蓄勢）與 `S4_COMPRESSION_BREAKOUT_V2`（前 1–5 日 setup 後的首次帶量突破）。兩者只作 strategy tag／S4 內排序，不改 `tech_score`、`final`、全域 Armed/Triggered 或 schema。`strategies.S4_VOLATILITY_CONTRACTION` 保留三者聯集；新增 additive `strategy_phases` 與每股 `strategy_signals`，首頁標示「壓縮蓄勢／壓縮突破」（突破優先）並各自讀其 strategy_meta（legacy 亦獨立）。setup 連續日依完整 `daily_prices` 交易日曆按 episode 去重；程式碼驗收完成；正式資料尚未重算，需另次人工確認。
- 2026-08-27 **勝率統計唯讀稽核**：盤點策略／分點事件、成熟樣本、entry／forward／win、export／UI 與文件定義；未改排名、未改 schema，未執行正式 DB 回算。
- 2026-08-27 **Codex Multi-Agent V2 執行偏好**：Sol high 負責整體架構／複雜判斷／跨模組決策；Terra high 負責一般功能實作、跨端整合與驗收；Luna 負責搜尋分析、簡單修改、測試／lint／typecheck、文件與重複性工作，最終 Code Review 固定 high。此為目前預設偏好，不取代 Cursor Grok/Auto 常駐流程與角色模型中立原則，使用者可當次覆寫。
- 2026-08-27 **融資主輪改 21:20**：TWSE ~21:00 產製,不必等到 22:40;分點第二輪改 **22:00** 避 lock。
- 2026-08-27 **融資未更新修復**：根因＝`git pull` 後腳本丟 +x → 22:10 `daily-margin` **Permission denied**（21:00 branches 同掛）；另 17:40 抓 MI_MARGN 過早必 empty。已：`sync_code` 強制 `chmod +x`、crontab 改 `bash` 呼叫、branches 不再抓 margin、腳本 git mode 100755。
- 2026-08-26 **交接**：`handoff.md` 已寫完整 Handoff＋下一對話可貼提示詞；本機／VPS 皆在 `a81860c`。
- 2026-08-26 **Phase D1/D2 董監＋內部人％**：`import-directors`（TWSE/TPEx OpenAPI）、`director_holdings`、HoldersPanel「董監持股」分頁；週表 `insider_pct` ffill。VPS `monthly-directors.sh` 已掛正式 crontab（每月 16 日 07:00）；2026-08-26 已成功匯入 2026-07 月資料，下一次正式 cron 為 2026-09-16。
- 2026-08-26 **內部人％公式修正**：姓名去重＋（目前持股＋關係人合計）÷集保；對齊籌碼／元大（2476≈12.09；舊式~10.48）。
- 2026-08-26 **ntfy 改繁中成功摘要**：日更結束發「三大法人 · 成功」「分點籌碼 · 成功」等；失敗／略過／注意同標題格式（VPS 已 pull）。
- 2026-08-26 **上櫃 15:00 主補抓槽**：新增 `daily-tpex-quotes.sh`（quotes→指標→分數→export）；**VPS crontab 已掛**平日 15:00；安靜窗 14:05–15:45。14:10 上市閃電不變；16:10／17:40／22:00 仍保底再抓。
- 2026-08-26 **上櫃日K 14:10 常 empty**：上市已是當日、上櫃卡前一日（`tpex dailyQuotes: no populated table`）。根因＝抓太早＋無後續補抓。已手動補齊 08-24／25／26 上櫃全日K（先前 08-24／25 僅 ~367 檔半套，約 520 檔看起來停在 08-21）。
- 2026-08-26 **週表內部人％暫隱藏**：口徑仍難穩對齊；UI 拿掉欄位，保留「董監持股」明細分頁。
- 2026-08-26 **TDCC archive 回補已上 VPS**：`backfill-tdcc` 灌入 16 週（2026-04-30～08-14；08-21 已有略過）+ export/deploy 完成（`~/tdcc-archive-backfill.done`）。
- 2026-08-26 **TDCC archive 回補 CLI**：`radar backfill-tdcc --from 2026-04-01`（wirelessr 週快照；官方無歷史）；`vps/scripts/backfill-tdcc.sh`。
- 2026-08-26 **大戶表 UI**：個股 tab 表改為日期｜大戶持股｜增減｜散戶｜內部人；紅漲綠跌＋+/-（`HoldersPanel`）；export 補 `retail_pct`（下次 export 後散戶有值；內部人暫 —）。
- 2026-08-26 **`docs/sql` migration 命名統一**：`YYYYMMDDHHMMSS_描述.sql`；見 `docs/sql/README.md`。既有 7 檔已改名並更新 STATUS／36／21／worker 引用。
- 2026-08-26 **docs/35 S2 程式落地＋VPS 已掛**：`bf-supervisor`（單寫者／自啟／ntfy）、`safe-branch-stats`＋scores、安靜窗收進 `lib.sh`；**TDCC B1/B2**（`import-tdcc`、個股「大戶」tab、`weekly-tdcc.sh` @ 週六 06:30）。**VPS**：crontab 已掛 supervisor／tdcc；`BF_ORDER=warrant,branches`（先權證）；`disk-cleanup.sh` 每日 07:40（首跑 +2G free）。`backfill-branches top=0` 已修（`7b2c003`）。
- 2026-08-27 **正式 VPS 回補／安靜窗實況驗證**：16:57 實測 repo HEAD 為 `2b0de0c`、tracked files 乾淨；正式 crontab 已含 TDCC 週六 06:30 與董監每月 16 日 07:00。權證回補已完成：`bf-warrant.done=2026-08-27T00:25:33+08:00`，`warrant_branch_hist` 12,644 rows／status ok。歷史分點尚未完成：最後完成 2025-10-29、累計 fetched 23,156；490 個目標交易日已走訪約 201 日（41%），餘約 289 日；此為日期走訪進度而非 completeness，舊日期缺口較大，不可線性推 ETA，未見 traceback／too-many-failures／stopped。`radar.db` 約 4.3G、WAL 約 91M，磁碟餘 7.9G（71%）；因有活躍寫者未跑 integrity check。14:10 TPEx empty、15:00 補抓 10,629 筆成功，15:05 scores 751 檔／24 檔達 65，export/deploy 成功。已清除兩個殘留診斷 shell，安全重啟 guard/supervisor；分點容器於 14:05–15:45 為 paused，15:46:05 自動 unpause，15:46:11 實測 `running|paused=false`，無 duplicate／restart。16:58 已完成 data Worker deploy；該 16:58 歷史事件當時未做程式碼部署、migration 或全市場重算；17:34 已完成正式 Pages code deploy 與策略 metadata 原子發布。
- 2026-08-26 **修字級／深淺色選單無反應**：頭像選單改原生 button；`userPrefs` 只依 `userId` 重拉並擋住進行中 refresh 蓋寫本機切換。
- 2026-08-26 **搜尋歷史＋文字縮放**：每位登入使用者搜尋紀錄（可清除）與 Header「A」三档字級綁帳號（`docs/36`）。**Supabase `20260826114421_create_user_ui_prefs.sql` 已執行**。
- 2026-08-26 **VPS 四層排程架構定案（歷史規劃節點）**：[`docs/35_vps_schedule_architecture.md`](35_vps_schedule_architecture.md)——當時只完成文件；其後 S2、TDCC 與正式 crontab 已落地，現況由 2026-08-31 頂部稽核與 `docs/35` 覆寫。
- 2026-08-26 **分點每日全股票**：`import-branch-trades --top 0`（當日有報價 type=stock，不含 ETF）；法人／資券本已是全市場單請求。大戶比率＝TDCC 週更，Phase B 待實作。
- 2026-08-26 **倉和卡 8/24**：DB 已有 8/25，個股 JSON 未重匯；觸發 force export。
- 2026-08-25 **WP-M1 個股 JSON 全市場**:`export-json` 改寫全部 active stock/etf(不綁評分池);今日無報價仍更新最新 K 線,修倉和類卡在舊日。
- 2026-08-25 **資券 Phase A4 實作**：`backfill-margin`、display 窗、`margin_meta`、MarginPanel；VPS `backfill-margin.sh` 排程 23:15 首跑。
- 2026-08-25 **融資排行表欄位**：限額／已用／較前日使用率；export `usage_chg`。
- 2026-08-25 **資券 Phase A 實作**:`docs/34` A0–A3——`daily_margins` 買進/賣出/現償、融資成本估算、`margin_history` export、`/margin` 排行、個股資券 tab；VPS 已 mid-publish。
- 2026-08-25 **S1.1 OOM 修復**:夜間含 stats 兩次被 OOM;改 mid 預設略過 stats、新增 `safe-branch-stats.sh`@23:30、`compute_branch_stats` 增量累加降記憶體。詳 `docs/33`。
- 2026-08-24 **回補中途動態上線規劃**:`docs/33_mid_backfill_publish_plan.md`——長回補期間定時 pause→stats→export/deploy→resume，不必等全部跑完才更新網站。
- 2026-08-21 **個股權證分頁＝權證分點動向**：原與 `/branch` 同源 `warrant_branches.json`、門檻 ≥500 萬；2026-08-28 已由上方雙 JSON 契約取代，個股 detail 降至 100 萬、全市場仍維持 500 萬。
- 2026-08-21 **VPS 先上線再回補**:回補 pause 期間跑完 `import-geo` + `compute-branch-stats` + export/deploy(不握長 flock);正式 `data_date=2026-08-21`、`branch_rankings` as_of=08-20、pocket 有資料。16:10 `daily-insti` 正常搶鎖。歷史回補容器仍由 `bf-cron-guard` 在 cron 窗 pause。
- 2026-08-21 **VPS 恢復歷史回補**:重開 `radar-bf-branches`(`--top 2500 --days 730`)與 `radar-bf-warrant`(`--top 6000 --days 130`),**不拿** `/tmp/radar-db.lock`;`~/bf-cron-guard.sh` 在 daily-* 窗或 flock 被佔時 `docker pause`,避免再擋今日排程。進度:`docker logs -f radar-bf-*`;跑完再 stats/export/`import-geo`。
- 2026-08-25 **籌碼日報深度顯示**：個股「分點進出」依**該檔** `branch_history` 顯示涵蓋區間；超過回補天數的 120/240/2年等選項 disabled，並自動降到可用深度。
- 2026-08-25 **監控 I-1／試搓**:大單改日均額 0.4% 分級(80萬–500萬);08:30–09:00 試搓不計訊號;UI 隱藏試搓歷史;修正 watch_price／adv20 讀取。
- 2026-08-25 **監控訊號 UX**：列表強制新→舊排序；今日顯示時分秒、跨日顯示日期；UI 隱藏 `00*` ETF（含元大台灣50／歷史訊號）；worker `is_etf_id` 與 classify 對齊。
- 2026-08-21 **盤中監控 UX**：導覽「首頁｜監控｜…」；首頁拿掉嵌入面板；I-1～I-4 兩欄標籤色；大單金額改億／千萬／百萬；額度 n/5；排除 00 開頭 ETF。需在 Supabase 執行 `docs/sql/20260821145158_add_worker_heartbeat_monitor_cap.sql`。
- 2026-08-21 **盤中雷達 UX**：`/intraday` 導覽頁；I-1～I-4 人話標籤；Realtime；worker 併自選。
- 2026-08-21 **VPS 資料凍結搶修**:根因=VPS 本地 dirty `vps/scripts` 擋 `git pull`,cron 全日無 export。已停回補、pull 最新、補抓 2026-08-20 並 deploy;稍後 catchup 後正式 `data_date=2026-08-21`(法人/融資/分點 freshness 仍可能 lag 至當日稍晚 cron)。盤中 worker 重建後上線。`lib.sh` 加 `core.filemode false` + pull 失敗 reset scripts 重試。
- 2026-08-20 **三包非 VPS**:①個股掃讀微優化(訊號摘要可收合、sticky tab、法人空態縮短);②docs/22 A4 Extended/Faded(export+首頁「追高風險」「失效」+徽章;等 VPS export);③docs/20 Phase 4 提案稿改寫(對齊 VPS cron,未改 cron)。
- 2026-08-20 **IA-5b**：個股加「法人」「技術」tab；K 線 tab 只留圖並放大手機高度；買方/賣方改全寬對半切（籌碼日報＋分點追蹤）。
- 2026-08-20 **IA-5 + IA-3b 籌碼分層**：個股頁 `K線 | 籌碼日報 | 權證`；籌碼日報買超/賣超分頁；點分點下鑽進出+對應 K 線（`.safe-overlay`）。分點追蹤頁同樣改買超/賣超分頁，不再兩表往下滑。`#branch` 開籌碼日報。未改評分/JSON/配色。
- 2026-08-20 **PWA 完善 + 品牌 PNG**:192/512 + maskable PNG(由 `trever-radar-mark.svg` 匯出,未重畫 Logo)、favicon 16/32、Apple Touch 180、`sw.js` 只 cache app shell(不碰 `/data`/JWT)、Android 安裝提示、iOS 加入主畫面說明、更新 toast、離線誠實橫幅、Header/BottomNav safe-area、登入頁改用正式 mark。manifest 仍為 `web/app/manifest.ts`。
- 2026-08-20 **品牌 + PWA 身分**(commit `e3cefcd`):Header 改 TR Radar mark(`web/public/icons/trever-radar-mark.svg`)+ `web/app/manifest.ts` + Apple Web App metadata。方向=TR Monogram + Radar + 隱性 Wheel;主色 `#0D0D0D` / `#3987E5` / `#35B5C9` / `#8FD6FF`。**勿重做 Logo、勿改回舊綠 Design System。**
- 2026-08-20 **docs/27 G4 口袋名單 UI**:首頁「口袋」tab、卡片/個股頁 reason badges、`/branch` 關鍵分點徽章;不進綜合分、零新色票。
- 2026-08-20 **VPS:`import-geo` 等回補結束**:分點+權證分點兩筆回補還在跑,不要手動 import-geo(搶寫鎖)。回補完再跑,或等下週一 14:10。落檔 `docs/27`、`vps/README.md`、handoff。
- 2026-08-20 **docs/27 G2 地緣/關鍵/題材 tag**:export `pocket_tags`+`lists.pocket`(≥2 family 才入榜),不進綜合分、不做口袋 tab。GEO 要等 `import-geo`;KEY/THEME 下一次 `export-json` 即可。
- 2026-08-20 **docs/27 G1 地緣資料層**:`company_profiles` + `broker_branch_geo`;`python -m radar import-geo`;週一 14:10 更新。庫藏股無 OpenAPI,buybacks 延後。不進綜合分。
- 2026-08-20 **WP-H3 卡片當日分時**:export-json 用 `FUGLE_API_KEY` 抓 Fugle 當日 1 分 K,降採樣寫 `spark_day`/`spark_open`;同日快取 `data/spark_day.json`;前端相對開盤+平盤虛線,缺資料退回 30 日線。
- 2026-08-20 **Fugle 金鑰命名定案**:WP-H3 沿用盤中既有 `FUGLE_API_KEY`(VPS `pipeline/intraday/.env`),不另開 `RADAR_FUGLE_TOKEN`、不進 GitHub Actions secret。
- 2026-08-20 **使用者核准入口整合**:管理員「使用者核准」只留右上帳號選單,不再出現在桌機頂部導覽。
- 2026-08-20 **WP-H1 首頁題材分組**:綜合/市場掃描加「分數|題材」切換;桌機與分數榜同一套 2/3/4 欄卡片牆(組標題 col-span-full,預設全開),手機仍前 3 組展開。
- 2026-08-20 **WP-B7 Access 關閉並驗收**:裸 curl `/data/radar.json` 直接 401;使用者確認無痕開站為站內 Google 登入、管理員登入後資料正常。門禁只剩站內登入 + Worker JWT/`RADAR_SERVICE_KEY`。
- 2026-08-19 **WP-B7 Worker JWT**:`/data` Worker 驗 Bearer JWT + `app_profiles.approved`,或 `X-Radar-Service-Key`;前端 `dataFetch` 帶 token;盤中 worker 改帶 service key。
- 2026-08-19 **WP-B7 前端核准閘門**:全頁 Google 登入、`docs/sql/20260819171000_create_app_profiles.sql`、`/admin` 核准頁;既有 auth.users 回填已核准,`a7033140327k@gmail.com` 為管理員。
- 2026-08-19 **手機版 UI 修正（多頁）**：個股頁 KChart 工具列拆兩列（Row1 固定：時間框架/副圖/主力分點；Row2 均線 wrap）；分點進出區摘要 card 對稱排列、時間範圍 wrap 全顯；分點頁統計列改 2×2 grid、標籤文字更清楚、資料起始日截斷修正。commits `b00916a`/`01b6c01`/`57f97a7`/`450f284`。
- 2026-08-19 **Cursor 協作常駐指令 + Phase 2 文件同步**:使用者定案 Workflow D——規劃用 Grok 4.6 High、執行用 Auto agent,完成功能/修正後自動更新 md 並 commit/push(高風險項除外);落檔 `AGENTS.md`、`docs/17`/`18`/`24`、`docs/project-context.md`。同日 Phase 2 差異報告 CLI(`phase2-diff-report`)與本機樣本報告文件同步(`docs/20`、`STATUS` Phase 2 條目)。
- 2026-07-18 **WP-B5 文件大同步完成**:`docs/31` §9 退役清單逐項落文件——`AGENTS.md` 危險清單改寫(WAL checkpoint/cache-release 續存鏈/DB 1GB 上限三條退役,換上「VPS 單一寫者不得破壞」「備份前 checkpoint+integrity_check」「資料與部署權限分離」三條)、`docs/08_scheduler_jobs.md` §0 重寫為 VPS cron 表、`DEPLOY.md` 改為資料/部署分離架構說明、`docs/vps_backfill_plan.md` Step 4e 上傳流程標記作廢、`docs/STATUS.md`(本檔)、`docs/32_wp_b3_cutover_runbook.md` 狀態標頭改為已執行、`docs/31` §12 補執行紀錄。未動任何程式碼/workflow yaml。
- 2026-07-18 **WP-B3 cutover 執行完成(選在假日執行)+ 發現 Actions Billing 阻斷**:Step 1-5 全落地——`/data/*` Worker route 正式接管、`cloudflare-trigger` crons 清空、`deploy.yml` 精簡為純 build+deploy(commit `109c8ad`)、intraday `.env` 改讀自訂網域、**repo 轉 private**(使用者網頁操作)。Agent 端 Step 6 驗證:未登入 curl 三入口(custom domain `/data/radar.json`、首頁、pages.dev)全部 302 被 Access 擋(紅線通過);5 支資料 workflow 確認 07-17 後零觸發(Worker cron 停用生效);cutover commit 當下 deploy 成功(1m4s 純 build)。**遺留問題:repo 轉 private 後,GitHub Actions 被帳戶帳務設定擋下**——其後 3 次 push 的 deploy 全部 3 秒 instant-fail、零 step,官方 annotation:「The job was not started because recent account payments have failed or your spending limit needs to be increased」。影響僅限**程式碼部署**(main push 不會更新網站前端);**資料鏈不受影響**(資料走 VPS→Worker assets,照常更新)。**同晚解決:使用者判斷修 Billing 需綁付款方式、牴觸免綁卡原則(取捨 16),決定將 repo 改回 public(Step 5 反轉)**——改回後 deploy 立即恢復(1m7s 成功),未登入三入口紅線重驗仍 302(Access 在 Cloudflare 端,與 repo 可見性無關)。GitHub 自 WP-B1 起零資料,合規紅線不受影響;殘餘暴露面 = repo 內文件(如 docs/30 的 ntfy 主題名)公開可見,屬既有狀態非新增。其餘 Step 6 項目(登入後 freshness/全站功能、VPS cron log、盤中 worker 隔日 online)待使用者確認;全過後回滾窗兩週倒數,接排 WP-B5 文件同步(`docs/08` §0、AGENTS.md 危險清單等)。
- 2026-07-18 **WP-B2 影子驗證驗收通過 + 盤中訊號雷達 Part A 全流程上線**:B 案影子驗證連續交易日(07-16/07-17)shadow 與正式站 freshness/榜單一致、ntfy 無 High 告警,**WP-B3 cutover 前置條件全滿足,執行手冊 `docs/32` 已備妥,待使用者敲定執行日**。盤中 worker 側:07-16 首次 VPS live smoke test 炸出 `fugle-marketdata` 套件 API 飄移(`connect()/subscribe()` 官方已改同步、WS callback 給原始 JSON 字串非 dict),當晚修復(commit `fcb3aef`,回歸測試 pytest 104 全過);07-18 確認已跟上盤中實跑、cron 常態化,首頁面板穩定 online。
- 2026-07-15 **WP-B0/B1 完成 + WP-B2 影子驗證起跑**(`docs/31` §12):WP-B0 全套人工+Executor 件完成(token/node/rclone gdrive/.env/docker 映像/首次 wrangler deploy,影子路由 `/data-preview/*` 兩測過);`vps/scripts/` 七支 + `manual-catchup.sh` 落地,crontab 七條已掛、ntfy 實測通;manual-catchup 一條龍完成(當日+近 6 日追補、全重算、990 檔資產 deploy)→ 首份 Drive 快照 `radar-20260715.db.gz`(integrity ok)→ **刪除 public release `radar.db.gz` asset,docs/10 §3 合規紅線解除**。雲端鏈 cache 單腿(已知風險),WP-B3 cutover 目標 ≤1 週;影子驗證第一發實彈 = 07-15 22:10 daily-margin。
- 2026-07-15 **docs/31 v3 改版:不採 R2(啟用需綁卡),資料層改 Workers 靜態資產、備份改 Google Drive 單雲**:使用者定案全方案不得使用需綁信用卡的服務;資料層 A 案(VPS `wrangler deploy` JSON 為 Worker assets,`/data/*` 路由,即傳即生效體感不變)取代 R2 bucket;備份 = VPS 本機 + Drive 兩份(單雲風險知情接受,§4 留 B2/MEGA 後路);`cloudflare-data-worker/` 改寫 assets 模式、`vps/.env.example` 憑證改 `CLOUDFLARE_API_TOKEN`(scope 限 Workers Scripts/Routes Edit);AGENTS/STATUS/project-context/handoff 同步;`docs/21` R0-R4 作廢。
- 2026-07-15 **資料架構 B 案定案並落檔 `docs/31`(v2 R2 資料層)+ WP-B0 Executor 件產出**:Planner(Fable 5)分析三根因(容量天花板/雙寫者同步/repo public 資料散布合規)後,使用者定案 radar.db 常駐 VPS 單一寫者;v1「VPS 輪詢 build+deploy」因部署延遲與管控面過大被使用者否決,v2 改「資料與部署解耦」——VPS 匯出 JSON 直傳 R2、`/data/*` 由 Cloudflare Worker 讀 R2 回應(快照放獨立 backup bucket 實體隔離)、GitHub push→deploy 維持現狀;明確不做 FastAPI/常駐 API;立項 WP-B7 登入統一(Supabase JWT+白名單,Access 驗證後退役,需資安審查);WP-M3 取消、docs/29 Phase 2 剩餘項作廢。同日完成 WP-B0 Executor 件:`cloudflare-data-worker/`(R2 代理 Worker+wrangler.toml+README)、`pipeline/Dockerfile`(依賴烤入映像)、`vps/.env.example`。
- 2026-07-14 `49c4a39` **分點進出標示籌碼日**(web):分點資料落後價格日時,明確標示所用籌碼日並警示暫用舊資料。
- 2026-07-13~14 **雲端 DB 瘦身 Phase 0-2 + VPS 分點歷史回灌**:`docs/29`(WP-M3R)落檔(`3df1976`)後實作 Phase 0/1(`980524d`)與 Phase 2 branch_dim 正規化(`3a72c8d`,同 commit 追加 WP-M4 全市場回補計畫);VPS 490 天分點歷史回補完成並回灌雲端,期間修掉 VPS 指令中 db download 會覆蓋 490 天歷史的風險(`7db809a`)、以還原後完整歷史 DB 觸發部署並 force deploy 清 cache(`5029ab5`→`fa464d3`);另新增 Actions `task=backfill-recent`/`backfill-branches-recent`/唯讀 `debug-query`(`fd1f002`/`9e4ffe0`/`0f0fd45`),補 07-10(五)缺漏交易日資料(`92a1e10`)。
- 2026-07-13 **Cloudflare Access 鎖站完成(docs/21 A0-A2)**:使用者手動於 Cloudflare Zero Trust 完成 Google IdP + email 白名單,單一 Access Application 覆蓋 `radar.techtrever.com` / `trever-radar.pages.dev` / `*.trever-radar.pages.dev`;執行紀錄寫入 `docs/21` §4 A3(commit `ff2b05f`)。
- 2026-07-14 **compute-branch-stats OOM 修復**(pipeline,已入 commit `4587c6f`;另新增 Actions `task=branch-stats` 讓 7GB RAM 雲端 runner 跑統計,commit `45787c4`):`compute_all()` 舊版一次把整張 `branch_trades`(回補後約 600 萬列)連同全部 500 檔完整價格序列載進記憶體,1–2GB RAM 的 VPS 被 OOM killer 殺掉(`51 Killed`)。改為**串流式逐檔處理**——先查 distinct stock_id,再逐檔載入單股價格 ctx + 該股 branch_trades 列(走 PK `(stock_id,…)` 前導,無需新索引),算完累加分點層事件池後即釋放。彙總/排行/auto in-out/落地全部不動,純函式不動,行為零變化;既有 28 項測試 + 全 106 項 pytest 全過。合成 1.2M 列(比生產密集)實測:舊版全表 fetchall Python 峰值 488MB(且舊版還在其上疊 stock_ctx+by_bs 兩份)→ 新版全程峰值 161.7MB(主要是跨檔事件池,單檔資料僅數 MB)。重跑指令見 `docs/vps_backfill_plan.md` 4c 後的 OOM 小節。
- 2026-07-14 **docs/28 WP-H4(個股頁分點統一)+ WP-H5(K 線圖/分點明細手機版)**(commits `83649ae`/`8b04b77`/`4587c6f`):H4 移除「分點」tab(收為 K線/權證),K 線下方 BranchFlowSection 升級為唯一分點區(標頭併分點分徽章+分點理由 pills,`#branch` 錨點捲動,BranchPanel 刪除);H5 手機(<768px,全 media/斷點 gated,桌機逐位元不變)子 pane 副圖/主力/分點三選一(獨立 localStorage、分點無勾選 disabled、總高 clamp(360,52vh,480)、stretch 使子 pane ≥120px)、`vertTouchDrag=false` 垂直手勢還頁面、游標值改上方 compact legend、工具 chips 單行橫滑+min-h-11、買賣超 segmented tabs+前8展開、勾選右下 fixed chip(z-30,點擊捲回 KChart)。修正前次 commit(83649ae/8b04b77)遺留的手機仍渲染 4 pane、桌機 chips 被改成單行不換行、主力 pane 綁 settings.mainForce 等缺陷。`web` `npm run build` 全過;未動 token/依賴/pipeline(僅 globals.css 加一個 `.scrollbar-hide` 工具 class)。
- 2026-07-07 `842b4e0 feat: add warrant radar UI`:首頁新增權證榜,股票卡/個股頁接上權證摘要、趨勢與熱門權證明細。
- 2026-07-07 `ed363b1 ci: deploy site on main push`:正式分支 push 會觸發 Cloudflare Pages 部署;已確認 GitHub Actions `nightly-radar` push run 成功。
- 2026-07-07 還原價資料層:新增 `daily_prices.adj_factor`、SQLite additive migration、`compute-adjustments` CLI、單元測試;2330 實測 6 筆除息事件/8031 日價列更新成功。
- 2026-07-07 技術指標資料層/UI:新增 `indicators_daily`、`compute-indicators`、技術分 reasons/risks、MA5/20/60 K 線疊線與個股頁技術摘要;本機 Top80 實算 18.5 萬列成功。
- 2026-07-08 訊號績效回填:新增 `daily_scores` entry/fwd 欄位、`compute-performance` CLI、單元測試與 nightly step;以次日還原開盤價進場、後續第 1/3/5/10/20 個交易日收盤回填報酬。
- 2026-07-08 分點籌碼分:新增 `daily_scores.branch_score`、`score_branch` 純函式與測試;綜合分權重改為分點35/權證20/技術20/法人15(題材10暫缺自動重分配),首頁卡片顯示分點分。
- 2026-07-08 分點 UI 補齊:個股 JSON 輸出 `branches/scores/reasons/risks`,個股頁新增分點 Tab 顯示分點分、理由、風險與前15大買賣超明細。
- 2026-07-08 題材分數接入:新增題材熱度評分純函數 `score_themes`、更新評分權重（加入題材 10% 權重）、個股頁/卡片 UI 整合與單元測試。
- 2026-07-08 籌碼日報:在個股頁分點 Tab 擴充籌碼日報功能，包含 1-240 日/自訂天數的前 13 大分點買賣超聚合計算，實作 Bento Grid 科技感 UI 與點擊展開的分點紅綠柱狀圖。
- 2026-07-08 分點排行與管線優化: 完成 `/branch` 頁面實作（含勝率排行與今日動向），並正式將 GitHub Actions 拆解為 `daily-market`、`daily-warrants`、`daily-branches` 三條獨立管線，同時新增了 `deploy` 管線負責 Push 時的即時部署。
- 2026-07-08 系統穩定度修正: 修正首頁動態榜單數量邏輯（無論行情好壞皆保底 15 檔，上限 40 檔避免過長）；修復 GitHub Actions 併發限制導致的管線互相取消問題，並將每日抓取管線 Timeout 時間全面延長至 30~40 分鐘。
- 2026-07-08 Mark策略演算法與獨立榜單: 新增「Mark策略」演算法（20日內漲停、5日內爆量、MACD零上金叉），於 `indicators.py` 中進行嚴格判定，並在前端首頁新增獨立的「Mark策略」頁籤。
- 2026-07-09 排程觸發改 Cloudflare Worker:實測發現 GitHub 原生 `schedule:` 延遲 2.5–3.5 小時,新增 `cloudflare-trigger/`(Cloudflare Worker,單一 10 分鐘 cron + 程式碼比對時間表)取代;4 支既有 workflow 拿掉 `schedule:`,新增 `daily-margin.yml`(22:10 台北融資券保底輪);修正隨手發現的 `daily-branches`/`data-backfill` 備份步驟隱性依賴 `event_name=='schedule'` 的 bug(原本手動觸發會意外覆蓋週備份);Worker 已部署並以 `gh run list` 驗證觸發成功;修補 Worker `fetch()` 端點原本無驗證可被任何人觸發 workflow 的漏洞,加上 token 驗證。
- 2026-07-11 個股頁 K 線下方分點進出:抽出共用元件 `web/components/BranchFlowSection.tsx`(時間範圍+N日淨流/家數摘要+前13大買/賣超兩欄列表,聚合邏輯自原 BranchPanel 原樣搬移),掛進 K 線視圖技術摘要之後(標題「分點進出」),分點 Tab 改引用同一元件——同一份邏輯兩處用;區塊自帶期間 state(預設 5 日)不與 K 線區間連動;`pillTabClass` 提到 `lib/utils.ts` 供兩處共用;`cd web; npm run build` 全過。
- 2026-07-10 觀察價/失效價 + 自選股 + 探索頁(集中度/題材):`daily_scores` 新增 `watch_price`/`stop_price`/`buy_concentration`/`concentration_avg20`(additive migration);純函式 `watch_stop_prices`/`buy_concentration` 各有單元測試,`buy_concentration` 從既有 B3 評分邏輯抽出重用;`export-json` 帶出至股票卡/個股頁/新的 `radar.json.concentration` 榜;前端新增 Supabase-backed 自選股(`web/lib/watchlist.tsx` Context + `WatchlistButton` + `/watchlist` 頁,需人工執行 `docs/sql/20260710002358_create_watchlist.sql` 建表)與 `/explore` 頁(集中度+題材 2 個 tab,地緣/關鍵分點/分點績效榜/權證異動因人工名單或與 `/branch` 重疊而暫緩);全專案 `npm run build`(含 static export)與 16 項 pytest 皆過。
- 2026-07-10 前端 UI 遷移 Tailwind CSS v4 + shadcn/ui(尚未 commit):分階段(header/nav/搜尋/auth → 首頁 → 個股頁 → branch/explore/watchlist → 清理舊 CSS)把全站手刻 CSS 換成 Tailwind utility + shadcn 元件,視覺目標是與遷移前逐頁比對不走樣(每階段皆截圖比對深色模式,並用本機 DB 產出的真實資料而非空狀態驗證);過程中發現並修掉兩個遷移期間才浮現的既有 bug——① 舊 `.grid` class 名稱與 Tailwind 內建 `grid`/`grid-cols-*` utility 直接碰撞,unlayered 規則蓋過 Tailwind 的 layered utility,導致多處 4 欄版面被壓成 3 欄且會換行,已刪除該舊規則;② shadcn `@theme inline` 的 `--color-border`/`--color-accent` 一度被誤指到 legacy brand token,深色模式因數值巧合沒發作,但淺色模式的邊框/hover 底色會全部跑掉,已修正並補上 body 背景色改用 shadcn token,讓淺色模式真正可用(站上切換 toggle 已於 2026-07-11 補上,見 docs/23 V3.1)。`npm run build` 全過,globals.css 從 912 行清到約 210 行。

- 2026-07-10 分點可信度排行榜(docs/13 §2b/§3a/§3b,commit `cae4fd1`):`compute_branch_stats.py` 由佔位邏輯改為真實統計——事件擷取(淨買超≥成交值1%、連續交易日合併、事件日=段首日)、重用 `forward_returns` 以還原價計前瞻報酬與 5 日勝率、隔日沖判定(次日回吐≥70% 比率≥60%)、可信度分數 0-100(勝率30/報酬25/買點分位15/規模10/近效20,級距為 V1 起始值待校準);`branch_rankings` 保留歷史快照(只刪同 as_of);`tracked_branches` 自動入選/移出(僅動 source='auto');export 只取最新快照且隔日沖獨立輸出;/branch 排行榜 tab 補樣本不足/來源徽章/隔日沖獨立區;新增 27 項單元測試(全套 44 過),verifier 種子 DB 實測 CONFIRMED。
- 2026-07-10 權證大戶追蹤 (Warrant Branch Tracker):於 export_json 實作跨權證彙總演算法，以標的股票為中心加總特定分點的多檔權證淨買賣額，支援 1D/2D/5D/30D 區間，並篩選出大於 500 萬台幣的大單。前端 `/branch` 頁面新增「權證大戶」Tab，透過 Bento Grid 卡片與 Pill Selector 呈現 UI/UX PRO MAX 質感。並且支援點擊卡片直接展開明細 (Accordion)，列出構成該大單的每一檔權證代號、名稱、屬性及金額佔比。（新增半年 120D 追蹤：排程範圍擴大至 Top 200 權證，並支援 120D 時間切換，用於追蹤大戶低檔佈局尚未出清之籌碼。）（新增視角切換功能：支援「依標的檢視」與「依分點檢視」雙模式，將相同標的或分點的卡片進行聚合，減少畫面散亂，大幅提升追蹤主力的效率。）**（導入 UI/UX PRO MAX 視覺升級：卡片漸層與立體陰影、懸浮式手風琴子卡片 (Nested Cards)、紅綠邊框指示條、以及 Apple 風格立體切換器，徹底跳脫傳統表格框架。）**
- 2026-07-10 資金流向面板改善與 UI 規範文件化(commit `a221995`,verifier CONFIRMED):①修條圖蓋字 bug——每列改「名稱|條軌|數值區」三欄 grid,條以 scaleX 在自己的 overflow-hidden 條軌內縮放,結構上不可能再壓到金額文字;②流入欄移到左邊(DOM 順序=視覺順序,移除 order hack);③產業下鑽子題材——export 為每產業輸出 `sectors[].subs`(成分 ≥2 檔題材、排除同產業名、金額前 10、每 sub 帶前 5 成分股),前端點產業先列子題材(如 BBU、被動元件)再展成分股,保留全部成分股入口;新增種子 DB 測試 `test_json_export.py`;④新增 `docs/19_ui_guidelines.md`(專案 UI/UX 規範,ui-ux-pro-max 對照),`AGENTS.md` 動前端必讀行同步更新——**日後改前端頁面先讀 docs/19 + docs/07**。
- 2026-07-10 13 項選股策略與獨立榜單重構:`indicators.py` 及 `scores.py` 實作涵蓋技術與籌碼（如「漲停二次發動」、「法人連買突破」、「均線糾結突破」等）共 13 種量化策略；前端首頁「策略」頁籤內，新增了可動態切換 13 種不同策略條件的選單，並移除個別策略按鈕上的雜訊數字，介面大幅升級。
- 2026-07-10 S1 雙軌還原 + mark 死碼移除:S1「漲停二次發動」還原舊版嚴謹/放寬雙軌(嚴謹 `S1_REBOUND` 20 分,elif 放寬 `S1_REBOUND_RELAXED` 15 分;放寬=20日內漲7%+5日量1.5倍+任意金叉),兩代碼同入 `strategies.S1_REBOUND` 榜、嚴謹排前,解決嚴謹單軌常態 0 檔;同時移除已無消費者的舊 T6 mark 榜死碼(`json_export.py` 的 mark 掃描/`lists.mark` 輸出、`web/lib/types.ts` ListKey 的 mark)並補 S1 單元測試;另把「策略邏輯改動需等增量/週六全重算才生效」文件化於上方已知債務。
- 2026-07-10 Armed 追蹤規劃落檔(`docs/22`):確認下一產品方向為狀態池(Quiet→Armed→Triggered→Extended→Faded),首頁「未發動/已發動」、重用 S12/W3/B3,不新增策略/不抬綜合分;程式未實作,排在 Access + B Phase 1–3 之後。
- 2026-07-10 功能·視覺 backlog 落檔(`docs/23`):ui-ux-pro-max 對齊後寫入 V1–V3 / F1–F4 與 WP-* Executor 工作包;拒絕新配色與 Inter 全站字體;程式未實作。
- 2026-07-10 B 方案 Phase 1 (UI 刪減與合併):集中度併入 `/branch` 今日動向、題材只留首頁、移除 `/explore` 與空殼盤中導航、權證大戶降級為「權證分點異動(實驗)」、移除未使用依賴 `recharts`。
- 2026-07-11 WP-V2 榜單/表格一致性(docs/23 §2 V2,只動 UI 不動資料語意):①權證明細標竿表補排序回饋——表頭可排序欄改鍵盤可聚焦 `<button>` + `aria-sort=ascending/descending`,選中欄加 inset ring + 亮字選中態;②`/branch` 集中度榜與「今日買超」兩個 div-grid 真表格遷成語意化 `<table>/<thead>/<tbody>`(對齊權證表字級/分隔線,`overflow-x-auto` 手機可橫滑,不裁代號/漲跌,淨額補 +/- 號),分點前13大買賣超與權證大戶群組維持卡片列不硬遷;③首頁 stale freshness 標示改琥珀徽章 + lucide `Clock`(用既有 `--warn` token,不新增色票)。無新增依賴,`npm run build` 過。
- 2026-07-11 個股頁多層圖:復刻籌碼K線版面——KChart 新增「主力買賣超(前15大)」pane(branch_history 每日全分點 net 加總柱 + 累計線,工具列可開關並記憶於既有 settings localStorage)與勾選驅動的「分點進出」pane(BranchFlowSection 前13大買/賣列表加 checkbox,上限 10,勾選集合每日 net 加總 + 累計線,無勾選不渲染);單 chart 實例 X 軸全 pane 同步,D/W/M 用新 `periodKey` 對齊 K 棒桶重取樣,pane 標題與游標當日/累計數值(帶正負號)以 v5 `createTextWatermark` 畫在對應 pane;無 branch_history 時兩 pane 不渲染、高度回原本。`npm run build` 過,以正式站 2330 真實資料 headless 驗證柱/累計數字與來源吻合。
- 2026-07-12 **docs/25 IA-1B (首頁榜單收斂) 與 IA-3 (分點研究 Master-Detail 整合) 實作**（commit `df02e6e`）：
  - **IA-1B 首頁榜單收斂（歷史實作紀錄）**：曾將 7 個一級 Tab 壓縮為 4 個，將「熱門/爆量/強勢/弱勢」收進「市場掃描」；現況已由本檔頂部 `8603f3a` 的 10 個一級 tabs 覆寫。
  - **IA-3 分點研究 Master-Detail 整合**：改寫 `branch/page.tsx`。桌機版在排行榜採用 `grid-cols-[380px_1fr]` 雙欄佈局（左欄過濾名單可獨立滾動並顯示 active focus-ring，右欄即時加載 `BranchTrackView` 或無 track 資料提示）；手機版保留單欄列表並覆蓋下鑽，帶有 ArrowLeft 安全返回，徹底移除了原本獨立的「追蹤視角」模式按鈕。
  - **BranchTrackView.tsx 改造**：支援 `hideBack` prop，在桌機詳情面板上隱藏返回鍵。
- 2026-07-12 **docs/23 F 系列 + docs/25 IA Phase A-F 完整實作**（commit `8d4aee5`，11 files, +597/-138）：
  - **IA-1A 首頁 Pilot**：Compact Brief 壓縮為水平 compact row；Primary Queue（榜單+股票卡）提前至 MoneyFlow 前；MoneyFlow 改可展開/收合（預設收合）；新增 `DesktopNav.tsx` client component（usePathname active state）；桌機導覽標題改為任務導向命名（今日雷達/分點研究/自選追蹤）。
  - **IA-4A + F1.1/F1.2 自選追蹤**：完整重寫 `watchlist/page.tsx`；純前端計算距觀察/失效價%（不動 pipeline）；5 種排序選項（接近失效/觀察/風險/漲跌/加入順序）；分組顯示「需要注意」vs「一般追蹤」；教育性空狀態 + 骨架屏。
  - **IA-2 + F3 個股判讀**：`stock/page.tsx` 加入 `StockDecisionHeader` 元件（reasons ≤3、risks ≤2、觀察/失效價+距離%、來源徽章 分點/權證/both）；接近失效價時紅色警示。
  - **IA-3 分點研究**：`branch/page.tsx` 加入 Page Brief（入榜/樣本足夠/可追蹤/資料起始 4 格）；Filter UI（分點名搜尋、可追蹤、樣本足夠、排除隔日沖）；排行榜改用 filteredMain/filteredDaytrade。
  - **F2 日報摘要**：`json_export.py` 新增 `_build_summary_text()`（規則模板≤3句，無 LLM）；`types.ts` 加 `summary_text?: string[]`；首頁 stale alert 後顯示摘要區塊。
  - **V3.3 Sonner**：`npm install sonner`；`layout.tsx` 掛 `<Toaster position="bottom-center" richColors />`；`WatchlistButton.tsx` 加入/移除觸發 `toast.success/info`。
  - build 兩次均通過（`npm run build`），0 errors；push main → Cloudflare Pages 自動部署。
- 2026-07-12 **docs/23 F4.2 策略四類分群 + F1.3 一鍵加入今日 Armed（純前端，commit `0d70e8a`）**：
  - **F4.2 策略四類分群**（`web/app/page.tsx`）：13 策略 pills 依 `docs/20` §4.1 改為「籌碼事件(S11-13)/突破發動(S2-4,6-8)/趨勢續強·回踩(S1,5,9)/低檔反轉(S10)」四組；每組標題含總檔數 badge + lucide `ChevronDown`（`aria-expanded`、`-rotate-90` 收合，transition-transform 200ms）；預設只展開籌碼事件（`expandedGroups` Set，session 內不持久化）；選中策略落在收合組時「有效展開」自動含入（`expandedGroups.has || codes.includes(strategy)`）；預設選中改籌碼事件組第一個有檔數者（皆無則 S11，radar 載入後 `useRef` 套一次不覆寫使用者選擇）；pill 樣式與 count 沿用既有；未改任何 S code 語意。
  - **F1.3 一鍵加入今日 Armed**（`web/app/watchlist/page.tsx`）：新增 `AddTodayArmedButton` 自足元件（fetch `/data/radar.json` 取 `lists.armed`）；置於三種頁面狀態頂部動作區（未登入 / 空自選 / 主檢視）；N = armed 中尚未在自選者，只加不減（pending 先排除已在自選者，逐檔 `toggle` 新增、失敗不中斷）；完成 Sonner `toast.success`「已加入 X 檔」/`toast.warning`「已加入 X 檔；失敗 Y 檔」；未登入(登入後可用)/今日無 Armed/pending=0 三態 disabled，執行中 `aria-busy`+loading disabled；`lists.armed` 空防禦；不自動同步。
  - `cd web; npm run build` 全過（0 errors）；13 策略與 STRATEGIES 常數逐一比對無缺漏/重複。
- 2026-07-12 **淺色對比補強 + 盤中面板顯示放寬（純前端，commit `331af88`）**：
  - **A 淺色 token 對比**（`web/app/globals.css`）：被當文字色用、原僅 `:root` 定義深色調值的 brand-extension token 改雙主題定義——`.dark` 補回原深色值(逐位元不變)、`:root` 給淺色可讀值：`--ink-2` #c3c2b7→#5f5e52(對白 1.79→6.54)、`--warn` #fab219→#8a5a00(1.83→5.93)、`--accent-2` #35b5c9→#0e7c8c(2.44→4.91)、`--legacy-accent` #3987e5→#2f6fc4(連結/focus,3.64→5.01)；`--up`/`--down` 刻意不動。（另記:非文字的 `--border-strong` rgba(255,255,255,.16) 與 `--line` #2c2c2a 於淺色偏弱,屬邊框類非本次文字對比範圍,留待後續。）
  - **A KChart 淺色主題**（`web/components/KChart.tsx`）：抽 `chartColors(isDark)`(dark=遷移前寫死值逐字不變、light=grid #e6e5e0／文字 #6b6a64／軸 #d8d7d2)；`MutationObserver` 監聽 `<html>` class,主題切換以 `applyOptions` 就地更新 grid/軸/水印色(不重建,不閃爍),水印動態值由 `paneTextRef` 即時跟色；K 棒紅綠/均線/量色不變。
  - **B 盤中面板顯示邏輯**（`web/components/IntradayPanel.tsx`）：移除非盤中隱藏,面板永遠渲染；未登入顯示登入提示外殼；登入後空狀態分「非交易時段(worker 平日 08:50 啟動)」與「交易時段 worker 離線/尚無訊號」；頂欄徽章非交易時段顯示中性「非交易時段」(不用紅色 offline);無訊號時單行精簡不留空白。
  - `cd web; npm run build` 全過（0 errors）；未新增依賴、未動 pipeline；深色 diff 中 `.dark` 值 = 原 `:root` 值逐字相同。

| Pipeline Module (CLI) | 實作的系統功能 |
|---|---|
| `import-daily` | 每日市場收盤價 (`quotes`)、三大法人買賣超 (`insti`)、融資融券餘額 (`margin`) |
| `import-warrant-master` | 每日發行的權證主檔更新，用於配對標的與到期日 |
| `aggregate-warrants` | 每日計算個股認購/認售權證的總成交金額與量比，輸出至首頁權證榜 |
| `import-branch-trades` | 每日下午抓取盤後分點前 15 大進出明細，支撐籌碼日報與分點評分 |
| `import-themes` | 每日/每週抓取概念股與產業題材分類，用於首頁熱力圖與題材分 |
| `compute-indicators` | 計算還原價 MA5/10/20/60、RSI、MACD、乖離率等技術指標 |
| `compute-scores` | 綜合評分引擎 (分點35/權證20/技術20/法人15/題材10)，產生分數與理由/風險 JSON |
| `export-json` | 根據動態閾值產生各類排行榜單 (hot, surge, strong, warrant, weak)，單檔明細，以及分點/權證大戶動向追蹤 |
