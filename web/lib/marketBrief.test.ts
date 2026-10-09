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
  TX_STITCH_NOTE,
  axisTickLabel,
  indexDecimals,
  indexPctText,
  mmdd,
  rangeStats,
  rangeTone,
  sliceRange,
  sparkPath,
  sparkTone,
  txSubtitle,
  type TrendPoint,
  INDEX_INTRADAY_URL,
  INTRADAY_EMPTY,
  INTRADAY_HINT,
  PREV_CLOSE_LABEL,
  TREND_RANGE_DEFAULT,
  TX_INTRADAY_EMPTY,
  TX_INTRADAY_NOTE,
  changeVsPrev,
  hhmmOf,
  intradayStats,
  intradayTone,
  prevCloseBefore,
  type IntradayPoint,
} from "./marketBrief.ts";
import { tickMarkLabel } from "./chartTime.ts";
import { chartTimeOf, twWallKey } from "./resample.ts";

test("指數:千分位兩位小數,與來源同字;台指期整數", () => {
  assert.equal(fmtIndex(49313.44), "49,313.44");
  assert.equal(fmtIndex(426.71), "426.71");
  assert.equal(fmtIndex(426.7), "426.70");
  assert.equal(indexDecimals("tx"), 0);
  assert.equal(indexDecimals("twse"), 2);
  assert.equal(fmtIndex(49700, indexDecimals("tx")), "49,700");
  assert.equal(fmtIndex(49700.4, 0), "49,700");
});

test("漲跌字串:箭頭＋點數＋百分比,正負都在字裡;缺值退化;台指期點數整數", () => {
  assert.equal(indexChangeText(-492.93, -0.99), "▼492.93 · -0.99%");
  assert.equal(indexChangeText(244.27, 0.65), "▲244.27 · +0.65%");
  assert.equal(indexChangeText(0, 0), "0.00 · 0.00%");
  assert.equal(indexChangeText(-3.75, null), "▼3.75");
  assert.equal(indexChangeText(null, -0.87), "-0.87%");
  assert.equal(indexChangeText(null, null), "—");
  assert.equal(indexChangeText(-30, -0.06, 0), "▼30 · -0.06%");
});

test("卡片格只放 %:「▼0.99%」;缺 % 退回點數", () => {
  assert.equal(indexPctText(-492.93, -0.99), "▼0.99%");
  assert.equal(indexPctText(244.27, 0.65), "▲0.65%");
  assert.equal(indexPctText(0, 0), "0.00%");
  assert.equal(indexPctText(-30, null, 0), "▼30");
  assert.equal(indexPctText(null, null), "—");
});

test("時間軸刻度與游標日期:年 → 2026年、月 → 9月、日 → 10/07", () => {
  assert.equal(axisTickLabel("2026-10-07", 0), "2026年");
  assert.equal(axisTickLabel("2026-09-01", 1), "9月");
  assert.equal(axisTickLabel("2026-10-07", 2), "10/07");
  assert.equal(axisTickLabel("odd", 2), "odd");
  assert.equal(mmdd("2026-10-07"), "10/07");
  assert.ok(TX_STITCH_NOTE.includes("未調整換月價差"));
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

test("台指期副標:近月月份與整數結算;結算 0(最後交易日)或缺 → 不顯示;沒有月份 → null", () => {
  assert.equal(txSubtitle({ contract_month: "202610", settlement: 49240 }), "近月 2026/10 · 結算 49,240");
  assert.equal(txSubtitle({ contract_month: "202610", settlement: null }), "近月 2026/10");
  assert.equal(txSubtitle({ contract_month: "202609", settlement: 0 }), "近月 2026/09");
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
  assert.deepEqual(TREND_RANGES.map((r) => r.label), ["1日", "1月", "3月", "6月", "1年"]);
  assert.equal(TREND_RANGE_DEFAULT, "3m");
  const s = rangeStats([["a", 100, null, null], ["b", 110, null, null], ["c", 95, null, null], ["d", 105, null, null]])!;
  assert.deepEqual([s.high, s.low, s.change, s.chgPct, s.from, s.to], [110, 95, 5, 5, "a", "d"]);
  assert.equal(rangeStats([]), null);
  assert.equal(rangeTone([["a", 100, null, null], ["b", 90, null, null]]), "down");
  assert.equal(rangeTone([["a", 100, null, null]]), "flat");
});

// 2026-10-08 台北;epoch 為真實 UTC 秒(09:00 台北 = 01:00Z),與 pipeline indices_intraday 同一個慣例
const ep = (hhmm: string) => Date.parse(`2026-10-08T${hhmm}:00+08:00`) / 1000;

test("1日:時間一律台北 HH:MM,與瀏覽器時區無關;圖表 time 走 chartTimeOf(twWallKey)", () => {
  assert.equal(hhmmOf(ep("09:00")), "09:00");
  assert.equal(hhmmOf(ep("13:30")), "13:30");
  assert.equal(hhmmOf(ep("08:45")), "08:45");
  const t = chartTimeOf(twWallKey(ep("09:05")));
  assert.equal(t, ep("09:05") + 8 * 3600);
  // 元件的時間軸刻度與游標標籤都用 tickMarkLabel(t, 3)
  assert.equal(tickMarkLabel(t, 3), "09:05");
  assert.equal(tickMarkLabel(chartTimeOf(twWallKey(ep("13:30"))), 3), "13:30");
});

test("1日基準:歷史檔裡早於當日的最後一列收盤(歷史檔已含今天時跳過今天)", () => {
  const hist: TrendPoint[] = [["2026-10-06", 100, null, null], ["2026-10-07", 110, null, null], ["2026-10-08", 105, null, null]];
  assert.equal(prevCloseBefore(hist, "2026-10-08"), 110);
  assert.equal(prevCloseBefore(hist.slice(0, 2), "2026-10-08"), 110); // 歷史檔還沒有今天
  assert.equal(prevCloseBefore(hist, "2026-10-07"), 100); // 日內檔是前一天的
  assert.equal(prevCloseBefore(hist, "2026-10-06"), null);
  assert.equal(prevCloseBefore(undefined, "2026-10-08"), null);
});

test("1日:相對前收漲跌、日高日低、線色跟當日漲跌", () => {
  assert.deepEqual(changeVsPrev(49313.44, 49806.37), { change: -492.93, chgPct: -0.99 });
  assert.deepEqual(changeVsPrev(110, 100), { change: 10, chgPct: 10 });
  assert.deepEqual(changeVsPrev(110, null), { change: null, chgPct: null });
  assert.equal(indexChangeText(-492.93, -0.99), "▼492.93 · -0.99%");

  const pts: IntradayPoint[] = [[ep("09:00"), 49411.36], [ep("10:00"), 49900], [ep("11:00"), 49200], [ep("13:30"), 49313.44]];
  const s = intradayStats(pts, 49806.37)!;
  assert.deepEqual([s.high, s.low, s.last, s.change, s.chgPct, s.from, s.to], [49900, 49200, 49313.44, -492.93, -0.99, "09:00", "13:30"]);
  assert.equal(intradayStats([], 1), null);
  const noPrev = intradayStats(pts, null)!;
  assert.deepEqual([noPrev.change, noPrev.chgPct], [null, null]);
  // 收在前收之下 → 綠,即使開盤後一路比 09:00 那根低也一樣看前收
  assert.equal(intradayTone(pts, 49806.37), "down");
  assert.equal(intradayTone(pts, 49000), "up");
  assert.equal(intradayTone(pts, 49313.44), "flat");
  assert.equal(intradayTone(pts, null), "down"); // 沒有前收:首尾相比
  assert.equal(intradayTone([], 1), "flat");
  assert.equal(INDEX_INTRADAY_URL, "/data/market/indices_intraday.json");
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
    TREND_AFFORDANCE, TREND_SHEET_TITLE, TREND_EMPTY, TREND_HINT, TX_STITCH_NOTE, ...TREND_RANGES.map((r) => r.label),
    INTRADAY_EMPTY, TX_INTRADAY_EMPTY, INTRADAY_HINT, TX_INTRADAY_NOTE, PREV_CLOSE_LABEL, "日高", "日低", "日漲跌"]) {
    assert.ok(!banned.test(t), t);
  }
  assert.ok(banned.test(word(0x505a, 0x591a)), "regex 本身有效");
});
