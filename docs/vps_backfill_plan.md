# 分點歷史回補計畫(2026-07-08 修訂版;原 VPS 方案評估附後)

## 0. 免費分點資料來源清查結論

| 來源 | 內容 | 免費? | 判定 |
|---|---|---|---|
| **MoneyDJ zco 頁(多券商鏡像)** | 每股每日前 15 大買/賣超分點,可按日查,無登入無驗證碼 | ✓ | **現行採用**;實測富邦與元富鏡像資料位元級一致 → 輪替分散負載 |
| TWSE bsr(官方) | 全量分點日報 | ✓ 但有 CAPTCHA | 不做破解(已定案) |
| TPEx 官方分點 | 上櫃逐檔 | ✓ | 備援候選,未接 |
| FinMind `TaiwanStockTradingDailyReport` | 全市場全歷史、結構化 | ✗ 贊助 NT$300–600/月 | **想要「全市場×多年」的唯一正解**;免費路線做不到就升級這條 |
| Goodinfo/HiStock/CMoney 爬蟲 | 各種整理表 | 條款禁止 | 不做 |

結論:免費路線 = MoneyDJ 鏡像輪替;範圍務實訂為「**Top 500 每日 + Top 300 × 60 交易日歷史**」。要 2 年×500 檔請直接付 FinMind,別跟爬蟲過不去。

## 1. 已實作(2026-07-08,取代原方案的程式碼部分)

1. **鏡像輪替**:`providers/fubon.py` `MIRROR_HOSTS`(富邦+元富,可擴充)——整體 1.2 秒/請求時單站有效節奏 2.4 秒,比原方案「1.5 秒全打富邦」對單站更禮貌
2. **每日池擴大**:`import-branch-trades --top 500 --sleep 1.2`(80→500 檔;約 10–12 分鐘,已接 daily-branches)
3. **`backfill-branches`**:歷史 march-back(新→舊),斷點續傳(逐日比對缺漏、補齊的日期零成本)、`--max-minutes` 時間閥
4. **凌晨自動**:data-backfill 每天 01:10 跑 `backfill-branches --top 300 --days 60 --max-minutes 90`——每晚啃 90 分鐘,**約 5–7 個交易夜自動補完 60 日深度**,之後每晚零成本略過

## 2. 原 RackNerd VPS 方案評估

**方向可行,三處修正:**
1. ❌「25 萬次請求全打富邦、1.5 秒間隔跑 104 小時」——單一來源高頻連打 4 天,正是最容易被封 IP 的模式;「唯一完美解法」結論不成立。✅ 修正:鏡像輪替(N 站 = 單站壓力 ÷N)+ 範圍縮到有統計價值的量(300×60 日 ≈ 1.8 萬請求,不是 25 萬)
2. ❌ 低估 GitHub Actions:凌晨窗口 + `--max-minutes` + 斷點續傳 = 不用管 6 小時上限,一週自動補完。VPS 從「必需」降級為「想更快/想更深時的加速器」
3. ✅ 其餘正確:斷點續傳、逐批寫入防 OOM、Docker 免污染主機、跑完 `gh release upload db-backup --clobber` 回寫——**注意:上傳後要刪掉 Actions 舊 cache(`gh cache delete --all`),否則雲端下次仍用舊 cache,VPS 成果不生效**

## 3. VPS 執行指令(修正版;想加速或加深時才需要)

```bash
git clone https://github.com/bbdevin/trever-radar.git && cd trever-radar
mkdir -p data
curl -L https://github.com/bbdevin/trever-radar/releases/download/db-backup/radar.db.gz -o data/radar.db.gz
gunzip data/radar.db.gz

docker run -d --name radar-backfill \
  -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
  -w /app/pipeline python:3.11 \
  bash -c "pip install -r requirements.txt && python -m radar backfill-branches --top 500 --days 120 --sleep 1.2"
# 進度:docker logs -f radar-backfill(500檔×120日 ≈ 6萬請求 ≈ 20小時,非 4 天)

# 跑完回寫(gh auth login 後):
gzip -kf data/radar.db
gh release upload db-backup data/radar.db.gz --clobber
gh cache delete --all --repo bbdevin/trever-radar   # 關鍵:讓雲端改用新資料庫
```

## 4. 風險與禮貌守則

- 鏡像站非官方 API:改版會斷(parser 掛掉會進 import_logs 告警);請求率守住整體 ≥1.2 秒、單站 ≥2.4 秒
- 只有前 15 大分點(追主力夠用);上櫃權證無此來源
- 統計效力:可信度分數需事件 ≥10——60 日深度 + 每日累積,約 2–4 週後排行榜開始可信
