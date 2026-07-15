# 32 WP-B3 cutover runbook(執行手冊,docs/31 §6 展開版)

> **狀態:草稿備用,尚未執行**。本檔只把 `docs/31` §6 WP-B3 的六個步驟展開成精確到指令/diff 的操作清單,
> 讓 cutover 當天變成照抄執行,不用臨場現想。**任何一步都不得在使用者明確喊「開工」前執行**
> (docs/31 §10 規則 1)。前置條件:WP-B2 影子驗證連續 2–3 個交易日通過(驗收清單 `vps/README.md` §9)。
> 選一個交易日**盤前**(14:10 daily-market 觸發前)執行,預留半天觀察午盤。

## 前置檢查(執行當天開工前,5 分鐘)

```bash
# 1. 影子驗證是否真的乾淨:最近 2-3 個交易日 ntfy 有沒有任何 High 告警
#    (人工回想/翻手機通知即可,沒有自動化指令)

# 2. VPS 資料是否新鮮
curl -s https://radar.techtrever.com/data-preview/radar.json | python3 -c "import json,sys; print(json.load(sys.stdin)['freshness'])"

# 3. 正式站是否新鮮(兩者應同日)
curl -s https://radar.techtrever.com/data/radar.json | python3 -c "import json,sys; print(json.load(sys.stdin)['freshness'])"

# 4. 工作樹乾淨、main 與 origin 同步
git status --short --branch
```

停止條件:任何一項不符合預期,不執行後續步驟,回報使用者。

## Step 1 — Worker route 解除影子限制,正式接管 `/data/*`

**檔案**:`cloudflare-data-worker/wrangler.toml`

```diff
 # WP-B3 cutover 時解除下面註解重新 deploy,正式接管 /data/*(docs/31 §6 WP-B3)
-# [[routes]]
-# pattern = "radar.techtrever.com/data/*"
-# zone_name = "techtrever.com"
+[[routes]]
+pattern = "radar.techtrever.com/data/*"
+zone_name = "techtrever.com"
```

**執行位置**:VPS(有 `cloudflare-data-worker/` 目錄與 `CLOUDFLARE_API_TOKEN`)。

```bash
cd ~/trever-radar
git pull --ff-only
# 手動編輯 wrangler.toml 解除上面兩行註解(或請 Agent 出 patch 貼上)
cd cloudflare-data-worker
npx wrangler deploy
```

**立即驗證**(這步做完,`/data/*` 同時有雲端 Pages 產物與 Worker 資產在搶同一路徑——
下一步 Step 3 完成前 Worker route 優先權以 Cloudflare 路由匹配為準,需實測確認資料來源已切換):

```bash
curl -sI https://radar.techtrever.com/data/radar.json | grep -i cache-control
# 預期:radar.json 是 no-store(來自本 Worker,而非 Pages 靜態檔快取)
```

## Step 2 — 停用 Cloudflare Worker trigger(排程觸發器)

**檔案**:`cloudflare-trigger/wrangler.toml`

```diff
 [triggers]
-crons = ["*/10 * * * *"]
+crons = []
```

程式(`worker.js`)保留不刪(§9 退役清單:回滾窗兩週內保留)。

```bash
cd cloudflare-trigger
npx wrangler deploy
```

**驗證**:Cloudflare dashboard → Workers → `trever-radar-scheduler` → Triggers 頁面應顯示無 Cron Trigger。

## Step 3 — `deploy.yml` 改純 build+deploy;5 支資料 workflow 停用觸發

**檔案**:`.github/workflows/deploy.yml` —— 刪除 DB restore/seed/compute-scores/compute-performance/export-json 步驟:

```diff
 jobs:
   build_and_deploy:
     runs-on: ubuntu-latest
     timeout-minutes: 10
     env:
       PYTHONUNBUFFERED: "1"
     steps:
       - uses: actions/checkout@v4

-      - uses: actions/setup-python@v5
-        with:
-          python-version: "3.11"
-          cache: pip
-          cache-dependency-path: pipeline/requirements.txt
-
-      - name: Restore SQLite cache
-        uses: actions/cache/restore@v4
-        with:
-          path: data/radar.db
-          key: radar-db-${{ github.run_id }}
-          restore-keys: radar-db-
-
-      - name: Seed DB from release backup
-        if: hashFiles('data/radar.db') == ''
-        env:
-          GH_TOKEN: ${{ github.token }}
-        run: |
-          gh release download db-backup --pattern radar.db.gz --dir data || true
-          if [ -f data/radar.db.gz ]; then gunzip data/radar.db.gz; fi
-
-      - name: Install dependencies
-        run: pip install -r pipeline/requirements.txt
-
-      - name: Compute daily scores
-        working-directory: pipeline
-        run: python -m radar compute-scores
-
-      - name: Backfill score performance
-        working-directory: pipeline
-        run: python -m radar compute-performance
-
-      - name: Export frontend JSON
-        working-directory: pipeline
-        run: python -m radar export-json
-
       - uses: actions/setup-node@v4
         with:
           node-version: 20
           cache: npm
           cache-dependency-path: web/package-lock.json
```

其餘(build site / deploy to Cloudflare Pages 兩步)不動。`web/public/data` 本已 gitignore,
Actions 不再產生它 → Pages 上不再帶資料檔,`/data/*` 全走 Step 1 的 Worker 資產。

**5 支資料 workflow**(`daily-market.yml` / `daily-insti.yml` / `daily-branches.yml` /
`daily-margin.yml` / `data-backfill.yml`):它們**只有 `workflow_dispatch:`**、無原生
`schedule:`(見 `cloudflare-trigger/README.md`),觸發完全靠 Step 2 停用的 Worker cron。
**所以 Step 2 做完,這 5 支就已經停止自動觸發**——本步驟不需要再改這 5 個 yaml 檔案本身,
保留檔案原封不動即可(§9 退役清單:回滾窗兩週後才刪)。

```bash
git add .github/workflows/deploy.yml
git commit -m "chore(deploy): cutover WP-B3 — strip data steps, VPS is now sole writer"
git push origin main   # 觸發一次 deploy.yml 驗證 code 部署鏈
```

**驗證**:`gh run watch` 看這次 push 觸發的 `deploy` workflow 是否在 ~2–3 分鐘內成功
(build → wrangler pages deploy,無資料步驟)。

## Step 4 — 盤中 worker 改讀自訂網域 + 啟用 Access service token

**檔案**:`pipeline/intraday/.env`(不入 repo,人工在跑 worker 的機器上改)

```
RADAR_JSON_URL=https://radar.techtrever.com/data/radar.json
CF_ACCESS_CLIENT_ID=<Cloudflare Access service token client id>
CF_ACCESS_CLIENT_SECRET=<Cloudflare Access service token secret>
```

`pipeline/intraday/worker.py` 已內建這兩把 token 的 header 注入(`_build_radar_headers()`），
程式碼零改動,只需要使用者本機 `.env` 補上述三行。Access service token 需在 Cloudflare
Zero Trust 後台建立(Service Auth → Service Tokens),白名單需另外加進既有 Access
Application(不是新開一個)。

**驗證**:重啟 intraday worker,看啟動 log 第一次抓 `radar.json` 是否 200(而非 403)。

## Step 5 — repo 轉回 private【人工,GitHub 網頁操作】

Settings → General → Danger Zone → Change repository visibility → Private。
**不透過 CLI 執行**(帳戶層級的破壞性設定變更,Agent 不代為操作,docs/10 §3 / AGENTS.md 危險清單)。

轉 private 後 Actions 分鐘數受 2,000/月限制;`deploy.yml` 每次 push ~2–3 分鐘,
月用量預估 <100 分鐘(§3.3),額度無虞。

## Step 6 — 當晚驗收清單

- [ ] 正式站 `radar.techtrever.com/data/radar.json` freshness 全綠(當日日期、`stale:false`)
- [ ] 14:10/17:40/21:00/22:10 各輪 VPS cron 正常跑完(`tail ~/radar-cron.log`,無 ntfy High)
- [ ] **未登入** `curl -s -o /dev/null -w '%{http_code}' https://radar.techtrever.com/data/radar.json` 回傳 302/403(被 Access 擋,不是 200)——**紅線,擋不住就要回滾**(docs/31 §7)
- [ ] 登入 Access 後,網站全站功能正常(首頁榜單、個股頁、分點頁、自選)
- [ ] 盤中面板 worker 狀態顯示 online(Step 4 驗證延續到隔天開盤 08:55)
- [ ] `gh run list --workflow deploy.yml --limit 3` 只看到 build+deploy,無資料步驟報錯

全部打勾 → cutover 完成,**回滾窗開始倒數兩週**(docs/31 §8)。任一項不符合預期,
立即依 §8 回滾步驟操作,不要邊看邊修——先回滾到已知良好狀態,再離線排查。

## 完成後的文件同步(WP-B5,cutover 後儘快另包執行)

不在本次 cutover 當天做,但緊接著排:AGENTS.md 危險清單改寫(WAL/cache/release 續存鏈條
標記退役)、`docs/08` §0 重寫為 VPS cron 表、`DEPLOY.md`、`docs/vps_backfill_plan.md`
Step 4e 上傳流程作廢、STATUS.md。細節見 `docs/31` §6 WP-B5。
