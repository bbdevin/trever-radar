# 42 分點區間損益（估算）`pnl-avgcost-v1`

> 版本：2026-10-03（Phase 1）。決策來源：使用者 2026-10-03 反轉 `docs/37` E2「不做獲利歸因」（見 `docs/37` §7 反轉紀錄）；Reviewer（Fable）定案方案。
> 程式：`pipeline/radar/compute/branch_interval_pnl.py`（純函式）、`pipeline/radar/export/json_export.py`（個股迴圈呼叫）、`web/lib/branchPnl.ts`、`web/components/BranchPnlPanel.tsx`。測試：`pipeline/tests/test_branch_interval_pnl.py`、`web/lib/branchPnl.test.ts`。

## 1. 這是什麼、不是什麼

- 是：只用這檔股票每日**前 15 大進出看得見**的淨張數，以**當日收盤價當成交價**、**平均成本法**估算一個分點在一段區間內的已實現＋未實現金額。
- 不是：帳戶真實損益、勝率、或「這個分點會低買高賣」的身分判定。看不見的日子視為沒交易，區間起點視為零持股；不含手續費、交易稅與股利。本站 2026-09-08 回測顯示分點×個股買賣傾向跨期可重現性低，畫面照實講。
- 排序只依 NT$ 金額（賺由大到小、賠由小到大），**不依百分比**。

## 2. 輸入與窗口

- 資料：export 個股迴圈內已載入的 `branch_trades`（`date >= as_of − 730 日曆日`），**在裁成每日前 12 名之前**；K 線 `daily_prices`（close 非 NULL）的 `close` 與 `adj_factor`。不新增資料表、不新增夜間步驟。
- 可見交易日：這檔股票有任何分點列、且 `date ≤ 匯出資料日` 的日期。`as_of` = 最後一個可見交易日。
- 窗口 W ∈ {60, 240, all}：最後 W 個可見交易日（all = 已載入的全部，約 2 年）。窗口之前的交易一律忽略（起點零持股）。
- 同一天同名分點多列時淨張數相加。

## 3. 公式（per 分點 × 個股 × 窗口）

- 價格 `p_d = close_d × af_d ÷ af_last`（af = adj_factor；`af_last` 為 `as_of` 當日或之前最後一根 K 線的 af）。窗口內該分點任一交易日 `af_d ≠ af_last` → `af_adjusted = true`。
- `p_last` = 同一根 K 線的收盤。
- 起始 `pos = 0, avg = 0, realized = 0`；依日期處理淨張數 `net`（`net = 0` 的日子不交易）：
  - `net > 0`：`avg = (pos·avg + net·p_d) / (pos + net)`；`pos += net`。
  - `net < 0`：`sold = min(|net|, pos)`；`realized += sold·(p_d − avg)·1000`；`pos −= sold`；`unattributed_sell += |net| − sold`（**不放空**）。
  - 每步之後 `max_cost = max(max_cost, pos·avg·1000)`。
- `unrealized = pos·(p_last − avg)·1000`；`est_total = realized + unrealized`；`ret_pct = est_total ÷ max_cost × 100`（max_cost 為 0 → null）。
- 會計恆等式（測試釘住）：`est_total = Σ 已歸屬賣出金額 + pos·p_last·1000 − Σ 買進成本`。

## 4. 入選與排除

- 窗口內看得見的買進（Σ net>0）≥ **50 張**，且 `max_cost` ≥ **1,000,000 元**。
- 窗口內該分點任一交易日（net≠0）沒有收盤價 → 整個不列，計入 `pairs_skipped_missing_price`。
- `pairs_considered` = 通過上兩條的分點數；`est_total > 0` 進 gainers、`< 0` 進 losers（兩者互斥，0 都不進），各取前 15；同額依名稱排序（確定性）。

## 5. Payload

`stocks/{id}.json.branch_pnl_est`（這檔沒有任何分點列時**缺鍵**）：

```
{ as_of, definitions_version: "pnl-avgcost-v1",
  windows: { "60": W, "240": W, "all": W } }
W   = { window_days, first_date, pairs_considered, pairs_skipped_missing_price,
        n_gainers, n_losers, gainers: Row[], losers: Row[] }
Row = { name, est_total, realized, unrealized, pos_lots, avg_cost, last_close,
        buy_lots, sell_lots_attributed, sell_lots_unattributed, visible_days,
        max_cost, ret_pct|null, af_adjusted, first_date, last_date }
```

金額（est_total／realized／unrealized／max_cost）為 NT$ 整數；`avg_cost`／`last_close` 兩位小數；`ret_pct` 為百分比兩位小數。`n_gainers`／`n_losers` 是全部個數（清單只留 15），供摘要句「估算賺 X 個、賠 Y 個」使用——相對 Reviewer 原始 schema 的唯一增補。`visible_days` = 該分點在窗口內出現的天數（含淨額 0 的列）；`first_date`／`last_date` 是它在窗口內第一次／最後一次出現。

## 6. 畫面（手機優先）

- 個股頁 → 籌碼日報 → 第四段「區間損益」（四段標籤：買賣超／囤出貨／買低賣高／區間損益，選中為主色實心）。缺鍵或 `definitions_version` 不認得時不出現這一段。
- SectionHeader「區間損益（估算）」→ 引言 → 區間 3月｜1年｜2年（記住）→ 估算賺／賠切換（紅／綠淡底＋文字與個數）→ 摘要句 → 前 5 卡＋「顯示全部（15）」→ 「怎麼算」（收合，公式）→ 頁尾聲明。
- 卡片：名次圈＋分點名；帶號金額（大字，`ChangeText` 紅賺綠賠，正負號一起出現）；「對最大持有成本 ±x%」小字；三格：均價→現價、持有（下限）、已實現／未實現兩段條（兩色各配「已／未」字樣與同色圓點）；`first–last · N 個可見日`；條件註記（持股 >0、找不到對應買進的賣出 >0、調整因子變動）。點卡片開既有分點下鑽。

## 7. 鎖定文案（`web/lib/branchPnl.test.ts` 逐字比對）

- 標題「區間損益（估算）」
- 引言「只用這檔每日前 15 大進出看得見的買賣，以當日收盤價當成交價、平均成本法估算；看不見的日子視為沒交易，區間起點視為零持股。不含手續費、交易稅與股利。」
- 持股 >0「以未實現為主：若已在榜外出清，實際結果會不同。」
- 找不到對應「另有 N 張賣出找不到對應買進（區間前已持有或榜外買進），未計入。」
- 調整因子「區間內有調整因子變動，成本已換算到今日股本。」
- 頁尾「估算不是帳戶真實損益，也不代表之後會重複；本站 2026-09-08 回測顯示分點×個股買賣傾向跨期可重現性低。」
- 禁用：勝率、獲利能力、常低買高賣（`test_label_honesty` 另禁「獲利」等詞）。

## 8. 成本與量測

- 單檔計算：本機 6488 樣本（480 個可見日、每日裁剪後 12 分點、5,760 列）約 13 ms；正式 export 用未裁剪列（約 2–3 倍），估計每檔 +30 ms 上下。實際 export 增量待 VPS 下一輪量測後回填。

## 9. 後續（未授權）

- Phase 2 以後（例如分點頁跨股彙總、更長窗口、手續費模型）均未授權，須另次確認。
