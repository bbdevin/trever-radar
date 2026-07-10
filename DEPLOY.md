# 上線部署指南(全免費)

架構:GitHub Actions 5 支 workflow(14:10/16:10/17:40/21:00/01:10 台北,分批抓資料+建站;`main` push 觸發 `deploy` 只重建/部署、不抓資料)→ Cloudflare Pages(靜態網站)→ Cloudflare Access(email 白名單登入)。時間表單一真相見 `docs/08_scheduler_jobs.md` §0。

DB 以 Actions cache 續存、GitHub Release 週備份;首跑會從 release 種子還原(本機資料已上傳)。

## 你要做的事(一次性,約 15 分鐘)

### 1. Cloudflare 帳號與金鑰

1. 註冊 https://dash.cloudflare.com(免費方案即可)
2. **Account ID**:進 dashboard → 左側「Workers 和 Pages」→ 右側欄位有 Account ID,複製
3. **API Token**:右上頭像 → My Profile → API Tokens → Create Token → 最下方 **Create Custom Token**:
   - 名稱:`trever-radar-deploy`
   - Permissions:`Account` / `Cloudflare Pages` / `Edit`
   - Continue → Create Token → 複製(只顯示一次)

### 2. 設 GitHub Secrets(PowerShell,gh 已登入)

每行執行後貼上對應的值按 Enter(值不會留在指令歷史):

```powershell
gh secret set CLOUDFLARE_API_TOKEN --repo bbdevin/trever-radar
gh secret set CLOUDFLARE_ACCOUNT_ID --repo bbdevin/trever-radar
gh secret set RADAR_FINMIND_TOKEN --repo bbdevin/trever-radar   # 選填,深歷史用
```

### 3. 手動觸發首次部署

```powershell
gh workflow run daily-market --repo bbdevin/trever-radar
gh run watch --repo bbdevin/trever-radar     # 看進度,約 5-10 分鐘
```

完成後網站在:**https://trever-radar.pages.dev**

### 4. 鎖上 A 私人測試版(2026-07-10 已決定,尚未實際設定)

目前狀態仍是**網站公開**。`noindex`/robots.txt 不是安全控制;未完成下列驗收前
不得宣稱網站已私有。完整計畫與旁路檢查見 `docs/21_private_beta_access_r2_plan.md`。

必須分別保護三類入口:

1. Pages project → Settings → General → Enable access policy,保護 preview deployments。
2. 依 Cloudflare Pages known issues 步驟,再建立/調整正式 `trever-radar.pages.dev` policy。
3. Zero Trust → Access → Applications → Self-hosted and private,建立
   `radar.techtrever.com/*` policy。
4. Allow 只填明確 email 名單;One-time PIN 可作登入方式,但不要 Allow Everyone 或所有有效 email。
5. 不為 `/data/*` 或 JSON 建 Bypass。

官方 Pages 三類網域設定說明:
https://developers.cloudflare.com/pages/platform/known-issues/#enable-access-on-your-pagesdev-domain

完成後用未授權無痕視窗逐一驗收:

- `https://radar.techtrever.com/`
- `https://radar.techtrever.com/data/radar.json`
- `https://trever-radar.pages.dev/`
- 任一 `<deployment>.trever-radar.pages.dev` preview URL

四者都必須先停在 Access;再用白名單 email 驗證頁面、Supabase watchlist、
GitHub Actions deploy 與 Cloudflare scheduler 仍正常。

## 之後的日常

什麼都不用做。每交易日依交易所公布時間分批自動更新(14:10/16:10/17:40/21:00,見 `docs/08_scheduler_jobs.md` §0)+ 部署。程式或 UI 修正 push 到 `main` 會立刻用現有 DB 重建 JSON 並部署,不會重抓資料。手機開網址就能看。

## 備援與注意

- Actions cache 被清(7 天未跑或超額)→ 自動從 release 備份還原,無感
- 想手動重跑某階段:`gh workflow run daily-branches`(或對應 workflow 名)
- 換電腦開發:`gh release download db-backup` 拿最新 DB
- **不要**把網址公開張貼(交易所資料授權 + 非投顧原則,見 docs/10)

## 沒選的選項(為什麼)

- **GitHub Pages**:私有 repo 免費方案不能開,且無登入
- **Vercel**:部署可行,但免費版沒有「訪客 email 登入」;要用的話網站等於公開
- **VPS**:月 USD 5–20,對純盤後批次產品是浪費;V2 盤中 worker 也定案跑本機
