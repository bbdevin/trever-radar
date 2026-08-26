# Handoff — 2026-08-26（VPS 日更／上櫃補抓／ntfy 繁中）

## 下一對話可貼上（Executor / Auto）

```
你是 Trever Radar 的 Executor（Cursor Auto）。請用繁體中文回覆。

必讀：AGENTS.md、docs/project-context.md、docs/STATUS.md、本檔 handoff.md、
docs/08_scheduler_jobs.md §0、docs/35_vps_schedule_architecture.md、vps/README.md。

現況摘要（2026-08-26 晚）：
- main HEAD = a81860c；本機與 VPS `/home/huang/trever-radar` 已 ff-only 對齊。
- 上櫃日K 14:10 常 empty → 已加平日 15:00 `daily-tpex-quotes.sh`，VPS crontab 已掛；安靜窗 14:05–15:45。
- 08-24/25/26 上櫃全日K 已手動補齊並 export/deploy 過。
- ntfy 成功／失敗／略過改繁中標題（如「三大法人 · 成功」），見 vps/scripts/lib.sh。
- 董監月槽 `monthly-directors.sh` 僅在 crontab.example，正式 crontab 尚未掛（待人工）。

仍須人工確認才可做：正式 radar.db 全市場重算／destructive、改 workflows/secrets、force push。
一般功能完成後：更新 handoff + STATUS（及相關 docs）→ commit → push main（勿擴大 Scope）。

先輸出：理解摘要、Confirmed Scope 草稿、預計動檔、風險；等我確認再改碼（除非我已給明確實作指令）。
```

若本次是規劃：改貼 `docs/18_handoff_template.md`「貼給 Planner(Grok 4.6 High)」。

---

## Handoff 表

- **Current Goal**: 日更穩定（上櫃不卡舊日）+ ntfy 繁中；交接給下一 agent 繼續待辦
- **Current Branch**: `main`（與 `origin/main` 對齊；工作區乾淨）
- **已確認範圍(Confirmed Scope)**: 本輪已完成、無需再開；下一輪需使用者另確認 Scope
- **Current Role**: Executor（本對話收尾／交接）
- **Next Role**: Executor（或 Planner，若要排下一優先序）
- **Current Agent / Model**: Cursor Auto
- **Suggested Next Agent / Model**: Cursor Auto（實作）；規劃用 Grok 4.6 High
- **Work Completed**:
  1. **上櫃 15:00 補抓**：`vps/scripts/daily-tpex-quotes.sh`；`crontab.example` + **VPS live crontab 已掛**；`lib.sh` 安靜窗含至 15:45
  2. **資料修復**：手動補 08-24／25／26 上櫃日K + 指標 + export/deploy（先前 24／25 僅半套、部分檔看似停在 08-21）
  3. **ntfy 繁中**：`lib.sh` 的 `job_zh`／`notify_ok`／`notify_skip`／`notify_warn`；日更與 mid／backup／tdcc 等腳本已接
  4. **VPS `git pull`**：已到 `a81860c`
- **Files Changed**（本主題相關，已在 main）:
  - `vps/scripts/daily-tpex-quotes.sh`、`lib.sh`、各 `daily-*.sh`／`mid-*`／`weekly-*`／`bf-*` 等
  - `vps/scripts/crontab.example`、`vps/README.md`
  - `docs/08_scheduler_jobs.md`、`docs/35_vps_schedule_architecture.md`、`docs/STATUS.md`、本檔
- **Current Git Status**: `main...origin/main`；HEAD `a81860c feat(vps): Traditional Chinese ntfy success summaries`
- **VPS**:
  - path: `/home/huang/trever-radar`
  - HEAD: `a81860c`（已 pull）
  - 日更 crontab（台北）:
    - 14:10 `daily-market.sh`
    - **15:00 `daily-tpex-quotes.sh`** ← 已上線
    - 16:10 `daily-insti.sh`
    - 17:40 / 21:00 `daily-branches.sh`
    - 22:10 `daily-margin.sh`
    - 另有 mid-publish、safe-branch-stats、bf-supervisor、weekly-backup、weekly-tdcc
  - **未掛**: `monthly-directors.sh`（example 為每月 16 日 07:00）
- **Known Issues**:
  - 14:10 TPEx `dailyQuotes` 仍可能 empty（設計上靠 15:00＋後續輪補）
  - 16:10 曾遇 TPEx warrant-master timeout（腳本側已非致命＋繁中 warn）
  - 內部人％週表欄位 UI 暫藏；董監分頁仍在
- **Errors/Logs**: 無未解 blocker；細節見對話 transcript `dfaac668-8b88-4bf2-bb71-3440554bec58`
- **Tests Run**: 未跑 pytest／web build（本輪為 VPS 腳本＋文件＋手動補資料）
- **Not Yet Done**:
  1. **人工**：掛董監月槽 crontab（`monthly-directors.sh`）
  2. 下個交易日觀察 15:00 上櫃是否準時齊、ntfy 繁中是否正常
  3. 其餘產品待辦見 `docs/STATUS.md`「未完成」（Phase 2 全市場重算、WP-B6、Phase 4 排程簡化等——皆須另確認）
- **Next Suggested Actions**:
  1. 使用者決定是否 SSH 掛 `monthly-directors.sh`
  2. 交易日抽查：`radar.json` freshness 上市／上櫃是否同日；ntfy 標題是否為繁中
  3. 勿在回補／日更鎖檔時手動寫正式 `radar.db`
- **Files That Should Not Be Modified**:
  - `.github/workflows/*`、secrets、DNS、Access
  - `adj_factor` 還原邏輯；`weekly-backup.sh` 的 WAL checkpoint／integrity_check
  - 正式環境第二寫者；未批准的 destructive DB 操作
- **Risk Notes**: `main` push 只部署前端／程式碼；資料靠 VPS `wrangler deploy`。動 cron／回補生命週期先讀 `docs/35`。

---

## 關鍵 commit

| commit | 說明 |
|---|---|
| `e58a820` | 15:00 上櫃補抓腳本＋安靜窗 |
| `6fd8af8` | docs：15:00 crontab 已 live |
| `a81860c` | ntfy 繁中成功摘要 |
