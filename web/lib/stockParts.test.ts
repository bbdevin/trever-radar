// 執行: node --test --experimental-strip-types web/lib/stockParts.test.ts
//
// 拆檔合併(docs/44 P1 §3.2):core + hist + chips 接回 == 舊單一檔;舊檔原樣;缺的部分不補。
import assert from "node:assert/strict";
import { test } from "node:test";

import { CHIPS_KEYS, decodeBranchDays, isSplitCore, mergeIfSplit, mergeStockParts, type StockCoreJson, type StockHistFile } from "./stockParts.ts";
import type { BranchDaysV2, StockJson } from "./types.ts";

function candles(n: number, first: string) {
  const start = Date.parse(`${first}T00:00:00Z`);
  return Array.from({ length: n }, (_, i) => ({
    t: new Date(start + i * 86400_000).toISOString().slice(0, 10),
    o: 1 + i, h: 2 + i, l: 0.5 + i, c: 1.5 + i, v: 10 + i, amt: 100 + i, af: 1,
  }));
}

function legacy(): StockJson {
  return {
    id: "2330", name: "台積電", market: "twse", industry: "半導體",
    candles: candles(400, "2023-06-01"),
    technical: null, scores: null, reasons: [], raw_reasons: [], risks: [], raw_risks: [],
    branches: [{ name: "凱基-台北", buy: 1, sell: 0, net: 1, pct: 0.1 }],
    branch_history: [{ t: "2024-01-02", branches: [{ n: "凱基-台北", b: 1, s: 0, net: 1 }] }],
    branch_pctile_counts: { version: 2 } as never,
    branch_tags: { as_of: "2024-01-02", geo: { rule: null, names: [] }, daytrade: { min_obs: 8, rate: 0.6, payback: 0.5, rows: {} }, tracked: [] } as never,
    warrant: null, warrant_history: [], active_warrants: [],
    insti_history: [], margin_history: [], holders_history: [], directors_latest: null,
    branch_pnl_est: { as_of: "2024-01-02", definitions_version: "x", windows: {} },
    futures: { version: 1, list_as_of: "2024-01-02", contracts: [] },
  };
}

/** 與 Python split_stock_payload 相同的切法(cut 以前進 hist),用來自造三份。 */
function split(full: StockJson, cut: string | null) {
  const core: Record<string, unknown> = {};
  const chips: Record<string, unknown> = { version: 1, id: full.id };
  for (const [k, v] of Object.entries(full)) {
    if ((CHIPS_KEYS as readonly string[]).includes(k)) chips[k] = v;
    else core[k] = v;
  }
  let hist: StockHistFile | null = null;
  if (cut) {
    const idx = full.candles.findIndex((c) => c.t >= cut);
    const n = idx < 0 ? full.candles.length : idx;
    if (n > 0) {
      hist = { version: 1, id: full.id, cut, bars: n, candles: full.candles.slice(0, n) };
      core.candles = full.candles.slice(n);
    }
  }
  core.parts = {
    version: 1,
    hist: hist ? { file: `hist/${full.id}.abcdef01.json`, bars: hist.bars, cut, first: hist.candles[0].t } : null,
    chips: { file: `chips/${full.id}.json`, keys: CHIPS_KEYS.filter((k) => k in chips) },
  };
  return { core: core as unknown as StockCoreJson, hist, chips };
}

test("core + hist + chips 接回 == 舊單一檔(連鍵序),且沒有 parts", () => {
  const full = legacy();
  const { core, hist, chips } = split(full, "2024-01-01");
  assert.ok(isSplitCore(core));
  assert.equal(hist!.bars, full.candles.filter((c) => c.t < "2024-01-01").length);
  assert.equal(core.candles[0].t, "2024-01-01");
  for (const k of CHIPS_KEYS) assert.ok(!(k in core));
  const merged = mergeStockParts(core, hist, chips as never);
  assert.deepStrictEqual(merged, full);
  assert.ok(!("parts" in merged));
  // 原物件沒被改
  assert.equal(core.candles.length, full.candles.length - hist!.bars);
});

test("沒有 hist(非聯集股)/ 沒有某些 chips 鍵:只接有的,不發明鍵", () => {
  const full = legacy();
  delete full.branch_pnl_est;
  delete full.futures;
  const { core, hist, chips } = split(full, null);
  assert.equal(hist, null);
  assert.equal(core.parts.hist, null);
  assert.deepStrictEqual(core.parts.chips.keys, ["branch_history", "branch_pctile_counts", "branch_tags"]);
  const merged = mergeStockParts(core, null, chips as never);
  assert.deepStrictEqual(merged, full);
  assert.ok(!("branch_pnl_est" in merged));
});

test("hist 還沒到:接回的 K 線只有核心那段,其餘鍵完整(個股頁第一次畫面)", () => {
  const full = legacy();
  const { core, chips } = split(full, "2024-01-01");
  const partial = mergeStockParts(core, null, chips as never);
  assert.equal(partial.candles[0].t, "2024-01-01");
  assert.deepStrictEqual(partial.branch_history, full.branch_history);
  assert.ok(!("parts" in partial));
});

test("舊單一檔不是核心:isSplitCore=false,mergeIfSplit 原樣回傳同一個物件", () => {
  const full = legacy();
  assert.equal(isSplitCore(full), false);
  assert.equal(mergeIfSplit(full, () => assert.fail("不該讀檔")), full);
});

const V2_DAYS: BranchDaysV2 = {
  version: 2, per_side: 15, names: ["凱基-台北", "元大-士林", "怪怪-分點"],
  days: [["2024-01-03", [[0, 10, 0], [1, 0, 7], [0, 3, 0], [2, 5, 2, 4]]], ["2024-01-02", [[0, 1, 0]]]],
};
const V2_DECODED = [
  { t: "2024-01-03", branches: [
    { n: "凱基-台北", b: 10, s: 0, net: 10 }, { n: "元大-士林", b: 0, s: 7, net: -7 },
    { n: "凱基-台北", b: 3, s: 0, net: 3 }, { n: "怪怪-分點", b: 5, s: 2, net: 4 },
  ] },
  { t: "2024-01-02", branches: [{ n: "凱基-台北", b: 1, s: 0, net: 1 }] },
];

test("chips v2(branch_days):接回時解碼成 branch_history,結果裡沒有 branch_days;與 Python decode 同規則", () => {
  assert.deepStrictEqual(decodeBranchDays(V2_DAYS), V2_DECODED);
  assert.deepStrictEqual(decodeBranchDays(undefined), []);
  assert.deepStrictEqual(decodeBranchDays({ version: 2 } as never), []);
  const full = legacy();
  delete full.branch_history;
  full.branch_days = V2_DAYS;
  const { core, hist, chips } = split(full, "2024-01-01");
  assert.deepStrictEqual(core.parts.chips.keys, ["branch_days", "branch_pctile_counts", "branch_tags", "branch_pnl_est"]);
  const merged = mergeStockParts(core, hist, chips as never);
  assert.ok(!("branch_days" in merged));
  assert.deepStrictEqual(merged.branch_history, V2_DECODED);
  // 其餘鍵與舊檔相同
  const expected = { ...legacy(), branch_history: V2_DECODED };
  assert.deepStrictEqual(merged, expected);
  // 舊單一檔(--legacy-stocks)帶 branch_days 也解碼
  const single = { ...legacy(), branch_days: V2_DAYS } as StockJson;
  delete single.branch_history;
  const norm = mergeIfSplit(single, () => assert.fail("不該讀檔"));
  assert.deepStrictEqual(norm.branch_history, V2_DECODED);
  assert.ok(!("branch_days" in norm));
  // 舊 chips v1(branch_history)照舊
  assert.deepStrictEqual(mergeStockParts(split(legacy(), null).core, null, split(legacy(), null).chips as never), legacy());
});

test("mergeIfSplit:依 parts 指標讀兩個檔再接回", () => {
  const full = legacy();
  const { core, hist, chips } = split(full, "2024-01-01");
  const reads: string[] = [];
  const merged = mergeIfSplit(core, (rel) => {
    reads.push(rel);
    return rel.startsWith("hist/") ? hist : chips;
  });
  assert.deepStrictEqual(reads, ["hist/2330.abcdef01.json", "chips/2330.json"]);
  assert.deepStrictEqual(merged, full);
});
