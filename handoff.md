## Handoff

- **Current Goal**: PWA 完善(install / PNG icons / iOS A2HS / standalone / safe-area / 更新提示 / 離線誠實)已落地。等使用者下一任務。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 從 `trever-radar-mark.svg` 匯出 16/32/180/192/512 + maskable PNG(未重畫 Logo)
  - 延伸 `web/app/manifest.ts`;`web/public/sw.js` 只 cache app shell,不碰 `/data` 與 JWT
  - Android `beforeinstallprompt`、iOS 加入主畫面提示、更新 toast、離線橫幅、safe-area Header/BottomNav
  - 登入頁改用正式 brand mark
- **Known Issues**:
  - **`import-geo` 等回補結束**:兩筆回補跑完前不要手動寫 DB。
  - Chrome 可安裝條件需 HTTPS + 192/512 PNG + SW(部署後用手機驗證)。
  - `design-system/stock/MASTER.md` 可能仍寫舊綠/`#22C55E`/Fira——以現站為準,勿回改 Web。
- **Not Yet Done**:
  - **docs/27 G3** 庫藏股
  - **docs/22** Quiet/Extended/Faded
  - iOS splash 多尺寸(非必須);原生 Capacitor 封裝(未授權)
- **Next Suggested Actions**:
  1. 部署後用 Android Chrome「安裝應用程式」與 iOS Safari「加入主畫面」實機驗。
  2. 回補結束 → `import-geo` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - Header 品牌 mark 路徑 / `web/public/icons/trever-radar-mark.svg`(可再匯出 PNG,勿重畫)
  - 另起衝突的第二份 PWA manifest
  - `pipeline/radar/db.py` 的 WAL checkpoint
  - `.github/workflows/*.yml`
  - 正式 `radar.db`

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
