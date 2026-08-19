## Handoff

- **Current Goal**: WP-B7 關掉 Cloudflare Access、只留站內登入。程式已落地;使用者需在 VPS 設 secret + deploy,確認 `/data` 401 後,才在 Zero Trust 關閉 Access Application。
- **Current Branch**: `main`
- **Workflow(2026-08-19)**:規劃 → Grok 4.6 High；執行 → Auto agent；完成 → 更新 md + commit + push（見 `AGENTS.md`、`docs/17` Workflow D）
- **Current Agent**: Cursor
- **Work Completed（本次）**:
  - `/data` Worker 必須驗身分:Bearer JWT + `app_profiles.status=approved`,或 `X-Radar-Service-Key`
  - 前端所有 `/data` fetch 改走 `dataFetch`(帶 Supabase JWT)
  - 盤中 worker 夾帶 `X-Radar-Service-Key`;Access header 過渡期仍可並存
- **Files Changed（本次 WP-B7 Worker JWT）**:
  - `cloudflare-data-worker/src/index.js`、`wrangler.toml`、`README.md`
  - `web/lib/dataFetch.ts` + 各頁 `dataFetch` 替換
  - `pipeline/intraday/worker.py`、`.env.example`、`pipeline/tests/test_intraday_worker.py`
  - `handoff.md`、`docs/STATUS.md`、`docs/31`、`docs/21`、`vps/README.md`、`AGENTS.md`
- **Known Issues**: Access 仍在,會登兩次 Google,直到使用者關閉 Application。本機不得 wrangler deploy。
- **Not Yet Done（需使用者操作）**:
  1. VPS:`git pull` → `wrangler secret put RADAR_SERVICE_KEY` → 同一把寫入 `pipeline/intraday/.env` → `npx wrangler deploy`
  2. 用 Access service token 測:無 key=401、帶 key=200
  3. Zero Trust 關閉 Access Application
  4. 無痕開站只見站內 Google 登入;裸 curl `/data/radar.json` 直接 401
- **Next Suggested Actions**:
  1. 依上方 VPS 步驟部署 Worker(先 secret 再 deploy)。
  2. 確認 401 後關閉 Access。
  3. 分點/權證回補跑完後再 `compute-branch-stats` + `export-json` + deploy(與本項分開)。
- **Files That Should Not Be Modified**:
  - `pipeline/radar/db.py` 的 WAL checkpoint 機制。
  - `.github/workflows/*.yml`
  - 正式 `radar.db`(VPS 唯一寫者)

---

> **Planner(Grok 4.6 High)**:讀 AGENTS.md、docs/17、STATUS、handoff → 產出 Confirmed Scope。
> **Executor(Auto)**:讀 Scope + Workflow D → 實作 → 更新 md → commit → push。Scope 未定或高風險時才「先 plan、等確認」。
