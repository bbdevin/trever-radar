# 30 全市場分點與權證歷史回補計畫 (WP-M4)

> 狀態：規劃與準備階段 (2026-07-14)
> 這是對應 `docs/vps_backfill_plan.md` 的長線執行擴充計畫。

## 1. 任務目標
1. **個股分點全市場歷史**：排除 ETF，回補全市場（約 1,200 檔）的分點歷史，初期目標 2 年（490 個交易日），最終目標 4 年（980 個交易日）。
2. **權證分點全市場歷史**：回補市場上所有活躍權證的分點歷史，目標半年（120 個交易日）。

## 2. 時程與硬體影響評估
因為爬蟲受限於安全頻率（1.2 秒一筆請求），此計畫需要極長的 VPS 執行時間：
* **個股 2 年**：1200 檔 × 490 天 = 約 58 萬次請求 ➔ **連跑約 8 天**
* **個股 4 年**：1200 檔 × 980 天 = 約 117 萬次請求 ➔ **連跑約 16 天**
* **權證半年**：預估每天活躍權證 8000 檔 × 120 天 = 約 96 萬次請求 ➔ **連跑約 13 天**

> **結論**：整體回補需在 VPS 上日夜不停執行約 3 到 4 週。我們依賴 `backfill-branches` 的**斷點續傳**能力，隨時中斷重啟都不會浪費進度。建議執行策略為「每跑 3~4 天就打包上傳一次 `radar.db`，讓前端逐步享有更長的歷史」。

## 3. 待辦的程式碼修正 (Blocking Issue)
在正式開始權證的大回補之前，必須先修正 `pipeline/radar/importer.py` 中的 `backfill_warrant_branches` 函數：
* **現有缺陷**：目前程式是拿「最新一個交易日」的 Top N 權證清單，去查這份清單過去半年的歷史。
* **致命問題**：權證壽命短，半年前的權證早就下市不在今天的清單中，而今天的權證半年前還沒發行！用今天的清單往回查會抓不到真正的歷史。
* **修正計畫**：將 Target 的查詢移入日期迴圈 `for d_iso in trade_dates:` 內，動態撈取「該歷史日期當天」真正有交易的權證清單，再發送請求。

## 4. VPS 上的智慧回補策略 (3 步驟)
為了讓網站能立刻獲得最近幾天的最新資料，而不必乾等一個月，我們採用「先補齊破洞並上傳，再放養長線回補」的策略。

### 第一步：補齊近期缺口並計算分數 (約需 1.5~2 小時)
```bash
# 1. 下載最新程式碼 (注意：絕對不要下載 db-backup，直接使用 VPS 裡既有的 490 天資料庫！)
cd ~/trever-radar && git pull


# 2. 啟動短期修補任務 (補齊最近 6 天的全市場個股與權證，並重算成績)
# 請將 NTFY 的值換成您自己的主題名稱
NTFY=trever-radar-x8k2m9q7

docker run -d --name radar-quick-catchup --restart unless-stopped \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar backfill-branches --top 2500 --days 6 --sleep 1.2 && \
    python -m radar backfill-warrant-branches --top 20000 --days 6 --sleep 1.2 && \
    python -m radar compute-indicators --days 10 && \
    python -m radar compute-scores && \
    python -m radar compute-branch-stats && \
    curl -s -H 'Title: Radar 6天修補完成' -d '請回 VPS 執行 Step 2 上傳' ntfy.sh/\$NTFY"
```

### 第二步：上傳完整的最新資料庫
等手機收到推播通知，或 `docker logs radar-quick-catchup` 顯示跑完後，執行上傳，讓前端網站更新：
```bash
cd ~/trever-radar
gzip -kf data/radar.db
gh release upload db-backup data/radar.db.gz --clobber --repo bbdevin/trever-radar
gh cache delete --all --repo bbdevin/trever-radar
```

### 第三步：放養長線歷史回補 (2年/半年)
網站更新完後，丟出背景指令讓 VPS 自己慢慢挖歷史（預估需跑 3 週以上）：
```bash
NTFY=trever-radar-x8k2m9q7

docker run -d --name radar-long-backfill --restart unless-stopped \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    python -m radar backfill-branches --top 2500 --days 490 --sleep 1.2 && \
    python -m radar backfill-warrant-branches --top 20000 --days 120 --sleep 1.2 && \
    curl -s -H 'Title: Radar 長線回補完成' -d '全市場歷史回補大功告成！' ntfy.sh/\$NTFY"
```

## 5. 容量監控
此計畫預計為資料庫新增 3,000 萬筆紀錄。得益於 Phase 2 的正規化架構，預計只會讓 `radar.db` 膨脹約 0.7~1.0 GB。請在每週上傳備份時，注意壓縮後的 `radar.db.gz` 檔案是否逼近 GitHub Release 的 2GB 上限。
