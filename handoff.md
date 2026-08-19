## Handoff

- **Current Goal**: WP-B7 前端核准閘門已實作。使用者需在 Supabase SQL Editor 執行 `docs/sql/app_profiles.sql`,再用 `a7033140327k@gmail.com` 登入後到 `/admin` 核准新使用者。Cloudflare Access **未拆除**。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - 全頁 Google 登入(AuthGate)+ pending/rejected 等待頁
  - `app_profiles` 表 SQL:既有使用者自動核准;指定管理員;新登入預設 pending
  - `/admin` 核准/拒絕使用者
- **Files Changed（本次 WP-B7 前端閘門）**:
  - `docs/sql/app_profiles.sql`（新增,需人工在 Supabase 執行一次）
  - `web/components/AuthGate.tsx`、`web/app/layout.tsx`、`web/lib/useSession.ts`
  - `web/app/admin/page.tsx`、`web/components/AuthButton.tsx`、`web/components/DesktopNav.tsx`
  - `handoff.md`、`docs/STATUS.md`、`docs/31_plan_b_vps_data_home.md`
- **Known Issues**: 前端閘門不是 `/data` 安全邊界;Access 仍為整站門鎖。表尚未建立時前端暫時 fail-open,避免鎖死既有測試者。
- **Not Yet Done（專案層級）**:
  - **WP-B7 剩餘**:Worker 驗 Supabase JWT + 關 Access(需另案資安審查)。
  - **WP-B6**:全市場歷史回補仍在 VPS tmux 跑(`backfill-branches` / `backfill-warrant-branches`)。
  - **B 方案 Phase 2 剩餘**:全市場重算(watchline crossed=0,目前不急)。
- **Next Suggested Actions**:
  1. 使用者立刻在 Supabase 執行 `docs/sql/app_profiles.sql`。
  2. 等 Cloudflare Pages 部署後,用管理員 Gmail 登入,確認 `/admin` 可見。
  3. 分點/權證回補跑完後再 `compute-branch-stats` + `export-json` + deploy。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - Cloudflare Access / Worker 路由(本輪不拆)。
  - `.github/workflows/*.yml`（排程部署設定）。

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
