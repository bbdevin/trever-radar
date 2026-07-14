# 26 全市場擴容計畫(2026-07-12 使用者定案)

> **決策記錄**:使用者 2026-07-12 定案「台股有幾檔就抓幾檔」——分點每日池與歷史回補擴至全市場,推翻原「P3 全部 ~2,000 檔不建議」取捨(`vps_backfill_plan.md` 附錄)。
> **翻案理由**(使用者提出,Planner 認同):流動性隨時間變化——「某檔 2 年前沒量、今年量很大」,以**現在的成交額**做 top-N 選樣有偏差:會漏掉「當時冷、後來熱」的完整歷程;且**發動前的冷門潛伏期正是分點佈局最有價值的觀察窗**,與產品核心(盤後找籌碼、抓發動)一致。
> 本檔為可執行工作包;WP-M3 屬 docs/17 高風險清單(schema/大量 backfill),動工前需使用者批准方案。
> **2026-07-15 更新**:**WP-M3(branch_hist.db 拆分)已因 B 案取消**——`docs/31` 定案 radar.db 常駐 VPS 後,拆分無必要;WP-M2/WP-M4 改依 `docs/31` WP-B6 執行。
> **⏸ 時程(2026-07-12 使用者指示)**:優先序後移——先讓現行 top500 歷史回補跑完、finalize 回灌並穩定運行幾天後,再啟動本計畫(STATUS 未完成 7a)。任何 agent 不得提前插隊執行本檔工作包。

## 1. 現況盤點(哪些已是全市場、哪些有池)

**已全市場(零工作)**:日K/法人/融資券/權證每日成交(每日全市場單請求)、題材(~1,060 類全映射)、指標 `compute-indicators --all`、綜合分(universe=當日有指標者,自動跟隨)、還原因子 `--all`、權證彙總。

**有池限制(本檔要解的)**:
| # | 池 | 現值 | 目標 |
|---|---|---|---|
| 1 | 每日分點爬取(import-branch-trades) | 500 檔×2輪 | **全市場×1輪** |
| 2 | 歷史分點 march-back | top500×490d(跑步中) | **全市場×490d**(第二輪) |
| 3 | 個股頁 JSON 池 | 評分池 959 檔 | **全市場 ~2,470 檔** |
| 4 | 權證分點 | 活躍 top 200 | **維持 top 200-300**(定案:冷門權證分點無統計意義且請求爆炸;參數可調) |

## 2. 硬約束(不可繞過)

- **DB 體積紅線**(AGENTS.md 危險清單):全市場分點歷史估 +3–6GB → 炸 GitHub Release 單檔 2GB 與 Actions cache 10GB。**WP-M4 之前必須完成 WP-M3 儲存拆分**。
- **MoneyDJ 禮貌速率不變**:1 req/s、5 鏡像輪替;全市場 490d ≈ 98 萬請求 ≈ **VPS 連跑 11–12 天**(斷點續傳,期間網站照常)。
- Actions 免費額度 2,000 分/月:每日全市場一輪 ~45 分/交易日 ≈ 現行 500×2輪 的總時間,**持平可承受**;兩輪全爬則爆——故 WP-M2 一輪制是前提。
- 冷門股樣本稀:統計面「樣本不足」標注照舊(寧缺勿濫),不因全量而放寬門檻。

## 3. 工作包

### WP-M1 個股頁 JSON 池全市場(可立即做,無依賴)
- `export-json` 個股池由評分池 959 → 全部 `type in ('stock','etf')`;非榜單裁 600 根維持。
- 驗收:實測產出總體積與檔案數(Pages 限 20,000 檔/部署),build+deploy 時間回報;搜尋任一股票有完整個股頁。
- 風險:總增量估 ~100–150MB 靜態檔;若實測爆預算,fallback = 非榜單裁 300 根。

### WP-M2 每日分點全市場一輪制(建議 finalize 上傳後切換)
- `daily-branches` 17:40 輪:import-branch-trades 改全市場(參數化,--top 0 或明確全清單);**21:00 輪移除分點爬蟲**,只補法人/融資券+重算分數(冪等)。
- 動 `.github/workflows/daily-branches.yml`(使用者已授權本計畫);**不動** cache/release 續存鏈與 WAL 步驟。
- 驗收:實測單輪耗時 ≤60 分(timeout 調整對應);Actions 月額度試算寫進 PR/commit 訊息;首晚跑完 branch_trades 當日檔數 ≈ 全市場。

### WP-M3 儲存拆分(⚠️ 高風險,需使用者批准後動工)
**建議方案(Planner 推薦)**:`branch_hist.db` 拆分 + 常駐 VPS + R2 週快照:
- 主 DB `radar.db` 的 `branch_trades` 只留**近 120 交易日**(每日評分 B1–B6/集中度/今日動向/track 視角預設窗全夠用);更舊分點列搬獨立 SQLite `branch_hist.db`。
- `branch_hist.db` **常駐 VPS**(主本)——全期統計(branch_stock_stats 全期勝率、Phase 3 回測、240d+ track 匯出)本來就在 VPS 跑,雲端日常鏈完全不需要它;**R2 私有 bucket 週快照**作異地備份(接 docs/21 R 系列,免費 10GB)。
- 雲端 Actions **不碰 R2、不需新憑證**——攻擊面不擴大。
- 需改:migration 腳本(搬移+主 DB VACUUM 回落體積)、compute-branch-stats 全期模式支援 `ATTACH branch_hist.db`(VPS 用)、export track 視角深度參數、`vps_backfill_plan.md` 流程同步。
- 驗收:主 DB 體積回落並穩定 <1.5GB;雲端全鏈(5 支 workflow)綠;VPS ATTACH 統計與拆分前一致(種子測試);R2 restore drill 一次。
- 替代方案 B(不推薦):hist 放 release 第二 asset——單檔 2GB 上限很快再撞,只是延後問題。

### WP-M4 歷史分點全市場 march-back(依賴 WP-M3)
- VPS:`backfill-branches` 全市場 × 490d(斷點續傳、鏡像輪替、1 req/s),估 11–12 天;完成後照 `vps_backfill_plan.md` Step 4 finalize+上傳(主 DB 只帶近窗,歷史直接寫 hist)。
- 寫入目標依 WP-M3 結構(新列進 hist 或先進主 DB 再由 migration 搬——由 WP-M3 實作定)。

## 4. 執行順序

```
現在:top500 歷史跑完 → finalize 鏈 + 上傳(全市場分數/題材/指標即上線)
   → WP-M1(隨時可做)+ WP-M2(上傳後切換)
   → WP-M3 使用者批准 → 實作 + 驗收
   → WP-M4 VPS 第二輪 march-back(~11-12 天,期間網站照常)
```

## 5. Reviewer 必查(實作時)

1. WP-M2 是否動到 cache/release 續存鏈或 WAL?(不應——只改爬取參數與輪次)
2. WP-M3 migration 是否可回滾、主 DB 近窗長度是否夠所有雲端日常計算(逐一列出讀 branch_trades 的程式點比對)?
3. R2 憑證是否只在 VPS(不進 Actions/repo)?
4. WP-M1 產出體積/檔案數是否實測並寫進回報?
5. 「樣本不足」誠實標注是否保留?
