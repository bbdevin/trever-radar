# VPS 設定手冊(Plan B v3 — Workers 資料層 + Google Drive 備份)

> 對應 `docs/31_plan_b_vps_data_home.md` v3。本檔記錄 2026-07-15 實際走過的完整設定步驟,
> 供日後重灌 VPS、換機、憑證輪替時照做。日常排程腳本(cron)由 WP-B2 補進本檔。
> 環境:Rocky Linux(RackNerd VPS),repo 位於 `~/trever-radar`。

## 0. 這台 VPS 的角色

- `data/radar.db` 唯一常駐、唯一寫者(單一寫者原則,docs/31 §1)。
- 每輪管線跑完 `export-json` 後,用 `wrangler deploy` 把 JSON 當 Cloudflare Worker 靜態資產上傳
  → `radar.techtrever.com/data/*` 即傳即生效(cutover 前只掛影子路由 `/data-preview/*`)。
- 每週六快照上 Google Drive(唯一雲端備份)。
- **不** build 前端、**不**開對外 port、**不**持有 Pages/DNS 權限。

## 1. Cloudflare API token(一次性,瀏覽器)

1. Cloudflare Dashboard → 右上頭像 → **My Profile → API Tokens → 建立 Token**。
2. 用範本「**編輯 Cloudflare Workers**」。
3. 修改:
   - 權限保留 `Workers 指令碼: 編輯` 與 `Workers 路由: 編輯`,其餘(KV/Tail 等)可刪。
   - 帳戶資源:選自己的帳戶(不要 All accounts)。
   - 區域資源:特定區域 → `techtrever.com`。
4. 建立後 token 值**只顯示一次**,立刻填進 VPS 的 `vps/.env`(下一節)。
5. Account ID:Dashboard 任一網域 Overview 右下「帳戶 ID」。

> 這顆 token 只能動 Workers scripts/routes,動不了 Pages/DNS/帳戶——資料與部署權限分離(docs/31 §5.1)。
> VPS 永不持有 Pages 部署 token。

## 2. `vps/.env`(一次性)

```bash
cd ~/trever-radar
git pull --ff-only
cp vps/.env.example vps/.env
nano vps/.env        # 填 CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID / NTFY
chmod 600 vps/.env
```

- 已被 `.gitignore` 涵蓋,絕不 commit、絕不進 GitHub secrets。
- **wrangler 不會自動讀這檔**——手動操作前要先載入:

```bash
set -a; source ~/trever-radar/vps/.env; set +a
```

## 3. node LTS(一次性,Rocky/dnf)

```bash
curl -fsSL https://rpm.nodesource.com/setup_22.x | sudo bash -
sudo dnf install -y nodejs
node -v
```

只為 `npx wrangler` 用,不裝其他前端工具鏈。

## 4. rclone + Google Drive remote(一次性)

```bash
curl https://rclone.org/install.sh | sudo bash
# 裝不動的備案:sudo dnf install -y epel-release && sudo dnf install -y rclone
rclone config
```

互動流程(VPS 無瀏覽器,OAuth 要繞到本機做):

| 提示 | 輸入 |
|---|---|
| `n` 新增 remote,名稱 | `gdrive` |
| Storage 類型 | `drive`(Google Drive) |
| `client_id` / `client_secret` | **Enter 留空**(內建 key 較慢,週備份夠用) |
| `scope` | `1`(full access) |
| 其餘(service_account 等) | 一路 Enter |
| `Edit advanced config?` | `n` |
| `Use auto config?` | **`n`**(關鍵!VPS 無瀏覽器) |

接著 VPS 會印一串指令,例如 `rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlIn0"`
(那串 base64 是參數不是結果)。到 **Windows 本機**:

```powershell
winget install Rclone.Rclone   # 本機沒裝過才需要;裝完開新 terminal
rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlIn0"
```

瀏覽器自動開 → 登入放備份的 Google 帳號 → 允許 → 本機印出
`--->` 與 `<---End paste` 之間的一段 token JSON → 整段複製,貼回 VPS 正在等的
`config_token>` 提示 → `y` → `q`。

驗證(**注意 remote 結尾有冒號**,少冒號會被當本地資料夾):

```bash
rclone lsd gdrive:
```

搞砸重來:`Ctrl+C` 中斷 → `rclone config delete gdrive` → `rclone config` 重跑。
token JSON 存於 `~/.config/rclone/rclone.conf`,屬 VPS 側金鑰,同 `.env` 紀律。

## 5. 資料 deploy(首次手動;日後由 cron script 執行)

```bash
cd ~/trever-radar
git pull --ff-only

# 首次(或 requirements.txt 變更後)build 管線映像:
docker build -t radar-pipeline pipeline

# 產出 JSON。export-json 對 DB 唯讀,WAL + busy timeout 下與回補/日常匯入「並行安全」
# (既有驗證事實,雲端每晚本來就邊寫邊匯出)——不必等回補結束。
# 容器內以 /app 為 repo 根;第三個 -v(web/public/data)必掛,否則 JSON 寫在容器裡直接丟失:
mkdir -p web/public/data
docker run --rm \
  -v ~/trever-radar/pipeline:/app/pipeline \
  -v ~/trever-radar/data:/app/data \
  -v ~/trever-radar/web/public/data:/app/web/public/data \
  radar-pipeline python -m radar export-json
ls web/public/data/           # 應有 radar.json、meta.json 等

set -a; source vps/.env; set +a
cd cloudflare-data-worker
npx wrangler deploy           # 資產內容 hash 去重,只上傳變動檔
```

驗收兩測(缺一不可,docs/31 §3.2):

1. 已登入 Access 的瀏覽器開 `https://radar.techtrever.com/data-preview/radar.json` → 回 JSON。
2. 無痕視窗開同一網址 → 被踢到 Cloudflare Access 登入頁(302),**不是** JSON。

cutover(WP-B3,需使用者確認)時:解除 `cloudflare-data-worker/wrangler.toml` 內
`/data/*` 路由註解 → 重 deploy 一次。

## 6. DB 快照上 Google Drive(首份手動;日後每週六 cron)

**前置:必須沒有任何程式在寫 DB**(回補、匯入輪全部結束)。
export-json 可以並行,但**快照 gzip 不行**——寫入中壓檔會拿到不一致的副本。

```bash
cd ~/trever-radar
# 用管線映像跑 SQL,主機不需裝 sqlite3:
docker run --rm -v ~/trever-radar/data:/app/data radar-pipeline \
  python -c "import sqlite3; print(sqlite3.connect('/app/data/radar.db').execute('PRAGMA wal_checkpoint(TRUNCATE);').fetchone())"
docker run --rm -v ~/trever-radar/data:/app/data radar-pipeline \
  python -c "import sqlite3; print(sqlite3.connect('/app/data/radar.db').execute('PRAGMA integrity_check;').fetchone()[0])"
# ↑ 必須輸出 ok,不 ok 絕不上傳
gzip -kf data/radar.db                            # 產生 data/radar.db.gz,原檔保留
rclone copy data/radar.db.gz gdrive:trever-radar-backup/
rclone ls gdrive:trever-radar-backup/             # 列得出檔案才算完成
```

日後每週六 05:00 由 `vps/scripts/weekly-backup.sh` 自動執行同一流程(§9)。

retention:保留最近 4 份 + 每月 1 份,超標刪最舊(docs/31 §4)。
單雲取捨已定案:Google 帳號出事=只剩 VPS 本機一份,知情接受;要補第二朵雲時
用 Backblaze B2 / MEGA(免卡)加一行 `rclone copy` 即可。

## 7. WP-B1 收尾(快照就位後,交給 agent)

首份快照確認在 Drive 上之後,由 agent 執行(絕不可在快照就位前做):

```bash
gh release view db-backup --repo bbdevin/trever-radar
gh release delete-asset db-backup radar.db.gz -y --repo bbdevin/trever-radar
```

目的:repo 目前 public,整包 DB 任何人可下載,踩 `docs/10` §3 紅線。

## 8. 災難還原(任何機器)

```bash
rclone copy gdrive:trever-radar-backup/radar.db.gz .
gunzip radar.db.gz
sqlite3 radar.db "PRAGMA integrity_check;"        # ok 才能用
# 放回 ~/trever-radar/data/radar.db → 跑 export-json → wrangler deploy 即恢復供資料
# 快照之後缺的幾天:官方源 backfill --days N + 分點按日補抓 + 指標/分數重算(docs/31 §4)
```

## 9. 每日排程(WP-B2,cron)

腳本在 `vps/scripts/`,一支 cron 項對應一支 script,全部鏡像現行 5 支 workflow 的指令序:

| Script | 時刻(台北) | 對應 workflow |
|---|---|---|
| `daily-market.sh` | 14:10 一–五 | daily-market(quotes→權證彙總→指標→分數→週一題材→export→deploy) |
| `daily-insti.sh` | 16:10 一–五 | daily-insti(法人→權證主檔→分數→export→deploy) |
| `daily-branches.sh` | 17:40 + 21:00 一–五 | daily-branches(margin/insti 補抓→分點爬蟲→分點統計→分數→績效→export→prune→deploy) |
| `daily-margin.sh` | 22:10 一–五 | daily-margin(融資券保底→分數→績效→export→deploy) |
| `data-backfill.sh` | 01:10 每日 | data-backfill task=deep(深歷史增量) |
| `weekly-backup.sh` | 週六 05:00 | (新)checkpoint→integrity_check→gzip→Drive+retention |

共用機制(`lib.sh`):
- **flock 互斥**:`/tmp/radar-db.lock`,搶不到=跳過本輪+ntfy 通知(防上一輪超時堆疊)。
- **開輪 `git pull --ff-only` + docker build**(layer cache,requirements 沒變近零成本)——舊碼算舊 reasons 的既有教訓。
- **失敗 → ntfy High 告警,成功靜默**(週備份成功發一則 default 摘要)。
- 非交易日:importer 靠 NoDataError 安全空跑,不手刻假日曆(既有定案)。
- deploy 憑證只在主機(`vps/.env`),容器只拿到 `RADAR_FINMIND_TOKEN`——權限分離。

安裝(一次):

```bash
cd ~/trever-radar
git pull --ff-only
chmod +x vps/scripts/*.sh
cd cloudflare-data-worker && npm install --no-audit --no-fund && cd ..   # 釘 wrangler 版本
crontab -e   # 貼入 vps/scripts/crontab.example 內容(路徑換成實際家目錄)
crontab -l   # 確認
```

手動補跑任一輪:直接執行對應 script,例 `vps/scripts/daily-market.sh`。
看狀態:`tail -f ~/radar-cron.log`、`docker ps -a`、ntfy 通知。

**影子驗證(cutover 前必過,docs/31 WP-B2)**:cron 全開後連續 2–3 個交易日,
每日收盤後比對 `https://radar.techtrever.com/data-preview/radar.json` 與正式站
`/data/radar.json` 的 freshness/榜單檔數一致(允許分鐘級時差);ntfy 無錯誤告警。
過了才可向使用者提請 WP-B3 cutover。

## 10. 常見坑(本次實際踩過)

- `rclone lsd gdrive`(沒冒號)→ 被當本地資料夾,報 `directory not found`。要 `gdrive:`。
- `Use auto config?` 按成 `y` → 卡住等瀏覽器。`Ctrl+C` → `rclone config delete gdrive` 重來。
- `rclone authorize` 那串 `eyJ...` 是要帶去本機的**參數**,不是 token 本身。
- wrangler 讀不到 token → 忘了 `set -a; source vps/.env; set +a`。
- 首次 `wrangler deploy` 失敗說目錄不存在 → `web/public/data/` 還沒有 export 產物,先跑 export-json。

## 11. 盤中訊號雷達 worker(docs/24 Part A,獨立於 B 案但同一台 VPS)

平日 08:50 啟動、13:35 自動收工,抓 Fugle 行情判定訊號寫入 Supabase,首頁盤中面板即時顯示。
一次性設定(docker build + `.env` 六行,含 2026-07-13 Access 上線後必填的 Access service token)
完整步驟見 `docs/vps_backfill_plan.md` Step 5;範本檔 `pipeline/intraday/.env.example`。
cron 行已在本檔 §9 的 `crontab.example` 裡,跟資料 cron 一起裝,不用另外處理。

**卡住的原因(2026-07-15 排查)**:Step 5 寫於 Access 上線前,`.env` 少了 Access service token
兩行,worker 抓 `radar.json` 會被 Access 擋成 403 直接 fatal exit——這才是「VPS 還是沒跑盤中訊號」
的真正原因,不是 cron 或 Docker 設定的問題。

✅ **2026-07-16 已解**:Cloudflare Access Service Token 已建立並加進既有 Access Application 的
原則(獨立一條「包含(或)= Service Token」規則,與既有 Google 信箱白名單原則互不影響,步驟已
記在 `.env.example` 內註解供之後輪替參考)。剩下是 VPS 端把 Client ID/Secret 填進
`pipeline/intraday/.env` 並跑冒煙測試(Step 5-e),詳細指令見 `docs/vps_backfill_plan.md` Step 5。
