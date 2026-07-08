# VPS 分點歷史回補 — 手把手操作手冊(2026-07-09)

> 目的:把「每檔股票的分點進出明細」抓到 **2 年深**(P1),之後再擴到 5 年(P2)。
> 你只需要:一台能 SSH 的 VPS(已裝 Docker)+ 一支手機。全程免費。
> 每一步都是「複製 → 貼上 → 按 Enter」。看到不一樣的輸出就停下來,把畫面貼給 AI。

---

## 事前理解(30 秒版)

- 抓什麼:MoneyDJ 公開分點頁,5 個券商鏡像站輪流打,每秒 1 個請求(單站 5 秒一次,很禮貌)
- P1 = 成交金額前 500 檔 × 2 年 ≈ 24.5 萬個請求 ≈ **連跑 3 天**
- 中斷沒關係:重跑同一個指令會自動從缺的地方繼續
- 資料來源實測只回溯到 2021 年中 → 5 年就是免費上限,更早沒有
- 跑完會自動推播通知到你手機

---

## Step 0:手機先裝通知(2 分鐘)

1. 手機商店搜尋 **ntfy** 安裝(免費、免註冊)
2. 打開 App → 右下 **+** → Subscribe to topic
3. 主題名輸入一個**只有你知道的長字串**,例如:`trever-radar-x8k2m9q7`
   (主題名就是密碼,太短會被別人猜到亂發通知)
4. 記住這個字串,Step 2 會用到

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

## Step 4:手機收到「P1 完成」後 → 上傳回雲端(10 分鐘)

SSH 回 VPS,逐段貼:

### 4a. 補齊 VPS 跑的 3 天裡缺的每日行情(不做會有 3 天缺口)

```bash
cd ~/trever-radar
docker run --rm -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && python -m radar backfill --days 7 && \
    for i in 0 1 2 3 4 5 6; do python -m radar import-daily --date \$(date -d \"-\$i day\" +%Y%m%d) --datasets insti,margin || true; done"
```

### 4b. 安裝 GitHub CLI 並登入(依你系統二選一)

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

### 4c. 上傳 + 讓雲端改用新資料庫(關鍵兩行都要跑)

```bash
gzip -kf data/radar.db
gh release upload db-backup data/radar.db.gz --clobber --repo bbdevin/trever-radar
gh cache delete --all --repo bbdevin/trever-radar     # 不跑這行,雲端會繼續用舊資料庫!
docker rm -f radar-backfill
```

### 4d. 回報

跟 AI 說「P1 上傳完成」→ AI 會驗證雲端接手、觸發重算分點統計。之後**網站個股頁的分點 tab 就有 2 年進出明細與「2年」聚合**,關鍵分點勝率/買低賣高統計開始有樣本。

---

## P2:擴到 5 年 × 1,200 檔(P1 之後,先等開發端一件事)

- ⚠️ 前置:5 年全量會讓資料庫 +7–9GB,超過現行免費架構上限(GitHub Release 單檔 2GB、Actions cache 10GB)→ **開發端要先把分點歷史拆成獨立檔**。做完會通知你。
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
