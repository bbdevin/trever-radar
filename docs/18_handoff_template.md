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
