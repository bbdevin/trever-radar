// 執行: node --test web/lib/branchPnl.test.ts
//
// 區間損益(估算)的顯示邏輯與鎖定文案(見 branchPnl.ts、docs/42)。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PNL_AF_NOTE,
  PNL_FOOTER,
  PNL_FORMULA,
  PNL_HEADING,
  PNL_LEAD,
  PNL_POS_NOTE,
  availableWindows,
  captionText,
  fmtMoney,
  fmtRetPct,
  normalizePnl,
  rowNotes,
  splitBar,
  summaryText,
  unattributedNote,
} from "./branchPnl.ts";
import { changeTokens } from "./changeTokens.ts";

function row(over: Record<string, unknown> = {}) {
  return {
    name: "群益金鼎-板橋", est_total: 270_000_000, realized: 200_000_000, unrealized: 70_000_000,
    pos_lots: 0, avg_cost: 52.3, last_close: 88.1, buy_lots: 5200, sell_lots_attributed: 5200,
    sell_lots_unattributed: 0, visible_days: 41, max_cost: 250_000_000, ret_pct: 108,
    af_adjusted: false, first_date: "2025-10-01", last_date: "2026-10-02", ...over,
  };
}

function win(over: Record<string, unknown> = {}) {
  return {
    window_days: 240, first_date: "2025-10-01", pairs_considered: 37,
    pairs_skipped_missing_price: 0, n_gainers: 21, n_losers: 16,
    gainers: [row()], losers: [], ...over,
  };
}

test("鎖定文案逐字", () => {
  assert.equal(PNL_HEADING, "區間損益（估算）");
  assert.equal(
    PNL_LEAD,
    "只用這檔每日前 15 大進出看得見的買賣，以當日收盤價當成交價、平均成本法估算；看不見的日子視為沒交易，區間起點視為零持股。不含手續費與交易稅；股利只在調整因子有更新的期間才反映。",
  );
  assert.equal(PNL_POS_NOTE, "以未實現為主：若已在榜外出清，實際結果會不同。");
  assert.equal(unattributedNote(120), "另有 120 張賣出找不到對應買進（區間前已持有或榜外買進），未計入。");
  assert.equal(PNL_AF_NOTE, "區間內有調整因子變動，成本已換算到今日股本。");
  assert.equal(
    PNL_FOOTER,
    "估算不是帳戶真實損益，也不代表之後會重複；本站 2026-09-08 回測顯示分點×個股買賣傾向跨期可重現性低。",
  );
});

test("禁用詞不出現在任何文案", () => {
  const all = [PNL_HEADING, PNL_LEAD, PNL_POS_NOTE, PNL_AF_NOTE, PNL_FOOTER, unattributedNote(1),
    summaryText(win()), ...PNL_FORMULA].join("\n");
  for (const w of ["勝率", "獲利能力", "常低買高賣", "獲利"]) assert.ok(!all.includes(w), w);
});

test("金額格式:萬/億、正負號", () => {
  assert.equal(fmtMoney(270_000_000), "+2.7 億");
  assert.equal(fmtMoney(-8_500_000), "−850 萬");
  assert.equal(fmtMoney(-35_000), "−3.5 萬");
  assert.equal(fmtMoney(0), "0 元");
  assert.equal(fmtMoney(1_234_567_890_123), "+12,346 億");
  assert.equal(fmtMoney(99_999_000), "+1 億");
  assert.equal(fmtRetPct(108), "+108.0%");
  assert.equal(fmtRetPct(-3.25), "−3.3%");
  assert.equal(fmtRetPct(null), null);
});

test("帶號金額會被 ChangeText 上色", () => {
  assert.deepEqual(changeTokens("+2.7 億").map((t) => t.kind), ["up"]);
  assert.deepEqual(changeTokens("−850 萬").map((t) => t.kind), ["down"]);
  // 區間或日期不是帶號金額
  assert.ok(!changeTokens("3-5 萬").some((t) => t.kind === "down"));
});

test("摘要句是個數", () => {
  assert.equal(summaryText(win()), "符合門檻的 37 個分點：估算賺 21 個、賠 16 個");
  // 舊 payload 沒有 n_gainers → 用清單長度
  assert.equal(summaryText(win({ n_gainers: undefined, n_losers: undefined })), "符合門檻的 37 個分點：估算賺 1 個、賠 0 個");
});

test("條件註記與說明列", () => {
  assert.deepEqual(rowNotes(row()), []);
  assert.deepEqual(rowNotes(row({ pos_lots: 3, sell_lots_unattributed: 40, af_adjusted: true })), [
    PNL_POS_NOTE, unattributedNote(40), PNL_AF_NOTE,
  ]);
  assert.equal(captionText(row()), "2025-10-01–2026-10-02 · 41 個可見日");
});

test("已實現／未實現兩段條", () => {
  assert.deepEqual(splitBar(row()), { realized: 74, unrealized: 26 });
  assert.deepEqual(splitBar(row({ realized: -100, unrealized: 300 })), { realized: 25, unrealized: 75 });
  assert.equal(splitBar(row({ realized: 0, unrealized: 0 })), null);
});

test("缺鍵或版本不認得 → null", () => {
  assert.equal(normalizePnl(undefined), null);
  assert.equal(normalizePnl({ as_of: "x", definitions_version: "v0", windows: { "60": win() } }), null);
  assert.equal(normalizePnl({ as_of: "x", definitions_version: "pnl-avgcost-v1", windows: {} }), null);
  const ok = normalizePnl({ as_of: "x", definitions_version: "pnl-avgcost-v1", windows: { "240": win(), all: win() } });
  assert.ok(ok);
  assert.deepEqual(availableWindows(ok), ["240", "all"]);
});
