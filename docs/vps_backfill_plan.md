# VPS 操作手冊 — 分點歷史回補 + 盤中 worker(2026-07-12 整併)

> 本檔是 **VPS 上所有操作的唯一手冊**(原 `docs/handoff_intraday_vps.md` 已併入本檔 Step 5)。
> 每一步都是「複製 → 貼上 → 按 Enter」。看到不一樣的輸出就停下來,把畫面貼給 AI。

---

## 🎯 現在待辦總覽(2026-07-12,依序)

| # | 事項 | 指令在哪 | 狀態 |
|---|---|---|---|
| 1 | 等 backfill-branches 跑完(`docker logs --tail 5 radar-backfill`;已回補到 2024-10) | Step 3 | ⏳ 跑著 |
| 2 | **VPS 一次做完**補洞+全部重算(4c,先 `git pull`;可選 4b 權證分點/4d 還原因子)→ 上傳+清 cache(4e) | Step 4 | 等 1 |
| 3 | 部署盤中 worker(docker build 一次 + `.env` 一次 + cron 08:50) | **Step 5** | 可與 2 並行 |
| 4 | 非盤中冒煙測試 worker | Step 5-e | 等 3 |
| 5 | 跟 AI 說「完成」→ AI 驗證全站 + Phase 2 差異報告 | — | 等 2+4 |

已完成 ✅:Supabase SQL(intraday_signals/worker_heartbeat)已執行;Fugle 金鑰已輪替(舊 key 實測 401 失效,git 歷史中為死 key);金鑰一律只放 VPS `.env`(gitignore 保護,`git pull` 永不影響它——使用者 2026-07-12 定案不入 repo)。

---

## ⚠️ 2026-07-09:遇到「database disk image is malformed」怎麼辦

**已修好,不是你操作錯。** 根因:資料庫開 WAL 模式,備份只打包主檔、沒合併 WAL 側檔,導致下載下來的 `radar.db.gz` 本身就不完整。已修管線(每次備份前強制合併 WAL)並重新產出一份乾淨備份。

你要做的:
1. **刪掉 VPS 上舊的容器和資料庫**:
   ```bash
   docker rm -f radar-backfill
   rm -f data/radar.db data/radar.db.gz data/radar.db-wal data/radar.db-shm
   ```
2. **重新下載**(Step 1 的下載指令再跑一次):
   ```bash
   curl -L https://github.com/bbdevin/trever-radar/releases/download/db-backup/radar.db.gz -o data/radar.db.gz
   gunzip data/radar.db.gz
   ```
3. **檢查完整性**(確認這次是好的再啟動):
   ```bash
   docker run --rm -v $(pwd)/data:/d python:3.11 python -c "import sqlite3; print(sqlite3.connect('/d/radar.db').execute('PRAGMA integrity_check').fetchone())"
   ```
   輸出 `('ok',)` 才能繼續;不是的話跟 AI 說,先別跑 Step 2。
4. 確認 OK 後,照 **Step 2** 重新啟動回補(指令不變)。

---

## 事前理解(30 秒版)

- 抓什麼:MoneyDJ 公開分點頁,5 個券商鏡像站輪流打,每秒 1 個請求(單站 5 秒一次,很禮貌)
- P1 = 成交金額前 500 檔 × 2 年 ≈ 24.5 萬個請求 ≈ **連跑 3 天**
- 中斷沒關係:重跑同一個指令會自動從缺的地方繼續
- 資料來源實測只回溯到 2021 年中 → 5 年就是免費上限,更早沒有
- 跑完會自動推播通知到你手機

---

## Step 0:通知管道二選一(2–5 分鐘)

### 方案 A:ntfy(手機裝一個 App,最快)

1. 手機商店搜尋 **ntfy** 安裝(免費、免註冊)
2. 打開 App → 右下 **+** → Subscribe to topic
3. 主題名輸入一個**只有你知道的長字串**,例如:`trever-radar-x8k2m9q7`
   (主題名就是密碼,太短會被別人猜到亂發通知)
4. 記住這個字串,Step 2 會用到

### 方案 B:n8n(不想裝 App;用你 VPS 上已有的 n8n 寄 Email 給你)

1. 開你的 n8n 網頁 → **New workflow**
2. 加第一個節點:**Webhook**
   - HTTP Method:`GET`
   - Path:填 `radar-done`
3. 加第二個節點(和 Webhook 連起來):**Send Email**(SMTP)或 **Gmail**
   - Gmail 節點照它的指示按 OAuth 授權一次即可
   - 收件人:你的信箱;主旨:`Radar 回補通知`
   - 內文填表達式:`{{ $json.query.msg }}`(會顯示完成或失敗訊息)
4. 右上把 workflow 切到 **Active**
5. 點 Webhook 節點,複製 **Production URL**(長得像 `https://你的n8n網址/webhook/radar-done`),Step 2 會用到
6. 先測試:瀏覽器開 `https://你的n8n網址/webhook/radar-done?msg=測試`,幾秒內應收到信

> 進階:第二個節點想接 **LINE** 也行(HTTP Request 節點打 LINE Messaging API)——那需要先開 LINE 官方帳號 channel,等我們做 LINE 推播功能時會一起弄,現在用 Email 最省事。

---

## Step 1:SSH 進 VPS,下載專案與資料庫(5 分鐘)

逐段貼上:

```bash
git clone https://github.com/bbdevin/trever-radar.git
cd trever-radar
mkdir -p data
curl -L https://github.com/bbdevin/trever-radar/releases/download/db-backup/radar.db.gz -o data/radar.db.gz
gunzip data/radar.db.gz
```

- `git clone` 是私有 repo,會要求登入:帳號輸入 `bbdevin`,密碼要用 GitHub **Personal Access Token**(github.com → Settings → Developer settings → Personal access tokens → Generate new token (classic),勾 `repo` 權限,產生後複製貼上當密碼)
- 成功標準:`ls data` 看得到 `radar.db`(約 1GB)

---

## Step 2:啟動回補(1 分鐘,之後它自己跑 3 天)

**先把第一行的主題名改成你 Step 0 取的那個**,再整段貼上:

```bash
NTFY=trever-radar-x8k2m9q7

docker run -d --name radar-backfill --restart unless-stopped \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    if python -m radar backfill-branches --top 500 --days 490 --sleep 1.0; then \
      curl -s -H 'Title: Radar P1 完成' -d '分點2年回補完成,回VPS執行 Step 4 上傳' ntfy.sh/$NTFY; \
    else \
      curl -s -H 'Title: Radar P1 中斷' -H 'Priority: high' -d '執行 docker logs radar-backfill 查原因' ntfy.sh/$NTFY; \
    fi"
```

- 成功標準:輸出一長串容器 ID(64 個字母數字)
- 之後**可以直接關掉 SSH 視窗**,它在背景跑;VPS 重開機也會自動續跑
- 想確認通知通不通,先手動測一發:
  ```bash
  curl -d "測試:通知管道正常" ntfy.sh/$NTFY
  ```
  手機應該幾秒內跳出來。沒跳 = 主題名打錯或 App 沒訂閱。

---

## Step 3:隨時看進度(可選)

```bash
docker logs --tail 5 radar-backfill
```

會看到類似:

```
backfill-branches 2026-05-14: missing=496 done, total fetched=41230
```

**日期越走越舊 = 進度**。從今天往回走,走到 **2024 年 7 月附近**就是完成(490 個交易日)。

想看精確數字(已累積幾個交易日/最舊到哪天):

```bash
docker run --rm -v $(pwd)/data:/d python:3.11 \
  python -c "import sqlite3; print(sqlite3.connect('/d/radar.db').execute('SELECT COUNT(DISTINCT date), MIN(date) FROM branch_trades').fetchone())"
```

輸出 `(490, '2024-07-xx')` 左右 = 完成。

---

## Step 4:抓完後 → 在 VPS 一次做完所有補洞與重算,再上傳(2026-07-12 改版)

> **改版說明(使用者決定)**:重算不再交給雲端 gh workflow——近日補洞、題材、指標、分數、績效、分點統計**全部先在 VPS 做完**,一次上傳,雲端之後只負責每日增量。好處:省 ~120 分鐘 Actions 額度、不用排隊等 radar-db 併發群、一條指令一次到位。原「上傳後跑 task=themes / indicators-only」流程降級為備援(見 4f 附註)。

SSH 回 VPS,逐段貼:

### 4a. 安裝 GitHub CLI 並登入(依你系統二選一，若已裝可跳過)

```bash
# Debian/Ubuntu:
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update && sudo apt install gh -y

# AlmaLinux/Rocky/CentOS:
sudo dnf install 'dnf-command(config-manager)' -y
sudo dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
sudo dnf install gh -y
```

```bash
gh auth login
# 選 GitHub.com → HTTPS → Paste an authentication token → 貼 Step 1 的同一個 token
```

### 4b.(可選,建議)權證分點半年回補——趁上傳前一起補

約 6.5 小時,中斷可續;想讓網站 120D 權證大戶資料一次到位就跑,不想等也可跳過(之後隨時可補跑再上傳一次):

```bash
cd ~/trever-radar && git pull
docker run --rm --name radar-warrant-backfill \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar backfill-warrant-branches --top 200 --days 120 --sleep 1.2"
```

### 4c. 一次重算鏈(必跑;約 2–2.5 小時,背景執行+手機通知)

補近 7 日行情/法人/融資券 → 題材 → 權證彙總 → 指標全歷史 → 分數 → 績效 → 分點統計,一條指令做完(**第一行主題名改成你 Step 0 的**):

```bash
cd ~/trever-radar && git pull
NTFY=trever-radar-x8k2m9q7

docker run -d --name radar-finalize \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar backfill --days 7 && \
    for i in 0 1 2 3 4 5 6; do python -m radar import-daily --date \$(date -d \"-\$i day\" +%Y%m%d) --datasets insti,margin || true; done && \
    python -m radar import-themes && \
    python -m radar aggregate-warrants && \
    python -m radar compute-indicators --all && \
    python -m radar compute-scores && \
    python -m radar compute-performance && \
    python -m radar compute-branch-stats && \
    curl -s -H 'Title: Radar 重算完成' -d '重算鏈全部完成,執行 4e 上傳' ntfy.sh/$NTFY || \
    curl -s -H 'Title: Radar 重算中斷' -H 'Priority: high' -d '執行 docker logs radar-finalize 查原因' ntfy.sh/$NTFY"
```

- 進度:`docker logs --tail 10 radar-finalize`
- ⚠️ `git pull` **必須**:2026-07-11 修了 NULL 資料整支崩潰(舊碼跑 compute-indicators --all 會炸)且策略邏輯在程式碼裡。

#### ⚠️ 若 compute-branch-stats 被 Killed(OOM)

**症狀**:`docker logs radar-finalize` 尾端出現 `Killed`(bash 顯示 `51 Killed`),前面各步都成功,只有 `compute-branch-stats` 沒跑完。

**原因(已修復,commit `<待填>`)**:舊版 `compute_all()` 一次把整張 `branch_trades`(回補後約 600 萬列)連同全部 500 檔的完整價格序列載進記憶體,1–2GB RAM 的 VPS 直接被 OOM killer 殺掉。現已改為**串流式逐檔處理**:一次只常駐單一個股的價格序列與其 branch_trades 列(單檔約 1.5 萬列),峰值記憶體改由「單檔資料(數 MB)+ 跨檔事件池」界定,不再隨全表線性成長。合成 1.2M 列(比生產密集)實測:舊版光是全表 fetchall 的 Python 峰值就達 488MB(且舊版還要在其上再疊 stock_ctx 與 by_bs 兩份巨型結構),新版全程峰值 161.7MB。行為零變化,既有測試全過。

**重跑**(`git pull` 拿到修復後,單獨補這一步,跑完接 4e 上傳):

```bash
cd ~/trever-radar && git pull
docker run --rm --name radar-branchstats \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && python -m radar compute-branch-stats"
```

### 4d.(可選)還原因子(除權息 adj_factor,3–4 小時,需 FinMind token)

不急可跳過(之後在雲端 `gh workflow run data-backfill.yml -f task=adjust` 補);要一起做就在 4c 完成後:

```bash
docker run -d --name radar-adjust \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -e RADAR_FINMIND_TOKEN=<你的FinMind token> \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar compute-adjustments --all --sleep 6.5 && \
    python -m radar compute-indicators --all"
```

### 4e. 壓縮上傳 + 讓雲端切換到新資料庫(兩段都要跑)

```bash
cd ~/trever-radar
gzip -kf data/radar.db
gh release upload db-backup data/radar.db.gz --clobber --repo bbdevin/trever-radar
gh cache delete --all --repo bbdevin/trever-radar
```
> ⚠️ **`gh cache delete` 不跑,雲端會繼續用舊快取,不會下載你剛上傳的新資料庫!**

### 4f. 回報與清理

跟 AI 說「**上傳完成**」→ AI 會推一個 commit 觸發 deploy(雲端 cache miss → 撈你的新 release → 匯出 JSON 上線),然後驗證全站(S1–S10 策略榜、題材、分點 2 年聚合、追蹤視角、Armed 池)。清容器:

```bash
docker rm -f radar-backfill radar-finalize 2>/dev/null; docker rm -f radar-warrant-backfill radar-adjust 2>/dev/null
```

> 備援註記:雲端 `task=themes` / `task=indicators-only` / `task=adjust` 仍存在——日後只改了算分程式、不想開 VPS 時可用;正常流程用不到。
> ⚠️ 近日缺口**不能**靠 `task=deep` 補(deep 對已拉深股票整檔跳過),一律走 4c 的 `backfill --days 7`。

---

## Step 5:盤中 worker 部署(2026-07-12 新增;一次設定,之後只要 `git pull`)

盤中訊號雷達(docs/24 Part A)的 worker 跑在這台 VPS:平日 08:50 啟動、13:35 自動收工,抓 Fugle 行情判定 I-1~I-4 訊號寫入 Supabase,網站首頁盤中面板即時顯示。前置(已完成 ✅):Supabase SQL 已執行、Fugle 新金鑰已備。

### 5-a. 更新程式 + build worker 映像(一次;2026-07-12 改為 docker 統一)

依賴預先烤進映像:08:50 啟動不碰 PyPI(網路慢/掛不會害 worker 缺席);映像內建 `TZ=Asia/Taipei`(worker 以本機時間判斷 13:35 收工,容器預設 UTC 會多跑 8 小時——Dockerfile 已處理)。

```bash
cd ~/trever-radar && git pull
docker build -t radar-worker pipeline/intraday
```

> 之後只要 `git pull` 拉到 `worker.py` 或 `Dockerfile` 的變更,重跑上面這兩行 rebuild 即可;沒改就不用。

### 5-b. 設 `.env`(一次;之後 `git pull` 永遠不會動到它)

```bash
nano ~/trever-radar/pipeline/intraday/.env
```

貼入以下四行(**尖括號換成你的實際值**,Supabase service key 在 Dashboard → Settings → API → `service_role`):

```
FUGLE_API_KEY=<你 2026-07-12 輪替後的新 Fugle key>
SUPABASE_URL=https://eroycvbgfitvyulfbbnw.supabase.co
SUPABASE_KEY=<Supabase service_role key>
RADAR_JSON_URL=https://trever-radar.pages.dev/data/radar.json
```

> 可選:之後 Cloudflare Access 上線,再加兩行 `CF_ACCESS_CLIENT_ID=` / `CF_ACCESS_CLIENT_SECRET=`(service token),worker 會自動夾帶 header 穿透。

### 5-c. 時區確認(cron 的 08:50/13:35 是台北時間)

```bash
timedatectl | grep "Time zone"
# 不是 Asia/Taipei 就執行:
sudo timedatectl set-timezone Asia/Taipei
```

### 5-d. cron 排程(平日 08:50 啟動,一次)

```bash
crontab -e
```

加入一行(`--env-file` 讀 5-b 設定的 `.env`;`--rm` 收工自動清容器):

```cron
50 8 * * 1-5 docker run --rm --name radar-worker --env-file /home/huang/trever-radar/pipeline/intraday/.env radar-worker >> /home/huang/radar-worker.log 2>&1
```

> cron 的 08:50 依 **VPS 主機**時鐘,主機時區也要是台北(見 5-c);容器內時區映像已內建。

### 5-e. 冒煙測試(非盤中時段跑一次,一分鐘)

```bash
docker run --rm --name radar-worker-test --env-file ~/trever-radar/pipeline/intraday/.env radar-worker
```

- 成功標準:log 顯示抓到 radar.json(或非交易時段的等待訊息)、無 Supabase 連線錯誤;開網站登入後,首頁盤中面板 worker 狀態轉 **online** → `Ctrl+C` 結束。
- 缺 `.env` 鍵會 fatal exit 並印出缺哪個;403 會指引檢查 `RADAR_JSON_URL` / Access token。

### 5-f. 韌性行為(不用做事,知道就好)

- radar.json 抓取失敗會退避重試 3 次;已有上次成功名單就沿用續跑;首次啟動即失敗才會結束。
- 之後程式更新只要 `cd ~/trever-radar && git pull`——`.env` 與 cron 都不受影響;僅當 `worker.py`/`Dockerfile` 有變更時補一句 `docker build -t radar-worker pipeline/intraday`。

---

## 隱藏版：權證大戶半年回補 (2026-07-10 新增)

如果您想要觀察「過去半年權證大戶佈局後尚未出清」的籌碼，我們新增了一支專用指令。這支指令會針對「大盤成交值前 200 大的活躍權證」，往回深挖 120 個交易日 (半年) 的分點進出。

**預估時間**：約 6.5 小時 (中斷一樣可隨時續傳)。

**啟動指令** (同 Step 2，只需替換指令本體)：

```bash
docker run -d --name radar-warrant-backfill --restart unless-stopped \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar backfill-warrant-branches --top 200 --days 120 --sleep 1.2"
```

> **注意**：這支指令**不強制要求**跑完才能用網站，只要它在跑，您每次打包上傳後，網站上的 `120D` 數據就會越來越完整！

---

## P2:擴到 5 年 × 1,200 檔(⚠️ 2026-07-12 已被 `docs/26` 全市場擴容計畫取代——目標改為全市場×490d,前置與工作包一律看 docs/26;本節僅留歷史參考)

- ⚠️ 前置:5 年全量會讓資料庫 +7–9GB,超過現行免費架構上限(GitHub Release 單檔 2GB、Actions cache 10GB)→ **開發端要先把分點歷史拆成獨立檔**。做完會通知你。
- R2 邊界見 `docs/21_private_beta_access_r2_plan.md`:R2 可保存壓縮後的 `branch_hist.db` 快照,
  但不能直接在 R2 上執行 SQLite;且 10GB-month 免費額度無法保證容納 P2 current+previous
  多版本。P2 仍需另案做容量實測與高風險批准,本計畫不因有 R2 就自動解鎖。
- 屆時指令 = Step 2 同一段,參數改:`--top 1200 --days 1215`,約連跑 **17 天**(march-back 由新到舊,跑到第 3 天時「1,200 檔 × 近一年」就已可用,不用等跑完)
- P3(全部 ~2,000 檔)不建議:日均額 3 千萬以下的冷門股分點稀疏,無統計意義

---

## FAQ

| 問題 | 答案 |
|---|---|
| 中斷/斷線/重開機? | 不用管,`--restart unless-stopped` + 斷點續傳,自己會繼續 |
| 跑的 3 天網站會壞嗎? | 不會,雲端每日排程照常;VPS 是平行作業,最後才合併 |
| 手機通知沒來但 log 顯示完成? | 手動跑 Step 2 最後那行 curl 測試;主題名兩邊要一致 |
| 為什麼不用 n8n? | 批次腳本自帶排程/續傳,n8n 包外面只是多層殼;n8n 留給之後的 LINE 推播 |
| 想更快? | 別。1 秒/請求已是 5 站輪替下的禮貌上限,更快 = 被封 IP = 全部歸零 |

---

## 附錄:免費來源清查與方案評估(背景)

| 來源 | 判定 |
|---|---|
| MoneyDJ zco × 5 鏡像(富邦/元富/永豐金/國泰/凱基,實測資料位元級一致) | **採用**;深度上限 ~2021 年中(5 年) |
| TWSE bsr 官方 | CAPTCHA,不破解(已定案) |
| FinMind 分點資料集 | 付費贊助 NT$300–600/月;要「超過 5 年或全市場無腦全量」才考慮 |
| Goodinfo/CMoney 等 | 條款禁止,不做 |

原始 RackNerd 方案(25 萬請求全打富邦單站、宣稱唯一解)的三處修正:鏡像輪替攤負載、範圍分階段、GitHub Actions 承擔每日增量(額度數學:歷史深挖 280 分/晚 × 15 晚 = 4,200 分 > 免費 2,000 分/月,故深挖歸 VPS、增量歸 Actions)。
