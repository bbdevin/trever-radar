// 執行: node --test --experimental-strip-types web/lib/marketBrief.test.ts
//
// 首頁「市場概況」(docs/49 §11):指數格式、漲跌字串、成交額合計、法人三格、資料日標記、禁詞。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BRIEF_INSTI_HINT,
  BRIEF_INSTI_LABEL,
  BRIEF_STALE_BADGE,
  BRIEF_TITLE,
  BRIEF_TURNOVER_LABEL,
  BRIEF_UPDOWN_HINT,
  dateTag,
  fmtE8,
  fmtIndex,
  indexChangeText,
  instiBriefItems,
  orderedIndices,
  turnoverCell,
  TREND_AFFORDANCE,
  TREND_EMPTY,
  TREND_HINT,
  TREND_RANGES,
  TREND_SHEET_TITLE,
  rangeStats,
  rangeTone,
  sliceRange,
  sparkPath,
  sparkTone,
  txSubtitle,
  type TrendPoint,
} from "./marketBrief.ts";

test("指數:千分位兩位小數,與來源同字", () => {
  assert.equal(fmtIndex(49313.44), "49,313.44");
  assert.equal(fmtIndex(426.71), "426.71");
  assert.equal(fmtIndex(426.7), "426.70");
});

test("漲跌字串:箭頭＋點數＋百分比,正負都在字裡;缺值退化", () => {
  assert.equal(indexChangeText(-492.93, -0.99), "▼492.93 · -0.99%");
  assert.equal(indexChangeText(244.27, 0.65), "▲244.27 · +0.65%");
  assert.equal(indexChangeText(0, 0), "0.00 · 0.00%");
  assert.equal(indexChangeText(-3.75, null), "▼3.75");
  assert.equal(indexChangeText(null, -0.87), "-0.87%");
  assert.equal(indexChangeText(null, null), "—");
});

test("資料日標記:與頁面資料日不同才標", () => {
  assert.equal(dateTag("2026-10-07", "2026-10-07"), null);
  assert.equal(dateTag("2026-10-06", "2026-10-07"), "10/06");
  assert.equal(dateTag(undefined, "2026-10-07"), null);
});

test("成交額格:兩市合計與漲跌家數相加;沒有 summary → null", () => {
  const c = turnoverCell([
    { market: "tpex", turnover: 158e8, up: 68, down: 72 },
    { market: "twse", turnover: 314e8, up: 132, down: 148 },
  ])!;
  assert.equal(fmtE8(c.total), "472.0億");
  assert.equal(fmtE8(1180.5e8), "1,180.5億");
  assert.deepEqual([c.up, c.down], [200, 220]);
  // 上市永遠在上櫃前面,不管 summary 的順序
  assert.deepEqual(c.byMarket.map((m) => m.market), ["twse", "tpex"]);
  assert.equal(turnoverCell([]), null);
  assert.equal(turnoverCell(undefined), null);
});

test("法人三格:外資/投信/自營,金額帶正負;缺鍵 → 空", () => {
  const m = {
    date: "2026-10-07",
    foreign: { net_lots: 45210, amt_est: 12_030_000_000 },
    trust: { net_lots: -3000, amt_est: -310_000_000 },
    dealer: { net_lots: 10, amt_est: 800_000 },
    total: { net_lots: 42220, amt_est: 11_720_800_000 },
  };
  const items = instiBriefItems(m);
  assert.deepEqual(items.map((i) => [i.label, i.text]), [["外資", "+120.3億"], ["投信", "-3.1億"], ["自營", "+80萬"]]);
  assert.deepEqual(instiBriefItems(undefined), []);
});

test("指數順序固定 上市 → 上櫃 → 台指期", () => {
  const tpex = { market: "tpex", name: "櫃買指數", date: "2026-10-07", close: 430.46, change: -0.4, chg_pct: -0.09 };
  const twse = { market: "twse", name: "加權指數", date: "2026-10-07", close: 49806.37, change: -16.18, chg_pct: -0.03 };
  const tx = { market: "tx", name: "台指期", date: "2026-10-07", close: 49700, change: -20, chg_pct: -0.04 };
  assert.deepEqual(orderedIndices([tx, tpex, twse]).map((i) => i.market), ["twse", "tpex", "tx"]);
  assert.deepEqual(orderedIndices(undefined), []);
});

test("台指期副標:近月月份與結算;沒有月份 → null", () => {
  assert.equal(txSubtitle({ contract_month: "202610", settlement: 49240 }), "近月 2026/10 · 結算 49,240.00");
  assert.equal(txSubtitle({ contract_month: "202610", settlement: null }), "近月 2026/10");
  assert.equal(txSubtitle({ contract_month: null, settlement: 1 }), null);
  assert.equal(txSubtitle({}), null);
});

test("迷你走勢:path 落在 w×h 內、舊→新、顏色看首尾;不足 2 點不畫", () => {
  const p = sparkPath([1, 3, 2], 40, 16)!;
  assert.match(p, /^M0\.0 15\.0 L20\.0 1\.0 L40\.0 8\.0$/);
  assert.equal(sparkPath([5, 5, 5], 40, 16), "M0.0 8.0 L20.0 8.0 L40.0 8.0");
  assert.equal(sparkPath([1], 40, 16), null);
  assert.equal(sparkPath(undefined, 40, 16), null);
  assert.equal(sparkTone([1, 2]), "up");
  assert.equal(sparkTone([2, 1]), "down");
  assert.equal(sparkTone([2, 2]), "flat");
  assert.equal(sparkTone(undefined), "flat");
});

test("走勢範圍:依交易日數取尾段;區間統計高低與首尾漲跌", () => {
  const pts: TrendPoint[] = Array.from({ length: 300 }, (_, i) => [`d${i}`, 100 + (i % 7), 0, 0]);
  assert.equal(sliceRange(pts, "1m").length, 21);
  assert.equal(sliceRange(pts, "3m").length, 63);
  assert.equal(sliceRange(pts, "6m").length, 126);
  assert.equal(sliceRange(pts, "1y").length, 250);
  assert.equal(sliceRange(pts.slice(0, 10), "1y").length, 10);
  assert.deepEqual(sliceRange(undefined, "1m"), []);
  assert.deepEqual(TREND_RANGES.map((r) => r.label), ["1月", "3月", "6月", "1年"]);
  const s = rangeStats([["a", 100, null, null], ["b", 110, null, null], ["c", 95, null, null], ["d", 105, null, null]])!;
  assert.deepEqual([s.high, s.low, s.change, s.chgPct, s.from, s.to], [110, 95, 5, 5, "a", "d"]);
  assert.equal(rangeStats([]), null);
  assert.equal(rangeTone([["a", 100, null, null], ["b", 90, null, null]]), "down");
  assert.equal(rangeTone([["a", 100, null, null]]), "flat");
});

test("禁詞:標題、標籤、提示", () => {
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const banned = new RegExp([
    word(0x52dd, 0x7387), word(0x7372, 0x5229), word(0x5831, 0x916c), word(0x95dc, 0x9375, 0x5206, 0x9ede),
    word(0x5927, 0x6f32), word(0x5674), word(0x6975, 0x54c1), word(0x6a5f, 0x7387), word(0x76ee, 0x6a19, 0x50f9),
    word(0x8cb7, 0x9032), word(0x8ce3, 0x51fa), word(0x770b, 0x591a), word(0x770b, 0x7a7a), word(0x5c07, 0x6703),
    word(0x6709, 0x6548, 0x652f, 0x6490), word(0x58d3, 0x529b, 0x6c89, 0x91cd), word(0x505a, 0x591a), word(0x505a, 0x7a7a),
    word(0x5efa, 0x8b70), word(0x558a, 0x55ae),
  ].join("|"));
  for (const t of [BRIEF_TITLE, BRIEF_STALE_BADGE, BRIEF_TURNOVER_LABEL, BRIEF_INSTI_LABEL, BRIEF_INSTI_HINT, BRIEF_UPDOWN_HINT,
    TREND_AFFORDANCE, TREND_SHEET_TITLE, TREND_EMPTY, TREND_HINT, ...TREND_RANGES.map((r) => r.label)]) {
    assert.ok(!banned.test(t), t);
  }
  assert.ok(banned.test(word(0x505a, 0x591a)), "regex 本身有效");
});
