# AGENTS.md — Trever Radar 多 AI 協作總規則

> 本檔是所有 AI agent(Claude Code / AGY / Codex / Cursor)進本專案前必讀的第一份文件。
> 完整流程細節在 `docs/17_no_fable_workflow.md`,本檔只放精簡規則與危險清單,避免三份文件角色定義互相漂移。

## Project Principle

1. 本專案由**多個 AI 工具接力開發**,不依賴任何單一高階模型(包含 Claude Fable)長期在場。
2. **一次只能有一個 agent 修改檔案**。開工前確認沒有其他 agent 正在改同一批檔案。
3. **文件是共同記憶**。對話歷史會遺失,`docs/` 不會——任何架構決策、取捨、已知債務都要寫進文件,不能只留在對話裡。
4. **人類使用者是最終決策者**。任何架構變更、正式部署、資料刪除/重建、高風險 migration,agent 只能提案,不能自行拍板執行。
5. Agent 不得自行 `merge`、不得自行觸發正式部署、不得改動正式環境(Cloudflare/GitHub secrets/DNS 等)。

## 文件現況表(本專案專屬,務必先讀)

| 文件 | 狀態 | 說明 |
|---|---|---|
| `docs/06_architecture.md` | 🗑️ **已刪除(2026-07-09)** | 原整份寫 Laravel+Inertia+Vue+PostgreSQL+VM+Docker Compose,與現行架構完全無關且危險,已刪除。現行架構見 `12`;需要舊內容可查 git 歷史。 |
| `docs/05_database_schema.md` | ⚠️ **標題過時,內容部分適用** | 標題寫「PostgreSQL 16」,實際是 SQLite(見 `pipeline/radar/schema.py`)。表設計概念(分點裁剪策略、欄位規劃)仍可參考,但語法/引擎描述以程式碼為準。 |
| `docs/02_mvp_scope.md` | ⚠️ **登入段過時** | 寫「登入(Laravel Breeze)」,實際是 Cloudflare Access / Supabase Google OAuth(見 `12`、`14`§4)。其餘範圍界定仍適用。 |
| `docs/11_ai_dev_workflow.md` | ❌ **superseded** | 全文 PHP 內容(`Modules/Scoring/*.php`、`php artisan`、pint/phpstan/phpunit、trunk-based+PR)為舊方案且**從未被實際執行**(實際是直接 push `main`)。已改寫為指向本檔與 `docs/17`/`docs/18`,技術棧對照改為 Python。 |
| `docs/08_scheduler_jobs.md` §0 | ✅ **current** | 排程總表,與 `.github/workflows/*.yml` 實際內容一致,是排程的唯一真相。 |
| `docs/08_scheduler_jobs.md` §1 | 🗑️ **已刪除(2026-07-09)** | 原 Laravel job chain 格式舊排程稿,與 §0 矛盾且從未實作,已刪除。§2(盤中管線)/§3(每週每月)為 V2 尚未實作的設計參考,保留。 |
| `docs/00_blueprint.md` | ⚠️ **表格欄位過時** | 頂部有 2026-07-06 修訂註記,但「架構」欄仍寫 Laravel/PG16/VM,讀表格本身會誤導。 |
| `docs/12_zero_cost_pivot.md` | ✅ **current** | 現行零成本架構(Python+SQLite+Next.js+GitHub Actions+Cloudflare Pages)的定案文件。 |
| `docs/project-context.md` | ✅ **current,衝突以此為準** | AI 開發每次必讀,150 行內,含「不要翻案」取捨清單。**排程時間行例外**:已知過時(見下)。 |
| `docs/STATUS.md` | ✅ **current,衝突以此為準** | 單一進度真相。**上線資訊表的排程行例外**:已知過時,寫「三條管線 15:30/16:30/18:30」,實際是 5 支 workflow(14:10/16:10/17:40+21:00/01:10+push-deploy),以 `08§0` 與 `.github/workflows/*.yml` 為準。 |
| `docs/vps_backfill_plan.md` | ✅ **current,分點來源以此為準** | 分點資料來源鏡像清單(5 站)最新版;`03`/`04`/`09`/`13` 提到分點來源時仍只寫單一來源,過時但不影響其評分規則邏輯本身。 |
| `docs/03/04/09/13` | ⚠️ **規則邏輯 current,資料來源段落過時** | 評分公式、資料表規格、頁面規格仍是設計藍圖依據;資料來源描述以 `vps_backfill_plan.md` 為準。 |
| `docs/17_no_fable_workflow.md` | ✅ **current** | No-Fable 工作流程完整版,見下方 Required Reading。 |
| `docs/18_handoff_template.md` | ✅ **current** | Agent 交接模板。 |
| `docs/24_agy_executor_prompts.md` | ✅ **current** | 交辦 AGY/Executor 的**可填空模板**(起手/Reviewer/激進版);任務範圍以 STATUS + Planner 當次 Confirmed Scope 為準,本檔不鎖定具體 Phase 清單。 |
| `docs/20_simplification_strategy.md` | ✅ **current,功能刪減與策略治理 source of truth** | 2026-07-10 使用者確認的 B 方案:停止擴張探索頁與新策略,策略/技術分解耦、績效閉環、UI 合併及排程簡化階段。 |
| `docs/21_private_beta_access_r2_plan.md` | ✅ **current,私人測試與 R2 source of truth** | Cloudflare Access 整站白名單、Pages 旁路封鎖、R2 僅作私有快照/未來歷史拆檔,不得當即時 SQLite。 |
| `docs/22_armed_tracking.md` | 📝 **規劃定案,程式未實作** | Armed/Triggered 狀態追蹤(未發動籌碼·權證池);須等 `20` Phase 1–3 與 `21` Access 有進度後另確認才實作,不新增策略/不抬綜合分。 |
| `docs/23_product_ui_backlog.md` | 📝 **規劃定案,程式未實作** | Access/B/Armed 之後的功能與視覺優化 backlog(V1–V3 / F1–F4)+ Executor 工作包;不得插隊或引入新配色/第14策略。 |
| `docs/25_ui_information_architecture_plan.md` | 📝 **任務導向 UI 規劃已落檔,程式未實作** | 將前端重整為掃描→判讀→追蹤任務流,含首頁/個股/分點/自選 IA Phase 與 Executor 驗收;不取代 `20`/`22`/`23`,每次只可另確認一個 Phase。 |
| `docs/29_db_slimming_plan.md` | 📝 **Planner 提案,尚未執行,2026-07-14 定案分析** | 雲端 `radar.db` 瘦身計畫(WP-M3R),取代 `docs/26` WP-M3 過時的容量估算;實測 `indicators_daily`(52%)才是主要肥胖來源,非分點資料(21%);`daily_prices` 明確排除、永遠保留全歷史不動。動 DB 體積/分點拆分/技術指標保留政策時必讀,以此檔數字為準。 |

有疑問時,信任順序:`project-context.md` / `STATUS.md` / `20`(功能刪減與策略治理) / `21`(私人測試/Access/R2) / `22`(Armed 追蹤) / `23`(功能·視覺 backlog) / `25`(任務導向 UI IA) / `12` / `08§0` / `vps_backfill_plan.md` > 其餘 `docs/*` > 對話記憶。

## Required Reading(改檔前必讀)

1. `AGENTS.md`(本檔)
2. `docs/project-context.md`
3. `docs/STATUS.md`
4. `docs/17_no_fable_workflow.md`
5. `docs/18_handoff_template.md`
6. `docs/24_agy_executor_prompts.md`(交辦 AGY 或其他 Executor 複製提示詞時用;與 18 搭配)
6. `docs/20_simplification_strategy.md`(進行功能規劃、評分、前端資訊架構或排程簡化時必讀)
7. `docs/21_private_beta_access_r2_plan.md`(動登入、Access、R2、DB 備份/還原時必讀)
8. `docs/22_armed_tracking.md`(規劃或實作未發動/已發動狀態追蹤、Armed 池時必讀)
9. `docs/23_product_ui_backlog.md`(規劃或實作額外功能 / 視覺優化 V·F 工作包時必讀;並讀 `docs/19`)
10. `docs/25_ui_information_architecture_plan.md`(規劃或實作首頁/個股/分點/自選的任務流重整、功能合併或版面層級時必讀;一次只做一個 IA Phase)

再依任務追加:
- 動資料庫/排程/R2 → `docs/08_scheduler_jobs.md` §0 + `docs/21_private_beta_access_r2_plan.md` + `.github/workflows/*.yml`
- 動評分規則 → `docs/04_signal_rules.md` + `pipeline/radar/compute/scores.py` + 對應 test
- 動前端頁面 → `docs/07_frontend_pages.md` 對應章節 + `docs/19_ui_guidelines.md` + `docs/25_ui_information_architecture_plan.md`(若涉及資訊架構/功能合併) + 該頁面檔案
- 動資安/登入 → `docs/10_security_legal.md` + `docs/14_feature_wave2.md` §4 + `docs/21_private_beta_access_r2_plan.md`

## Golden Rules

1. 改前先看 `git status`、`git diff`——搞清楚工作區目前是什麼狀態。
2. 每個 agent 在自己的短分支工作,不直接改主線(除非使用者明確要求直接在 `main` 上改)。
3. 改前先提出短 plan(目標、要動的檔案、預期風險)。
4. **不重構整個專案**,除非使用者明確要求;禁止「順手重構」——看到不順眼的舊程式碼,除非任務就是修它,否則不要動。
5. 不改 unrelated files。
6. **不改 `.env`、金鑰、部署設定、GitHub Actions workflow yaml**,除非任務明確就是要改這些。
7. 大改前先產生 handoff / plan(見 `docs/18`)。
8. 改完必列:修改檔案 / 內容摘要 / 測試方式 / 風險 / 下一步。
9. 任一 agent 中斷或沒額度不代表停擺,可交接給另一個 agent(見 `docs/17` Workflow B),交接照 `docs/18`。
10. Reviewer 意見只是建議,不代表可自動 merge——人類看過才算數。

## 本專案專屬危險清單

- ⚠️ **`main` push 會直接觸發 Cloudflare Pages 正式部署**(`deploy.yml` on push)。未經人類確認,不得 push `main`。
- ⚠️ **不動 DB 備份的 WAL 合併邏輯**。`pipeline/radar/db.py` 開 `PRAGMA journal_mode=WAL`,四支 workflow 的 cache-save 前都有 `PRAGMA wal_checkpoint(TRUNCATE)`——這是**剛修好的根因**(曾導致 VPS 下載備份出現 `database disk image is malformed`)。拿掉這段會重現該問題。
- ⚠️ **不動 cache / release `db-backup` 的 DB 續存鏈**。5 支 workflow 共用 `radar-db` concurrency group,cache 優先、miss 才用 release 種子還原——這條鏈曾經分岔過(見 `docs/15`),改動前必須完整理解全部 5 支 workflow 的還原/存檔順序。
- ⚠️ **不動 `adj_factor` 還原價邏輯**。`daily_prices.adj_factor` 由 FinMind `TaiwanStockDividendResult` 累乘計算,技術指標與績效回填都依賴 `price * adj_factor`。
- ⚠️ **DB 已 ~1GB,逼近 GitHub Release 單檔 2GB / Actions cache 10GB 上限**。分點資料擴到 5 年前(P2,見 `vps_backfill_plan.md`)**必須先**把分點歷史拆成獨立檔(如 `branch_hist.db`)或搬去 Cloudflare R2,否則會炸掉這兩個上限。勿貿然灌大量分點歷史資料。
- ⚠️ **R2 不是即時資料庫**。只能放 SQLite/JSON 物件快照;不得讓多支 workflow 對同一 R2 物件做「線上 SQLite」讀寫,不得在 restore drill 前移除 Actions cache/Release fallback,不得公開 `r2.dev` backup URL。
- 不做 TWSE bsr CAPTCHA 破解(已定案取捨)。
- 不做自動下單(已定案取捨,見 `docs/10` §3)。

## Agent Roles

角色由**本次任務指定,不由模型品牌永久決定**。GPT、Claude、Gemini、Grok、Codex 或其他高階模型,能力足夠時都可擔任 Planner、Executor 或 Reviewer。

| Role | 工作內容 | 限制 |
|---|---|---|
| **Planner** | 分析需求、功能整合、UI 統一、新功能、技術方案、風險與實作順序 | 預設只讀,不修改程式碼 |
| **Executor** | 依照已確認的 plan 修改程式碼、補測試與更新必要文件 | 不自行擴張需求或更改已確認 plan |
| **Reviewer** | 審查 plan 或 git diff,檢查錯誤、安全性、測試與 MVP 偏離 | 預設只讀,不可審查後直接修改 |
| **Human User** | 決定架構、優先順序、merge、deploy、資料刪除及正式環境變更 | 唯一最終決策者 |

工具對照(名稱可保留,但不永久綁定角色):**Cursor** = IDE / 檔案 / diff / branch / 人工確認介面(唯一例外,是介面而非角色,本身不代表決策);**Claude Code、AGY/Gemini、Codex、GPT/Grok 等高階模型**均可任 Planner / Executor / Reviewer,遵守相同流程。高階模型擔任 Planner 時,主要用於系統與產品規劃、找出重複功能、合併相似頁面/介面、統一 UI/元件/篩選器/狀態與操作流程、提出值得增加的新功能、找出可刪除/簡化/自動化的功能、評估風險成本與實作順序。

## 未被指定角色的 agent(低信任情境)的額外限制

未被明確指定為 Planner / Executor / Reviewer 的 agent,比照 `docs/17` Workflow C:不做架構大改、不做 destructive migration、不改部署設定;只做文件整理、小 bug、isolated changes;每次小範圍改動 + 附 `git diff`;重要決策留給使用者。
