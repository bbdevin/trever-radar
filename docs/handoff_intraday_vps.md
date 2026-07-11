## Handoff

- **Current Goal**: 將盤中雷達 (Intraday Radar) Worker 調整為「雲端解耦架構」，以便獨立部署至使用者的 VPS。
- **Current Branch**: `main`
- **已確認範圍(Confirmed Scope)**:
  1. 修改 `pipeline/intraday/worker.py`：將原本讀取本機 `web/public/data/radar.json` 的邏輯，改為使用 HTTP `requests` 向正式網址 (`https://trever-radar.pages.dev/data/radar.json`) 抓取。
  2. 確保 Worker 腳本完全不依賴專案的實體檔案庫，達成只要有 `worker.py` 與 `.env` 即可在遠端 VPS 獨立運行的極簡部署。
- **Current Role**: Planner
- **Next Role**: Reviewer
- **Current Agent / Model**: Google Antigravity
- **Suggested Next Agent / Model**: 任何高階模型 (擔任 Reviewer)
- **Work Completed**:
  - 已完成盤中雷達 I1-I3 基礎實作。
  - Supabase 表格 `intraday_signals` 與 `worker_heartbeat` 結構定案。
  - `worker.py` 已完成 Fugle WebSocket 連線與訊號 (I-1, I-3, I-4) 推播邏輯。
  - 前端 `IntradayPanel.tsx` 實作完成，並掛載於首頁。
- **Files Changed**: (之前的階段已全數 Commit 並 Push)
  - `docs/sql/intraday_signals.sql` (NEW)
  - `pipeline/intraday/worker.py` (NEW)
  - `web/components/IntradayPanel.tsx` (NEW)
  - `web/app/page.tsx` (MODIFIED)
- **Current Git Status**: 工作目錄乾淨，與遠端 `main` 同步。
- **Known Issues**: `worker.py` 仍寫死讀取本機相對路徑的 `radar.json`，直接丟上 VPS 會因找不到檔案而報錯。
- **Errors/Logs**: 無
- **Tests Run**: 前端 TypeScript 已透過 `npm run build` 確認無編譯錯誤。
- **Not Yet Done**:
  - `worker.py` 尚未改寫為 HTTP URL Fetch 邏輯。
  - 尚未在 VPS 上設定 `.env` 與 `cron` 排程。
- **Next Suggested Actions**:
  1. 請 Reviewer 確認：「將 `worker.py` 改為直接抓取 `https://trever-radar.pages.dev/data/radar.json`」的架構變動是否安全且符合專案規範？
  2. （請 Reviewer 特別注意：雖然目前 URL 可公開抓取，但根據 `docs/21` 規劃，未來上線 Cloudflare Access 後，`/data/radar.json` 會被保護。請確認此改動是否需預留 `CF-Access-Client-Id` Header 擴充空間。）
  3. 若 Reviewer 審查通過，請直接交辦 Executor 修改 `worker.py` 並 push。
- **Files That Should Not Be Modified**:
  - 遵守 `AGENTS.md` 危險清單，不得觸碰任何與 `cache/release DB 續存鏈`、`.github/workflows/*.yml` 相關的邏輯。
- **Risk Notes**:
  - 此改動會讓 Worker 對正式網站發出網路請求。若未來實作 `docs/21` 的 Private Beta Access 防護網，Worker 將會收到 403 Forbidden。屆時需要在 Worker 的 `.env` 補上 Cloudflare Service Token 並夾帶於 Request Header 中才能穿透防護。

---

## 部署步驟(VPS)

雲端解耦改造完成後,`pipeline/intraday/worker.py` 只需自身 + `.env` 即可獨立運行(radar.json 改為向正式站 HTTP 抓取,不再依賴 repo 實體檔)。以下為在使用者 VPS 上部署的步驟。

### 1. Supabase 前置(僅需一次)

先於 Supabase SQL Editor 執行 `docs/sql/intraday_signals.sql`,建立 `intraday_signals` 與 `worker_heartbeat` 兩張表及其 RLS。**未先建表,worker 寫入會失敗。**

### 2. Python 依賴

只需要 worker 相關的套件即可(不必安裝整條盤後管線的 pandas/SQLAlchemy)。相對於基礎 `requests`,本階段新增的三個依賴為:

```bash
pip install "fugle-marketdata>=2.4.1" "supabase>=2.31.0" "python-dotenv>=1.2.2" "requests>=2.31"
```

(或直接 `pip install -r pipeline/requirements.txt`。)

### 3. `.env` 設定

在 worker.py 同目錄放置 `.env`,鍵值如下:

| 鍵 | 必填 | 說明 |
|---|---|---|
| `FUGLE_API_KEY` | ✅ | Fugle MarketData 金鑰。**務必使用輪替後的新 key** — 舊 key 已進 git 歷史,視為已洩漏,請至 Fugle 後台撤銷舊 key、改用新 key。 |
| `SUPABASE_URL` | ✅ | Supabase 專案 URL。 |
| `SUPABASE_KEY` | ✅ | Supabase **service role key**(僅存本機 .env,絕不進版控)。 |
| `RADAR_JSON_URL` | 可選 | radar.json 來源;預設 `https://trever-radar.pages.dev/data/radar.json`。 |
| `CF_ACCESS_CLIENT_ID` | 可選 | Cloudflare Access service token(docs/21 Access 上線後才需要)。 |
| `CF_ACCESS_CLIENT_SECRET` | 可選 | 同上;兩者需成對設定,worker 才會夾帶 `CF-Access-*` header 穿透 Access。 |

缺任一必填鍵,worker 啟動時會 fatal exit 並印出指引訊息。

### 4. cron 排程(平日開盤前啟動)

Worker 於本機時間 13:35 自動收工。平日 08:50 啟動一次即可(週一~週五):

```cron
# 分 時 日 月 週  指令
50 8 * * 1-5 cd /home/you/trever-radar-worker && /home/you/trever-radar-worker/.venv/bin/python worker.py >> /home/you/trever-radar-worker/worker.log 2>&1
```

(請將路徑替換為 VPS 上實際的部署目錄與 venv;VPS 時區需為台北時間 `Asia/Taipei`,否則 08:50 / 13:35 會對不上盤中時段。)

### 5. 韌性行為說明

- radar.json 抓取失敗(網路 / 403 / 非 200 / JSON 解析失敗)會退避重試 3 次;仍失敗時:
  - 若記憶體已有上一次成功的名單 → 沿用該名單繼續跑。
  - 若首次啟動即失敗 → fatal exit,訊息指引檢查 `RADAR_JSON_URL` 與(Access 上線後的)`CF_ACCESS_*` token。
