# 11 AI 輔助開發流程(2026-07-09 改版)

> **主流程已改為 No-Fable workflow,完整規則見 `AGENTS.md` + `docs/17_no_fable_workflow.md` + `docs/18_handoff_template.md`。本檔不重複那三份的內容,只放本專案的技術棧對照與省 token 細節。**
>
> ⚠️ 舊版本檔(2026-07-06 前)寫的是 Laravel/PHP 技術棧(`Modules/Scoring/*.php`、`php artisan`、pint/phpstan/phpunit、trunk-based+PR)。**那套從未被實際採用**——專案定案技術棧是 Python(見 `docs/12_zero_cost_pivot.md`),以下已全部改寫對應。

## 1. 核心原則(與舊版一致,原則不變)

1. **文件即上下文**:AI 每次任務只讀 `docs/project-context.md`(<150 行)+ 該任務對應的規格文件 + 目標檔案。永遠不丟整個專案。
2. **規則進文件,不進對話**:任何架構決策做完立刻寫進 `project-context.md` 的「已做取捨」;下次任何模型接手都從文件出發,對話歷史可拋棄。
3. **純函式評分層是省 token 的關鍵**:`pipeline/radar/compute/*` 無 I/O、無框架依賴,AI 修改評分規則時只需讀 `04` 文件 + 對應 compute 模組 + 其測試,不用理解整個系統。
4. **小模型可讀**:文件用表格與短句。

## 2. 每類任務的「該讀檔案清單」(技術棧已更新為 Python/Next.js)

| 任務 | 讀 |
|---|---|
| 改評分規則 | `project-context` + `04` + `pipeline/radar/compute/scores.py` + `pipeline/tests/test_scores.py` |
| 改技術指標 | `project-context` + `04`§6 + `pipeline/radar/compute/indicators.py` + `pipeline/tests/test_indicators.py` |
| 加資料源 | `project-context` + `03` + `vps_backfill_plan.md`(分點來源現況)+ `pipeline/radar/providers/` 內一個現有實作當範本 |
| 改前端頁 | `project-context` + `07` 對應章節 + 該頁面檔案(`web/app/*`)+ 對應元件(`web/components/*`) |
| 改排程 | `project-context` + `08`§0 + `.github/workflows/*.yml`(**改前先讀 `AGENTS.md` 危險清單**) |
| 改資料表 | `project-context` + `05` + `pipeline/radar/schema.py`(**改 `05` 文件先於改 code**) |

## 3. 防 AI 改壞(比省 token 更重要)

1. **Golden-file / pytest 測試**:`pipeline/tests/` 已有 `test_adjustments.py`、`test_indicators.py`、`test_performance.py`、`test_scores.py`、`test_theme_score.py`——固定輸入資料集,評分輸出快照比對。AI 動評分必跑,分數變了就會被看見——變動要嘛是預期(更新快照 + 在摘要說明),要嘛是 bug。
2. Provider 測試:每個 provider 用錄下的真實 API response 測 parser;來源改版時 fixture 更新即回歸(現況:尚未每個 provider 都有測試,新增 provider 時應補)。
3. CI:目前無強制 CI gate(尚未設 GitHub Actions CI workflow 跑 pytest)。**改動評分/指標邏輯後,本機手動跑 `pytest pipeline/tests/` 確認全過,並在交接摘要寫明測試結果。**
4. **一次一模組**:給 AI 的任務切到「單一模組單一行為」;跨模組需求先拆單。禁止「順手重構」——重構是獨立任務(呼應 `AGENTS.md` Golden Rule 4)。
5. 驗收:目前用 `python -m radar export-json` 產出 JSON 後人眼比對前端顯示,尚無自動化 dry-run 驗收腳本。

## 4. 分支與節奏(現況,非規劃)

- **實際流程**:目前是直接在 `main` 上 commit 並 push(**不是** trunk-based+PR)。`main` push 會直接觸發 `deploy.yml` 正式部署——這是 `AGENTS.md` 列的頭號危險項,任何 push 前都要三思。
- Conventional Commits 風格(`feat:`/`fix:`/`docs:`/`chore:`)已在使用,維持。
- 沒有 `CHANGELOG.md`;決策變更記錄在 `docs/STATUS.md`「最近完成」區與 `project-context.md`「已做的關鍵取捨」。

## 5. 歷史回補策略(省 API/請求額度,原則不變)

- FinMind 免費額度約 600 req/hr:`deep-backfill` 已做斷點續傳(已拉深的股票自動跳過)。
- 分點資料(MoneyDJ 鏡像,見 `vps_backfill_plan.md`):夜間 GitHub Actions 增量 + 大量回補交給使用者 VPS(額度數學見 `docs/15`——GitHub Actions 免費額度撐不住大量長跑任務)。
- 冷門股/池外股票:lazy 補(現況見 `STATUS.md` 已知債務)。

## 6. 開發順序(歷史記錄,V1 已大致完成)

原規劃 8 週順序(專案骨架→資料 Provider→指標→Scoring→觀察清單→個股頁→探索頁)已大致走完,現況以 `docs/STATUS.md` 的「已完成」清單為準,不在此重複。後續開發任務排序改看 `STATUS.md`「未完成(依優先序)」。
