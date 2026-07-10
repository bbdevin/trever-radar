# 21 私人測試版 Access 與 R2 計畫(2026-07-10 定案)

> 使用者已確認目前只做 **A 私人測試版**,不規劃公開註冊、付費牆或會員分級。
> 本文件是 Cloudflare Access 與 R2/SQLite 儲存邊界的 source of truth。
> 本次只完成規劃文件;建立 Access policy、R2 bucket、GitHub secrets 或修改 workflow
> 都是高風險外部狀態變更,必須由使用者另行確認後分階段執行。

## 1. 決策摘要

1. **整站私人化**:Cloudflare Access 保護首頁、所有頁面、`/data/*`、正式
   `pages.dev`、preview deployment 與 `radar.techtrever.com`。只允許明確 email 名單。
2. **Supabase 保留但不當安全邊界**:Google OAuth / watchlist 繼續提供個人自選;
   整站能否進入由 Cloudflare Access 決定。
3. **R2 不是資料庫引擎**:不能直接對 R2 裡的 `radar.db` 執行 SQLite SQL。
   R2 只存完整 SQLite 快照、未來拆出的 `branch_hist.db`、manifest/checksum 或靜態檔。
4. **短期不取代 Actions cache**:日常熱 DB 仍走 Actions cache;cache miss 仍先保留現有
   GitHub Release fallback。R2 先作 shadow backup,完成還原演練後才可加入 restore chain。
5. **不碰 WAL 安全修正**:任何 R2 上傳前仍必須執行既有
   `PRAGMA wal_checkpoint(TRUNCATE)`;不得只上傳主 DB 而遺漏未合併 WAL。
6. **保持零成本需容量紀律**:R2 Standard 免費額度為每月 10 GB-month。現有 DB
   快照適合,但五年分點 +7-9GB 再乘版本數後很可能超額,因此 P2 仍延後。

## 2. R2 能做與不能做

| 用途 | 判定 | 說明 |
|---|---|---|
| 存 `radar.db.gz` 備份 | ✅ 適合 | 大型單檔、耐久物件、可版本化 |
| 存未來 `branch_hist.db.gz` | ✅ 適合 | 但只作檔案快照;Actions/VPS 使用前仍要下載 |
| 存前端 JSON | ⏸️ 暫不做 | Access 已可保護 Pages;現在搬 R2只增加路由與權限複雜度 |
| 直接執行 SQLite 查詢 | ❌ 不行 | R2 是 object storage,不是掛載磁碟或 SQLite server |
| 多個 workflow 同時改同一 DB | ❌ 不行 | 仍需 `radar-db` concurrency 單寫者模型 |
| 取代 WAL checkpoint | ❌ 不行 | 上傳前必須合併 WAL |
| 立刻刪除 GitHub Release 備份 | ❌ 不行 | R2 至少通過兩次備份+還原演練後才評估 |

官方依據:

- R2 bucket 預設不公開;只有明確開啟 `r2.dev` 或 custom domain 才會曝露:
  <https://developers.cloudflare.com/r2/buckets/public-buckets/>
- R2 Standard 免費額度:10 GB-month、Class A 100萬、Class B 1000萬、免 egress:
  <https://developers.cloudflare.com/r2/pricing/>
- `wrangler r2 object put` 僅支援到 315MB;大型備份應用 rclone 或 S3 multipart:
  <https://developers.cloudflare.com/r2/objects/upload-objects/>

## 3. 私人測試版目標架構

```text
允許名單使用者
  → Cloudflare Access
      → radar.techtrever.com
      → trever-radar.pages.dev
      → *.<project>.pages.dev previews
          → Cloudflare Pages(static HTML/JS/JSON)
          → Supabase Auth + RLS watchlist(僅個人化)

GitHub Actions(單一 radar-db concurrency)
  → restore Actions cache
  → cache miss:未來 R2 verified snapshot
  → R2 miss/失敗:GitHub Release db-backup
  → import / compute / export / deploy
  → WAL checkpoint + cache save
  → 每週 verified snapshot → private R2(Standard)
```

**當前狀態不是上圖完成態**:網站仍公開、R2 尚未建立、restore chain 仍是
cache → GitHub Release。不得因本文件存在就宣稱已完成私人化或 R2 遷移。

## 4. Access 實作計畫

### A0. 範圍

必須保護三類入口,缺一不可:

1. 自訂網域:`radar.techtrever.com/*`
2. 正式 Pages 網域:`trever-radar.pages.dev/*`
3. 預覽/branch 網域:`*.trever-radar.pages.dev/*`

Cloudflare Pages 對 production `pages.dev`、preview deployment 與 custom domain 的
Access 設定是分開的。官方已知問題與完整步驟:
<https://developers.cloudflare.com/pages/platform/known-issues/#enable-access-on-your-pagesdev-domain>

### A1. Policy 原則

- Allow policy 只用**逐一列出的 email**。
- 不使用 `Include Everyone`。
- 不用「所有有效 email / One-time PIN」當唯一 Allow 條件;OTP 只是驗證方法,
  允許對象仍要是明確 email。
- 不為 `/data/*`、`*.json`、靜態資產建立 Bypass。
- 不使用涵蓋整個 `*.techtrever.com` 的過寬 policy,避免誤傷 scheduler Worker 或其他服務。
- Cloudflare Worker scheduler 網域維持原狀,不納入網站 Access application。

Access policy 官方說明與常見誤設:
<https://developers.cloudflare.com/cloudflare-one/access-controls/policies/>

### A2. 驗收

使用未在白名單的無痕視窗測試:

- `https://radar.techtrever.com/` → 必須停在 Access。
- `https://radar.techtrever.com/data/radar.json` → 必須停在 Access。
- `https://trever-radar.pages.dev/` → 必須停在 Access。
- 任一 preview URL → 必須停在 Access。

使用白名單 email 測試:

- Access 登入後首頁、stock、branch、watchlist 皆可讀。
- Supabase Google OAuth 登入/登出與 watchlist RLS 正常。
- GitHub Actions deploy 仍成功;Cloudflare Worker 仍能 dispatch workflows。
- 不存在任何可直接讀 JSON 的替代 hostname。

## 5. R2 儲存設計

### 5.1 Bucket

- 建議名稱:`trever-radar-private`
- Storage class:**Standard**(免費額度只適用 Standard)
- `r2.dev` Public Development URL:**Disabled**
- Custom domain:**不設定**
- 只透過 S3-compatible API/rclone 或受信任 Worker binding 存取
- R2 API token 限定該 bucket 的 Object Read/Write;不給帳號全域管理權
- Access key / secret 只放 GitHub Secrets 與必要 VPS secret,不得進 repo/前端

### 5.2 Object key

```text
radar-db/snapshots/2026/07/radar-20260710T174000Z-<sha12>.db.gz
radar-db/manifests/radar-20260710T174000Z.json
radar-db/current.json

# P2 仍延後;未經另案確認不得產生
branch-hist/snapshots/<timestamp>-<sha12>.db.gz
branch-hist/current.json
```

`current.json` 只是一個最後寫入的指標,至少包含:

- object key
- SHA-256
- compressed/uncompressed bytes
- SQLite `PRAGMA user_version`
- 資料日期/as_of
- 產生此快照的 git SHA
- created_at UTC

流程必須「先上傳不可變 snapshot → 驗證可讀 → 最後更新 current.json」。
不得直接覆寫唯一的 `current/radar.db.gz`,避免中斷時同時失去新舊版本。

### 5.3 上傳工具

DB 已約 1GB,不得用 Wrangler 單檔上傳。採以下之一:

1. **rclone(S3 backend,建議)**:可自動 multipart、重試與驗證。
2. AWS CLI / 其他 S3-compatible client multipart upload。

上傳前:

1. `PRAGMA wal_checkpoint(TRUNCATE)`
2. `PRAGMA quick_check`(每週上傳前)
3. gzip
4. `gzip -t`
5. 計算 SHA-256
6. 上傳 versioned object
7. 下載抽驗或 HEAD/size/checksum 比對
8. 更新 manifest/current pointer

還原後:

1. 驗 SHA-256
2. `gzip -t`
3. 解壓
4. `PRAGMA integrity_check`
5. 成功才取代工作 DB;失敗則退回 Release backup

### 5.4 容量與 retention

零成本目標不是把 10GB 用滿,而是保留安全餘裕:

- R2 總使用量警戒線:8 GB-month
- `radar.db.gz`:保留 current + previous + 1 份月快照,實際版本數依壓縮後大小調整
- 用 lifecycle policy 刪除超過 retention 的舊 snapshot
- incomplete multipart uploads 使用預設 7 日清理或更短 policy
- P2 `branch_hist.db` 上線前重新計算壓縮後容量;若 current+previous 會超 8GB,
  就不是零成本方案,需縮短歷史或接受付費

## 6. R2 分階段導入

### R0:建立資源(外部狀態,待確認)

- 建 private Standard bucket
- 建 bucket-scoped API token
- 設 GitHub/VPS secrets
- 確認 public access disabled

### R1:Shadow backup

- 每週既有 Release backup 成功後,再鏡像一份到 R2
- restore 邏輯完全不改
- 保留現有 GitHub Release 與 cache
- 連續完成至少 2 份 verified snapshot

### R2:還原演練

- 在暫存目錄或 VPS 下載 R2 snapshot
- 完成 checksum/gzip/integrity_check
- 比對關鍵表最大日期與筆數
- 不清 cache、不覆蓋正式 release、不部署

### R3:加入 fallback chain(另案高風險)

只有 R1/R2 通過後才提案修改五支 workflow:

```text
Actions cache → R2 current verified snapshot → GitHub Release → 明確失敗
```

- R2 讀取失敗要 fail closed 或安全 fallback,不能產生空 DB 繼續部署
- Release 至少再保留一段觀察期
- WAL/cache/release 原有順序不得因抽 reusable step 而改變

### R4:分點歷史拆檔(延後)

只有使用者重新批准 P2 後才做:

- `radar.db`:日常所需近期資料與評分
- `branch_hist.db`:深分點歷史,由 VPS 更新、R2 保存
- Actions 日常不必每跑下載完整 `branch_hist.db`;需要統計時才在專門 job/VPS 使用

這一階段是 schema/資料搬移與大 backfill,必須另走 `docs/17` 高風險流程。

## 7. 不採用的替代方案

### 把 R2 當即時 SQLite 磁碟

不採用。R2 沒有 SQLite 所需的隨機讀寫、檔案鎖與交易語意。

### 每支 workflow 都下載/上傳完整 DB 到 R2

暫不採用。會把目前 cache 的快速續存退化成每階段搬運約 1GB,增加時間與中斷面。

### 將 R2 bucket 設公開供前端直接讀

私人測試版不需要。Pages 已由 Access 保護;R2 backup 不應有 public URL。

### 立刻用 R2 取代 GitHub Release

不採用。沒有 restore drill 的備份不算備份。

## 8. 執行順序與所有權

1. **先完成 Access A0-A2**:這才真正解決策略/JSON 外洩。
2. B 方案 Phase 1-3 可照 `docs/20` 繼續,與 R2 不互相阻塞。
3. R2 R0-R2 可獨立進行,先 shadow 不改正式 restore。
4. R3 workflow 變更最後做,且需 Reviewer 完整審查。
5. R4/P2 保持延後。

每一階段完成後更新本文件狀態與 `docs/STATUS.md`,不得只留在對話。

## 9. Phase 狀態

| Phase | 狀態 |
|---|---|
| 文件規劃 | ✅ 完成(2026-07-10) |
| Access A0-A2 | ⏳ 待使用者確認並操作/授權 |
| R2 R0 建資源 | ⏳ 待確認 |
| R2 R1 Shadow backup | ⏳ 待 R0 |
| R2 R2 Restore drill | ⏳ 待 R1 兩份快照 |
| R2 R3 Workflow fallback | ⛔ 未授權 |
| R2 R4 / 分點 P2 | ⛔ 延後 |
