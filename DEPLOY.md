# 上線部署指南(全免費)

架構:GitHub Actions(每交易日 17:30 / 21:00 台北自動抓資料 + 建站;`main` push 只重建/部署、不抓資料)→ Cloudflare Pages(靜態網站)→ Cloudflare Access(email 白名單登入)。

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
gh workflow run nightly-radar --repo bbdevin/trever-radar
gh run watch --repo bbdevin/trever-radar     # 看進度,約 5-10 分鐘
```

完成後網站在:**https://trever-radar.pages.dev**

### 4. 鎖上登入(2026-07-07 使用者決定:先公開、之後再鎖)

目前狀態:**網站公開**(僅靠網址不外流 + noindex/robots.txt 擋搜尋引擎)。
要分享給朋友、或想恢復私有時,照以下步驟開 Access(隨時可做,約 10 分鐘):

Cloudflare Access 免費 50 人,訪客要輸入 email 收一次性 PIN 才能進:

1. https://one.dash.cloudflare.com → 選 Zero Trust(首次會要你選免費方案)
2. Access → Applications → **Add an application** → Self-hosted
3. Application domain:`trever-radar.pages.dev`;再加一條 `*.trever-radar.pages.dev`(擋預覽網址)
4. Identity providers:勾 **One-time PIN**
5. Add policy:Action = Allow;Include = Emails → 填你和朋友的 email(≤10 個)
6. 儲存。完成——不在名單上的人連首頁都看不到

## 之後的日常

什麼都不用做。每交易日 17:30 自動更新 + 部署,21:00 補一次晚公布的資料。程式或 UI 修正 push 到 `main` 會立刻用現有 DB 重建 JSON 並部署,不會重抓資料。手機開網址就能看。

## 備援與注意

- Actions cache 被清(7 天未跑或超額)→ 自動從 release 備份還原,無感
- 想手動重跑:`gh workflow run nightly-radar`
- 換電腦開發:`gh release download db-backup` 拿最新 DB
- **不要**把網址公開張貼(交易所資料授權 + 非投顧原則,見 docs/10)

## 沒選的選項(為什麼)

- **GitHub Pages**:私有 repo 免費方案不能開,且無登入
- **Vercel**:部署可行,但免費版沒有「訪客 email 登入」;要用的話網站等於公開
- **VPS**:月 USD 5–20,對純盤後批次產品是浪費;V2 盤中 worker 也定案跑本機
