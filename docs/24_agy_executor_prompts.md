# 24 AGY / Executor 交辦提示詞(模板)

> 給人類交辦 **AGY(Gemini)** 或其他 Executor 時複製。
> 交接表格用 `docs/18`;流程用 `docs/17`。
>
> **本檔不鎖定具體功能清單。** 要做什麼以當下的 `docs/STATUS.md`、
> Planner 最新文件 / handoff、以及你在提示詞裡填的「本次任務」為準。
> Planner 更新優先序或範圍後,**不必改本檔**,只要改交辦時填空內容。

## 0. 怎麼用

1. 複製 **§1 標準起手**(或 §3 激進版)。
2. 填空:`本次任務`、`必讀加檔`、`建議 branch`(可選)、`額外約束`(可選)。
3. 需要時加 **§2 角色變體**(Reviewer / Planner 接力)。
4. 安全底線只守 `AGENTS.md` 危險清單與你填的 Confirmed Scope——**不要**在本檔維護過期的 Phase 清單。

任務真相來源(依序):人類這次貼的範圍 → 最新 handoff → `STATUS.md` → 對應 `docs/20`/`21`/`22`/`23`/其他規劃檔。

---

## 1. 標準起手(建議預設:先 plan 再動手)

把 `【】` 換成這次的內容即可。

```
你現在是 Trever Radar 的 Executor(可為 AGY / 其他模型)。

必讀:
1. AGENTS.md
2. docs/project-context.md
3. docs/STATUS.md
4. docs/17_no_fable_workflow.md
5. docs/18_handoff_template.md
【必讀加檔:例如 docs/20、docs/22、docs/23、docs/19、handoff 路徑——依任務填;沒有就刪這行】

開工前:
- 看 git status、git diff、目前 branch
- 對照 STATUS「未完成」與我下方的 Confirmed Scope;若衝突,先說明並停下,不要自行改優先序

規則:
- 先輸出理解摘要、預計改檔、風險、測試方式;等我回「確認」再改碼
- 只做 Confirmed Scope;發現「順便可做」的只列出來問我,不自行擴大
- 不重構無關檔;不改 .env / secrets;不改 workflow yaml(除非 Scope 明確要求)
- 不動 WAL checkpoint、cache/release DB 鏈、adj_factor(除非 Scope 明確且已走高風險流程)
- 不得 merge、不得自行 push main、不得觸發正式部署(除非我明確要求)
- 完成後用 docs/18 輕量交接回報,並更新 STATUS 與本次相關規劃檔的狀態欄(若有)

Confirmed Scope(本次唯一可做範圍):
【用幾句話或條列寫清:目標 / 可動檔案類型 / 驗收 / 明確不做什麼】

建議 branch(可選):【例如 agy/short-topic;沒有就讓 Executor 依任務自訂短分支名】
```

### 1.1 填空範例(僅示範格式,不是固定任務)

> 範例會過期;實際交辦請依當下 STATUS / Planner 更新改寫。

```
Confirmed Scope:
- 依 docs/STATUS 目前第 N 項與 docs/XX 對應章節實作
- 可動:【web/... 或 pipeline/...】
- 驗收:【npm run build / pytest …】
- 不做:【例如不改評分權重、不改 workflow、不 push main】

必讀加檔: docs/XX、docs/19(若動前端)
```

---

## 2. 角色變體(同樣不綁死功能)

### 2.1 Reviewer(只讀)

```
你現在是 Reviewer,只讀不改碼。

必讀:AGENTS.md、docs/STATUS.md、【相關規劃檔】。
請 review【git diff / PR / branch 名】。

檢查:
- 是否超出人類 Confirmed Scope 或偏離 STATUS 目前優先序
- AGENTS.md 危險清單(WAL / cache·release / adj_factor / 未批 push main 等)
- 測試與明顯安全問題、過度設計

只回報問題與建議;若要改,先列檔案等我確認。
```

### 2.2 接 Planner 的 handoff 繼續做

```
你是接手的 Executor。先讀 AGENTS.md、STATUS、以及【handoff 路徑或貼上的 Handoff 全文】。
以 handoff 的 Confirmed Scope 為準;STATUS 若更新導致衝突,先報告再等我決策。
先輸出理解摘要與剩餘 plan,等確認後只完成 Not Yet Done / Next Suggested Actions 內項目。
```

### 2.3 請 Planner 更新任務(人類或另一模型)

```
你是 Planner,預設不改程式碼。
讀 AGENTS.md、STATUS、相關 docs 後,更新或起草【要改的規劃檔 / STATUS 條目】建議稿。
輸出:目標、優先序、建議交 Executor 的 Confirmed Scope 草稿、風險、不做清單。
等我確認後,再決定是否寫入 docs(或交另一 agent 寫入)。
```

---

## 3. 激進版(範圍已寫死且你信任時)

與 §1 互斥:用了就不要再要求「等確認才動手」。  
**Scope 仍由你這次填空決定**,不由本檔寫死。

```
你是 Executor。讀 AGENTS.md、project-context、STATUS、【必讀加檔】後,
直接執行下方 Confirmed Scope。

不要擴大需求;不要改無關檔;不要 push main;不要碰 AGENTS 危險清單,
除非 Scope 明文允許且我已知高風險。
做完跑相關測試/build,用 docs/18 輕量交接回報,並更新 STATUS 與相關規劃狀態欄。

Confirmed Scope:
【目標 / 檔案範圍 / 驗收 / 不做】
```

---

## 4. 穩定安全提醒(很少改;不是任務清單)

這些是專案級底線,與「這週做哪一項」無關:

| 預設不要讓 Executor 自行做 | 原因 |
|---|---|
| `git push main` / 正式部署 | `main` push 會部署 |
| 改 workflow / secrets / DNS / Cloudflare Access 實設 | 高風險外部狀態 |
| 未批准的 destructive migration、全市場重算回灌 | 資料語意與正式資料 |
| 把 R2 當線上 SQLite | 見 `docs/21` |

若某次任務**就是**要做上表某一項:在 Confirmed Scope 明文寫出,並要求走 `docs/17` 高風險流程;不要改寫本檔來「永久開放」。

「目前延後／不做」的產品項以 **STATUS + 現行規劃檔** 為準,本檔不維護副本。

---

## 5. 給人類的一句話流程

```
Planner 更新 STATUS / docs → 你複製 §1 → 填 Confirmed Scope → 交給 AGY
```

不要把過期的 Phase/WP 清單貼進本檔當永久真理;那會和 Planner 打架。
