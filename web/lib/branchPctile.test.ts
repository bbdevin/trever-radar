// 執行: node --test web/lib/branchPctile.test.ts
//
// 個股頁「買點偏低、賣點偏高的分點」面板的純邏輯(見 branchPctile.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  baseLegend,
  campDefinition,
  campStatus,
  campTabLabel,
  daytradeSummary,
  fmtInt,
  normalizeBranchPctile,
  searchBranches,
  sideView,
  visibleRows,
} from "./branchPctile.ts";

function row(name: string, values: Partial<Record<string, number | null>> = {}) {
  return {
    branch_name: name,
    buy_pctile_known: 11, buy_pctile_unknown: 0, low_buy_count: 7,
    sell_pctile_known: 7, sell_pctile_unknown: 0, high_sell_count: 2,
    buy_lots_known: 2350, low_buy_lots: 1318, sell_lots_known: 400, high_sell_lots: 80,
    ...values,
  };
}

function camp(rows: ReturnType<typeof row>[], extra: Record<string, unknown> = {}) {
  return {
    available: true,
    stock_buy_pctile_known: 2000, stock_low_buy_count: 944,
    stock_sell_pctile_known: 2000, stock_high_sell_count: 696,
    stock_buy_lots_known: 10000, stock_low_buy_lots: 2250,
    stock_sell_lots_known: 10000, stock_high_sell_lots: 3000,
    shrink_k_buy_lots: 300, shrink_k_sell_lots: 250,
    branches: rows,
    ...extra,
  };
}

const LOOKUP_FIELDS = [
  "branch_name",
  ...["short", "long"].flatMap((c) => [
    "buy_pctile_known", "low_buy_count", "sell_pctile_known", "high_sell_count",
    "buy_lots_known", "low_buy_lots", "sell_lots_known", "high_sell_lots",
  ].map((f) => `${c}.${f}`)),
];

function v2(overrides: Record<string, unknown> = {}) {
  const shortRows = Array.from({ length: 12 }, (_, i) =>
    row(`分點${String(i + 1).padStart(2, "0")}`, { daytrade_obs: 9, daytrade_paybacks: 2 }));
  shortRows[0] = row("群益金鼎-板橋", { daytrade_obs: 3, daytrade_paybacks: 1 });
  return {
    version: 2,
    ranking: "lots_shrunk_v1",
    min_known_episodes_per_side: 5,
    max_branches: 30,
    windows: { short: 20, long: 120 },
    low_buy_max_pctile: 0.4,
    high_sell_min_pctile: 0.6,
    min_daytrade_obs: 8,
    as_of: "2026-09-30", window_market_days: 490, window_from: "2024-09-23",
    computed_at: "2026-10-01T00:06:27+08:00", definitions_version: "e2-pair-v2",
    stock_daytrade_obs: 3388, stock_daytrade_paybacks: 971,
    short: camp(shortRows),
    long: camp([row("元大-板橋")]),
    lookup_fields: LOOKUP_FIELDS,
    lookup: [
      // 只在長線派清單裡:短線派數字從 lookup 來。
      ["元大-板橋", 3, 1, 0, 0, 30, 10, 0, 0, 11, 7, 7, 2, 2350, 1318, 400, 80],
      // 兩派都沒進清單。
      ["凱基-台北", 4, 4, 9, 5, 40, 40, 90, 50, 2, 1, 0, 0, 20, 10, 0, 0],
    ],
    ...overrides,
  };
}

test("v2:主要那一行以張數為主、次數為輔", () => {
  const model = normalizeBranchPctile(v2())!;
  const stat = model.camps.short.rows[0];
  const view = sideView("buy", stat.buy, model.camps.short.base.buy, model.minKnown);
  assert.equal(view.label, "買在低檔 1,318 / 2,350 張 · 56%");
  assert.equal(view.detail, "次數 7/11");
  assert.equal(Math.round(view.pct!), 56);
  // 刻線用同一種單位:該股張數比率 2250/10000。
  assert.equal(view.basePct, 22.5);
  assert.equal(fmtInt(1318), "1,318");
});

test("賣出次數不足門檻 → 「賣出紀錄不足」,不是 0%", () => {
  const model = normalizeBranchPctile(v2())!;
  const stat = model.camps.short.rows[0];
  const thin = { ...stat.sell, known: 2, hit: 0, lotsKnown: 900, lotsHit: 0 };
  const view = sideView("sell", thin, model.camps.short.base.sell, model.minKnown);
  assert.equal(view.insufficient, true);
  assert.equal(view.label, "賣出紀錄不足");
  assert.equal(view.pct, null);
  assert.doesNotMatch(view.label + view.detail, /0%/);
  assert.match(view.detail, /未達 5 次/);
});

test("舊快照(張數為 null)退回次數比率,刻線也用次數", () => {
  const data = v2({
    ranking: "counts_v1",
    short: camp([row("甲", {
      buy_lots_known: null, low_buy_lots: null, sell_lots_known: null, high_sell_lots: null,
    })], { stock_buy_lots_known: null, stock_low_buy_lots: null }),
  });
  const model = normalizeBranchPctile(data)!;
  assert.equal(model.lotsRanked, false);
  const view = sideView("buy", model.camps.short.rows[0].buy, model.camps.short.base.buy, 5);
  assert.equal(view.label, "買在低檔 7 / 11 次 · 64%");
  assert.equal(Math.round(view.basePct! * 10) / 10, 47.2);
});

test("v1 payload 照樣可讀:沒有長線派、沒有張數,不當機", () => {
  const model = normalizeBranchPctile({
    version: 1, min_known_episodes_per_side: 5, max_branches: 10, min_daytrade_obs: 8,
    as_of: "2026-09-30", window_market_days: 490, window_from: "2024-09-23",
    computed_at: null, definitions_version: "e2-pair-v2",
    stock_buy_pctile_known: 2493, stock_low_buy_count: 1029,
    stock_sell_pctile_known: 2595, stock_high_sell_count: 1176,
    stock_daytrade_obs: 3388, stock_daytrade_paybacks: 971,
    branches: [{
      branch_name: "國票-九鼎", buy_pctile_known: 6, buy_pctile_unknown: 0, low_buy_count: 4,
      sell_pctile_known: 9, sell_pctile_unknown: 0, high_sell_count: 7,
      daytrade_obs: 6, daytrade_paybacks: 3,
    }],
  })!;
  assert.equal(model.version, 1);
  assert.equal(model.camps.long, null);
  assert.equal(model.camps.short.rows.length, 1);
  const view = sideView("buy", model.camps.short.rows[0].buy, model.camps.short.base.buy, 5);
  assert.equal(view.label, "買在低檔 4 / 6 次 · 67%");
  assert.match(campTabLabel(model, "short"), /近 20 個交易日/);
  // 搜尋只在清單裡找,長線派那一格是 null。
  const { results } = searchBranches(model, "九鼎");
  assert.equal(results.length, 1);
  assert.equal(results[0].camps.long, null);
});

test("未知版本或缺鍵 → null,整節不渲染", () => {
  assert.equal(normalizeBranchPctile(undefined), null);
  assert.equal(normalizeBranchPctile({ version: 3 }), null);
  assert.equal(normalizeBranchPctile({ version: 2 }), null);
  assert.equal(normalizeBranchPctile({ version: 1 }), null);
});

test("預設只顯示前 5 個,展開後顯示全部", () => {
  const model = normalizeBranchPctile(v2())!;
  const rows = model.camps.short.rows;
  assert.equal(rows.length, 12);
  assert.equal(visibleRows(rows, false).length, 5);
  assert.equal(visibleRows(rows, true).length, 12);
  assert.deepEqual(visibleRows(rows, false).map((r) => r.name), rows.slice(0, 5).map((r) => r.name));
});

test("搜尋涵蓋清單與 lookup,並說出誠實的未入選理由", () => {
  const model = normalizeBranchPctile(v2())!;
  const { results } = searchBranches(model, "板橋");
  // 兩者都排在某一派的第 1 位,同位時以名稱排。
  assert.deepEqual(results.map((r) => r.name).sort(), ["元大-板橋", "群益金鼎-板橋"].sort());
  const yuanta = results.find((r) => r.name === "元大-板橋")!;
  // 長線派清單第 1 位;短線派從 lookup 取數字,買進次數不足。
  assert.equal(campStatus(model, "long", yuanta.camps.long), "長線派：排序第 1 位");
  assert.equal(yuanta.camps.short!.stat!.buy.known, 3);
  assert.equal(
    campStatus(model, "short", yuanta.camps.short),
    "短線派：未進排行，買進紀錄 3 次，未達 5 次",
  );
  const kgi = searchBranches(model, "凱基").results[0];
  assert.equal(kgi.camps.short!.rank, null);
  assert.equal(kgi.camps.long!.stat!.buy.lotsKnown, 20);
  // 大小寫、前後空白不影響;空字串不搜尋。
  assert.equal(searchBranches(model, "  ").results.length, 0);
  assert.equal(searchBranches(model, "沒有這家").total, 0);
});

test("排序名次之外、買進次數足夠時,理由是名次", () => {
  const model = normalizeBranchPctile(v2({
    lookup: [["永豐-竹北", 9, 2, 0, 0, 90, 20, 0, 0, 9, 2, 0, 0, 90, 20, 0, 0]],
  }))!;
  const hit = searchBranches(model, "竹北").results[0];
  assert.equal(campStatus(model, "short", hit.camps.short), "短線派：未進排行，排在前 30 位之後");
});

test("頁籤與定義的數字來自 payload", () => {
  const model = normalizeBranchPctile(v2({ windows: { short: 20, long: 120 } }))!;
  assert.equal(campTabLabel(model, "short"), "短線派（近 20 個交易日 ≈ 1 個月）");
  assert.equal(campTabLabel(model, "long"), "長線派（近 120 個交易日 ≈ 半年）");
  assert.match(campDefinition(model, "long"), /近 120 個交易日的收盤區間/);
  assert.match(campDefinition(model, "long"), /≤40%/);
  assert.match(campDefinition(model, "long"), /≥60%/);
  const other = normalizeBranchPctile(v2({ low_buy_max_pctile: 0.3, high_sell_min_pctile: 0.7 }))!;
  assert.match(campDefinition(other, "short"), /≤30%.*≥70%/);
});

test("刻線圖例用張數比率", () => {
  const model = normalizeBranchPctile(v2())!;
  assert.equal(baseLegend(model.camps.short), "刻線＝此股全體分點：買在低檔 23%、賣在高檔 30%");
});

test("長線派未計算時明講,不是空排行", () => {
  const model = normalizeBranchPctile(v2({ long: camp([], { available: false }) }))!;
  assert.equal(model.camps.long!.available, false);
  const hit = searchBranches(model, "板橋").results[0];
  assert.equal(campStatus(model, "long", hit.camps.long), "長線派：這份資料尚未計算");
});

test("次日回吐:觀察不足講無法判定,不是 0 次", () => {
  const model = normalizeBranchPctile(v2())!;
  const thin = daytradeSummary(model, model.camps.short.rows[0])!;
  assert.match(thin, /無法判定/);
  const ok = daytradeSummary(model, model.camps.short.rows[1])!;
  assert.match(ok, /^2 \/ 9 次/);
  assert.match(ok, /此股全體分點 971 \/ 3388 次/);
  // 長線派沒有次日回吐。
  assert.equal(daytradeSummary(model, model.camps.long!.rows[0]), null);
});
