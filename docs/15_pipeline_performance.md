# 15 管線效能優化(2026-07-08 規劃)

> 使用者痛點:GitHub Actions 每日更新久、深歷史回補 4 小時。
> 診斷結論:**慢的不是「抓資料」**(官方 API 每日僅 ~6 請求、幾十秒),而是抓完之後的四件事。

## 0. 每日管線耗時解剖(優化前)

| 環節 | 耗時 | 原因 |
|---|---|---|
| DB cache 還原/儲存 | 1–3 分 ×2 | radar.db 已 1GB(深歷史回補後) |
| **gzip 1GB + 上傳 release 備份** | **2–4 分 ×3 支 workflow** | 每支每天都做一次(daily-market/warrants/branches 各一次) |
| **compute-indicators --all** | **最大宗,10–40 分** | 每晚對 ~2,470 檔「上市以來全歷史」重算並重寫幾百萬列 |
| 分點/權證爬蟲 | ~5 分 | 95 請求 × 3 秒禮貌節流(不宜加速) |
| export + build + deploy | 3–6 分 | 959 個 JSON + Next build + 上傳 |
| pip/npm 安裝 | 1–2 分 ×每支 | 無快取 |

## 1. 本次已實作 ✅

1. **指標增量計算**(最大贏面):`compute-indicators --all --days 5`
   - 只取每檔最後 340+5 根(暖機窗 = 年線 240 + 箱型 60 + 緩衝),只回寫最後 5 個交易日
   - 指標已是最新的股票直接跳過(前日已算過 → 只有當日新增要算)
   - 全歷史重算保留給「還原因子更新後」手動跑(`--all` 不帶 `--days`)
   - 註:MACD 的 EMA 理論上有無限記憶,340 根暖機後殘差 <10⁻⁶,可忽略
   - 預估:10–40 分 → **1–3 分**
2. **release 備份週五化**:三支 daily workflow 每天各 gzip 1GB 上傳一次 → 集中到 daily-branches(當日最後一跑)且僅週五/手動;cache 仍每跑必存(這才是日常續存機制)。省 6–12 分/日
3. **修正 cache 鏈分岔 bug**:daily-warrants 與 daily-branches 原本繞過 Actions cache 直接從 release 種子——與 daily-market 的 cache 鏈各玩各的,資料可能互相蓋舊。統一為「cache 優先、miss 才用 release 種子」
4. **pip/npm 快取**:全部 workflow 加 setup-python/node cache。省 1–2 分/跑

優化後預估:daily-market 20–50 分 → **5–8 分**;daily-branches ~15 分 → **10–12 分**(爬蟲節流佔大頭,不該省)。

## 2. 「歷史回補 4 小時」說明(不是 bug)

瓶頸 = **FinMind 免費額度 600 請求/小時**,2,470 檔每檔一請求 → 數學下限就是 ~4.2 小時。網路快慢無關。
- 這是**一次性**成本:做完後每日增量靠官方端點(每天 2 請求),永遠不用再跑
- 可中斷續跑(已拉深的股票自動跳過),排 1AM 跑完全不影響使用
- 想快只有兩條路:FinMind 贊助方案(額度大增)或多帳號輪替(違反其條款,不做)

## 3. 下一步(依效益排序,尚未做)

1. **export 批次查詢**:目前每檔 4–5 個 SQL × 959 檔 ≈ 5,000 次查詢 → 改一表一次撈全部再於 Python 分組;另 json.dumps 40MB。預估 2–4 分 → <1 分
2. **個股 JSON 歷史/近期分檔**(同時解「全歷史K線」與部署體積):`hist/{id}.json`(固定切點如 2026-01-01 之前,內容整年不變 → Pages 依內容雜湊自動跳過重傳)+ `stocks/{id}.json`(今年部分,每日更新但小)。全市場 2,470 檔都給上市以來完整K線也不拖慢每日部署
3. **warrant_daily 裁剪**(05 既定):保留 2 年明細,更早只留 warrant_stock_daily 彙總 → DB 從 1GB 縮 ~40%,cache/備份更快;加 VACUUM 月排程
4. **compute-performance / compute-scores 微調**:確認皆為當日增量(必要時比照指標加 --days)
5. 想再快的終極選項(皆免費):資料層搬 Cloudflare R2(部署不再帶 40MB JSON)、self-hosted runner(自己電腦跑,無 cache 上下載)——都先不做,等實際還嫌慢再說

## 4. 驗收

- daily-market 全程 ≤ 8 分鐘(Actions run 時間頁可查)
- 每日 Actions 總分鐘數 ≤ 30 分(月額度 2,000 分綽綽有餘)
- 週五備份照常出現在 release `db-backup`
