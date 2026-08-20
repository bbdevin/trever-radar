## Handoff

- **Current Goal**: 品牌+PWA 身分已整合進 `main`(`e3cefcd`)。不重做 Logo、不蓋 Header mark。等使用者下一任務(PWA 完善或資料/口袋驗收)。
- **Current Branch**: `main` @ `e3cefcd`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - `git pull --ff-only`:`540c5f0` → `e3cefcd`
  - 品牌決策落檔:`docs/19`、`docs/project-context.md` 取捨 17、`STATUS`、本檔
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - PWA 目前只有 SVG icon + manifest;192/512 PNG、maskable、install UI、離線策略尚未做。
  - `design-system/stock/MASTER.md` 可能仍寫舊綠/`#22C55E`/Fira——以現站為準,勿回改 Web。
- **Not Yet Done**:
  - PWA 完善(install / PNG icons / iOS A2HS / standalone / safe-area / 更新提示);須 Network First 行情、不動登入 JWT、不改評分語意
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
- **Next Suggested Actions**:
  1. 使用者指定下一包再做(建議 PWA 優先序見對話:installability → PNG icons → iOS/Android 體驗 → standalone/safe-area)。
  2. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark / `web/public/icons/trever-radar-mark.svg` / `web/app/manifest.ts`(延伸可,另起衝突設定不可)
  - `pipeline/radar/db.py` 的 WAL checkpoint
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
