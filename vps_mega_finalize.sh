#!/bin/bash
# VPS 專用: 終極大禮包回補與重算腳本 (現貨+權證雙打專用)
# 用途: 一鍵補滿三大法人、融資券、權證分點歷史，並重新結算所有指標與分數
# 建議執行頻率: 週末一次，或覺得籌碼資料有缺時手動執行

# 您可以透過環境變數傳入，或直接修改下方的字串為您的主題
NTFY_TOPIC=${NTFY_TOPIC:-"trever-radar-x8k2m9q7"}

echo "啟動 Radar 終極大禮包回補程序..."
echo "通知將發送至 ntfy.sh/$NTFY_TOPIC"

# 自動切換到腳本所在的目錄 (專案根目錄)
cd "$(dirname "$0")"

# 如果之前有跑過的同名容器，先清掉
docker rm -f radar-mega-finalize 2>/dev/null

docker run -d --name radar-mega-finalize \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && \
    echo '>>> 步驟 1: 回補 490 天開高低收價量、三大法人與融資券...' && \
    python -m radar backfill --days 490 --datasets quotes,insti,margin && \
    echo '>>> 步驟 2: 回補 120 天活躍權證 (Top 200) 分點...' && \
    python -m radar backfill-warrant-branches --top 200 --days 120 --sleep 1.2 && \
    echo '>>> 步驟 3: 抓取最新題材分類...' && \
    python -m radar import-themes && \
    echo '>>> 步驟 4: 彙總權證成交資訊...' && \
    python -m radar aggregate-warrants && \
    echo '>>> 步驟 5: 重新計算所有技術指標...' && \
    python -m radar compute-indicators --all && \
    echo '>>> 步驟 6: 計算最新綜合評分...' && \
    python -m radar compute-scores && \
    echo '>>> 步驟 7: 計算歷史績效回測...' && \
    python -m radar compute-performance && \
    echo '>>> 步驟 8: 計算追蹤分點勝率統計...' && \
    python -m radar compute-branch-stats && \
    echo '>>> 全部完成，發送通知...' && \
    curl -s -H 'Title: Radar 終極回補完成' -d '200大權證與所有資料皆已結算完畢，可以執行上傳了！' ntfy.sh/$NTFY_TOPIC || \
    curl -s -H 'Title: Radar 終極回補失敗' -H 'Priority: high' -d '執行發生錯誤，請檢查 docker logs radar-mega-finalize' ntfy.sh/$NTFY_TOPIC"

echo "✅ 已經成功丟入背景執行！"
echo "👉 您可以安全地關閉此 SSH 視窗。"
echo "👉 若想隨時回來查看進度，請輸入: docker logs -f radar-mega-finalize"
