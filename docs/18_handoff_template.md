# 18 Agent 交接模板

> 流程說明看 `docs/17_no_fable_workflow.md`。本檔只放**交接時要填的表格**。
> 分兩級:日常小改用輕量版,跨 agent 或高風險任務用完整版——避免制度太重被跳過。

## 輕量交接(日常小改用)

四欄,複製貼上即可:

```markdown
- **Current Goal**:
- **Current Branch**:
- **Files Changed**:
- **Next Suggested Action**:
```

## 完整交接(跨 agent 或高風險任務用)

高風險任務定義見 `docs/17` 的「高風險項目清單」。

```markdown
## Handoff

- **Current Goal**:
- **Current Branch**:
- **Current Agent**:(Claude Code / AGY / Codex / 其他)
- **Work Completed**:
- **Files Changed**:
- **Current Git Status**:(貼 `git status` / `git diff --stat` 輸出)
- **Known Issues**:
- **Errors/Logs**:(有錯誤訊息就完整貼,不要摘要)
- **Tests Run**:(跑了什麼、結果如何;沒跑就寫「未跑」)
- **Not Yet Done**:
- **Next Suggested Actions**:
- **Files That Should Not Be Modified**:(對照 `AGENTS.md` 危險清單,列出本次任務範圍內特別要避開的)
- **Risk Notes**:
```

---

## 固定提示詞(直接複製貼上,不要改寫)

### 貼給 AGY 或任何新接手的執行者

> 你現在是接手本專案的 agent。請先閱讀 AGENTS.md、docs/17_no_fable_workflow.md、docs/18_handoff_template.md、docs/STATUS.md。請先不要修改程式碼。請先輸出你理解的狀態、下一步計畫、你預計修改哪些檔案。等待使用者確認後才開始修改。

### 貼給 Codex(review 用)

> 請 review 目前的 git diff(或指定範圍)。檢查:是否符合 AGENTS.md 危險清單(尤其 WAL checkpoint、cache/release DB 續存鏈、adj_factor 邏輯是否被動到)、是否有安全疑慮、測試是否涵蓋改動、是否偏離 docs/STATUS.md 目前的 MVP 優先序。只回報 review 結果,不要直接修改檔案;若你認為需要改,先列出會動哪些檔案再等使用者確認。

### 貼給 Claude Code(新對話接手時)

> 請先讀 AGENTS.md、docs/project-context.md、docs/STATUS.md、docs/17_no_fable_workflow.md,再讀 git status 與 git diff 確認現況。先輸出理解摘要與 plan,不要直接開始改程式碼,等我確認範圍後再動手。

### 貼給 Claude Code(Pilotfish)
請先閱讀 `AGENTS.md`、`docs/project-context.md`、`docs/STATUS.md`、`docs/17_no_fable_workflow.md` 與 `docs/18_handoff_template.md`，再檢查目前 branch、`git status`、`git diff` 與最近相關 commit。

請依照 Pilotfish 工作流完成本次任務：

* 搜尋與程式定位交給 `scout` 或 `Explore`
* 規則明確的機械式修改交給 `mech-executor`
* 需要判斷的功能實作與 Bug 修正交給 `executor`
* 涉及資安、認證、權限、密鑰、輸入驗證或弱點修補的工作交給 `security-executor`
* 非簡單修改完成後，交給全新 context 的 `verifier` 獨立驗證

開始修改前，先在回覆中簡短列出：

1. 需求理解
2. 實作方案
3. 預計修改的檔案
4. 主要風險
5. 目前所在 branch 與工作目錄是否乾淨

確認沒有違反 `AGENTS.md` 的危險清單後即可繼續執行，不需要等待我再次確認。

執行期間請遵守以下限制：

* 不要擴大需求範圍
* 不要重構無關程式碼
* 不要修改未列入計畫的重要檔案，除非為完成需求所必要；若必須增加修改範圍，請在最終報告中明確說明
* 不得執行 `merge`、`rebase`、`reset --hard`、`clean`、強制推送或刪除遠端 branch
* 不得刪除資料庫、正式資料、備份或使用者資料
* 不得修改正式環境、正式伺服器或部署正式版本，除非本次任務明確要求
* 不得使用 `git push --force` 或 `git push --force-with-lease`
* 不得跳過測試或 verifier，就直接宣稱完成
* 若 verifier 回報 `REFUTED`，必須先修正並重新驗證
* 若測試失敗且無法在本次範圍內安全修正，不要 commit 或 push，請保留修改並在最終報告說明
* 若發現目前 branch 是 `main`、`master` 或其他正式分支，只有在本次修改明確允許直接推送正式分支，且現有專案流程也允許時，才能直接 push；否則請建立適當的工作 branch 再提交
* 建立新 branch 時，名稱應清楚反映任務內容，例如 `fix/...`、`feat/...` 或 `docs/...`
* 不要將 `.env`、密鑰、token、憑證、資料庫檔、備份檔、暫存檔或其他敏感資料加入 commit

完成修改後，依序執行：

1. 檢查 `git diff`
2. 執行與修改直接相關的測試
3. 執行必要的 lint、type check 或語法檢查
4. 交給全新 context 的 `verifier` 獨立驗證
5. 確認 verifier 結論為 `CONFIRMED`
6. 再次檢查 `git status` 與即將提交的檔案
7. 建立內容明確的 commit
8. 將目前工作 branch push 至遠端

你可以自行執行 `git commit` 與一般的 `git push`，不需要等待我在線確認，但只能提交與本次任務直接相關、已測試且已通過 verifier 的修改。

Commit message 請使用清楚、可追蹤的格式，例如：

* `fix: 修正盤中資料續存異常`
* `feat: 新增分點交易查詢`
* `docs: 更新專案接手文件`
* `test: 補充分點資料流程測試`

若工作目錄原本已有與本次任務無關的未提交修改：

* 不要擅自修改、丟棄或提交那些變更
* 只 stage 本次任務相關檔案
* 若無法安全區分，不要 commit 或 push，請在最終報告說明原因

完成後請回報：

* 需求完成狀態
* 實際修改的檔案
* 每個檔案的修改內容
* 執行過的測試與結果
* verifier 結論與主要依據
* 是否碰觸 `AGENTS.md` 危險清單
* 是否偏離原實作計畫
* commit message
* commit hash
* push 的 remote 與 branch
* 尚未完成或無法驗證的項目
* 殘留風險
* 建議的下一步
