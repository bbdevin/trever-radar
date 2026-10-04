// 執行: node --test --experimental-strip-types web/lib/priceLevels.test.ts
//
// 價格位置(docs/45)的句型、排序、上下各 ≤5、精度、禁用詞鎖、舊 JSON 相容。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  HOWTO_LINES,
  MAX_ROWS_PER_SIDE,
  PL_LABELS,
  chartLevels,
  fmtDist,
  fmtLevelPrice,
  insufficientText,
  priceLevelFacts,
  priceLevelsView,
  pricePrecision,
  volumeSplitText,
} from "./priceLevels.ts";
import type { Candle, PriceLevels } from "./types.ts";

// 禁用詞清單以「·」拆開或用字碼組回,避免這個檔案本身被 test_label_honesty 掃到。
const BANNED = [
  "勝·率", "獲·利", "報·酬", "關鍵·分點", "大·漲", "極·品", "機·率",
  "目標·價", "買·進", "賣·出", "看·多", "看·空", "將·會", "有效·支撐", "壓力·沉重", "做·多", "做·空", "建·議", "喊·單",
].map((w) => w.replace("·", "")).concat(String.fromCharCode(0x5674));

function ok(over: Partial<Extract<PriceLevels, { status: "ok" }>> = {}): Extract<PriceLevels, { status: "ok" }> {
  return {
    version: 1,
    status: "ok",
    as_of: "2026-10-03",
    bars: 240,
    close: 120,
    ma: { "5": 121, "10": 118.9, "20": 125, "60": 128.4, "120": 110, "240": 100 },
    ma_align: "bear",
    highs: {
      "20": { p: 126, t: "2026-09-25" },
      "60": { p: 135, t: "2026-09-12" },
      "120": { p: 135, t: "2026-09-12" },
      "240": { p: 150, t: "2026-02-03" },
    },
    lows: {
      "20": { p: 112.5, t: "2026-09-28" },
      "60": { p: 105, t: "2026-08-01" },
      "120": { p: 90, t: "2026-05-01" },
      "240": { p: 80, t: "2025-12-01" },
    },
    new_high_20: false,
    new_low_20: false,
    vol_price_2d: null,
    vol_profile: { window: 120, above: 0.38, below: 0.62, at: 0 },
    dense_above: { lo: 124, hi: 125.2, share: 0.08 },
    dense_below: { lo: 116.4, hi: 117.6, share: 0.06 },
    ...over,
  };
}

test("舊 JSON 沒有 price_levels → missing,不丟例外", () => {
  assert.deepEqual(priceLevelsView(undefined), { state: "missing" });
  assert.deepEqual(priceLevelsView(null), { state: "missing" });
  assert.deepEqual(chartLevels(undefined), []);
});

test("K 棒不足 → insufficient", () => {
  const v = priceLevelsView({ version: 1, status: "insufficient", as_of: "2026-10-03", bars: 12 });
  assert.deepEqual(v, { state: "insufficient", asOf: "2026-10-03", bars: 12 });
  assert.match(insufficientText(12), /12 根/);
});

test("階梯:由高到低、上下各 ≤5、同價同日合併標最長視窗", () => {
  const v = priceLevelsView(ok());
  assert.equal(v.state, "ok");
  if (v.state !== "ok") return;
  assert.ok(v.above.length <= MAX_ROWS_PER_SIDE && v.below.length <= MAX_ROWS_PER_SIDE);
  const top = (r: { price: number; priceHi?: number }) => r.priceHi ?? r.price;
  for (const side of [v.above, v.below]) {
    for (let i = 1; i < side.length; i += 1) assert.ok(top(side[i - 1]) >= top(side[i]));
  }
  assert.ok(v.above.every((r) => r.dist >= 0));
  assert.ok(v.below.every((r) => r.dist < 0));
  // 60 與 120 日最高同價同日 → 只剩一列,標 120
  const highs = v.above.filter((r) => r.kind === "high").map((r) => r.label);
  assert.deepEqual(highs, ["240日最高", "120日最高", "20日最高"]);
  assert.equal(v.above.find((r) => r.label === "120日最高")?.date, "09/12");
  // 上方:3 個前高 + 密集區 = 4,剩 1 格給最近的均線(5日 121,不是 20日 125 或 60日 128.4)
  const mas = v.above.filter((r) => r.kind === "ma").map((r) => r.label);
  assert.deepEqual(mas, ["5日均線"]);
  // 下方:4 個前低 + 密集區 = 5,均線全被擠掉
  assert.equal(v.below.length, 5);
  assert.equal(v.below.filter((r) => r.kind === "ma").length, 0);
});

test("均線與現價相等歸上方", () => {
  const pl = ok({ ma: { "5": 120 }, highs: {}, lows: {}, dense_above: null, dense_below: null });
  const v = priceLevelsView(pl);
  if (v.state !== "ok") throw new Error("state");
  assert.equal(v.above[0].label, "5日均線");
  assert.equal(v.above[0].dist, 0);
  assert.deepEqual(priceLevelFacts(pl, "2026-10-03").map((f) => f.text), ["5 日線在上方,最接近 5日線 120.0(0.0%)", "5/10/20日均線空頭排列"]);
});

test("多空事實句與鏡像", () => {
  const pl = ok({
    ma_align: "bull",
    new_high_20: true,
    vol_price_2d: "up",
    highs: { "20": { p: 125, t: "2026-10-03" }, "60": { p: 125, t: "2026-10-03" }, "120": { p: 140, t: "2026-06-01" } },
  });
  const f = priceLevelFacts(pl, "2026-10-03", 64);
  // F3(今日即 60 日最高)與 F4(收盤創 20 日新高)同側 → 合併成一句
  assert.deepEqual(f.filter((x) => x.side === "bull").map((x) => x.text), [
    "站上 10/120/240 日線,最接近 10日線 118.9(−0.9%)",
    "5/10/20日均線多頭排列",
    "收盤創20日新高,今日高點亦為 60 日最高",
    "連2日量增價漲",
    "RSI14 64,位於 50–70",
  ]);
  assert.ok(!f.some((x) => x.code === "F3_HIGH_TODAY"));
  assert.deepEqual(f.filter((x) => x.side === "bear").map((x) => x.text), ["5/20/60 日線在上方,最接近 5日線 121.0(+0.8%)"]);
  // F1 進壓力段、帶距離;其餘進技術段日K;價格是 price 段
  const f1 = f.find((x) => x.code === "F1_MA_ABOVE")!;
  assert.deepEqual([f1.section, f1.tf, f1.dist?.toFixed(2)], ["levels", "D", "0.83"]);
  assert.deepEqual(f1.segments?.filter((s) => s.kind), [{ t: "121.0", kind: "price" }, { t: "+0.8%", kind: "up" }]);
  assert.ok(f.filter((x) => !x.code.startsWith("F1")).every((x) => x.section === "tech" && x.tf === "D"));
  // 只有今日即最高、沒有創 20 日新高 → F3 單獨一句
  const only = priceLevelFacts(ok({ highs: { "60": { p: 125, t: "2026-10-03" } } }), "2026-10-03");
  assert.ok(only.some((x) => x.code === "F3_HIGH_TODAY" && x.text === "今日即60日最高"));
  // 20 日線在上方 → F1 多方不宣告 T1_MA20;其餘鏡像照宣告
  assert.deepEqual(f.find((x) => x.code === "F1_MA_BELOW")?.mirrors, undefined);
  assert.deepEqual(f.find((x) => x.code === "F2_BULL")?.mirrors, ["T1_BULL_MA"]);
  assert.deepEqual(f.find((x) => x.code === "F8_RSI_OK")?.mirrors, ["T5_RSI"]);
  // 今日即最高的不進階梯
  const v = priceLevelsView(pl);
  if (v.state !== "ok") throw new Error("state");
  assert.ok(!v.above.some((r) => r.date === "10/03"));

  const w = priceLevelFacts(ok({ new_low_20: true, vol_price_2d: "down", lows: { "20": { p: 119, t: "2026-10-03" } } }), "2026-10-03", 38.04);
  assert.deepEqual(w.filter((x) => x.side === "bear").map((x) => x.text), [
    "5/20/60 日線在上方,最接近 5日線 121.0(+0.8%)",
    "5/10/20日均線空頭排列",
    "收盤創20日新低",
    "連2日量增價跌",
    "RSI14 38,低於 50",
  ]);
  // RSI 70–80 兩邊都不列
  assert.ok(!priceLevelFacts(ok(), "2026-10-03", 75).some((x) => x.code.startsWith("F8")));
  // 站上 20/60 → 宣告 T1_MA20、T1_MA60
  const up = priceLevelFacts(ok({ ma: { "20": 100, "60": 90 } }), "2026-10-03");
  assert.deepEqual(up[0].mirrors, ["T1_MA20", "T1_MA60"]);
});

test("as_of 不是最新 K 棒日 → 每句帶日期、不宣告鏡像", () => {
  const f = priceLevelFacts(ok({ ma_align: "bull" }), "2026-10-06", 60);
  assert.ok(f.length > 0);
  assert.ok(f.every((x) => x.date === "10/03" && x.mirrors === undefined));
  assert.deepEqual(priceLevelFacts(null, "2026-10-03"), []);
  assert.deepEqual(priceLevelFacts({ version: 1, status: "insufficient", as_of: "2026-10-03", bars: 3 }), []);
});

test("精度與正負號", () => {
  assert.equal(pricePrecision(1085), 0);
  assert.equal(pricePrecision(120), 1);
  assert.equal(pricePrecision(23.5), 2);
  assert.equal(fmtLevelPrice(1593.84, 1085), "1,594");
  assert.equal(fmtLevelPrice(135, 120), "135.0");
  assert.equal(fmtLevelPrice(12.3, 23.5), "12.30");
  assert.equal(fmtDist(12.49), "+12.5%");
  assert.equal(fmtDist(-6.25), "−6.3%");
  assert.equal(fmtDist(0.01), "0.0%");
  assert.equal(volumeSplitText({ window: 120, above: 0.384, below: 0.616 }), "近120日成交:現價之上 38%、之下 62%");
});

test("K 線價位線:上下各 ≤2、取最近、有日期的換回原始價", () => {
  const candles = [
    { t: "2026-09-12", o: 0, h: 0, l: 0, c: 0, v: 0, amt: 0, af: 0.5 },
    { t: "2026-10-03", o: 0, h: 0, l: 0, c: 120, v: 0, amt: 0, af: 1 },
  ] as Candle[];
  const lv = chartLevels(ok(), candles);
  const above = lv.filter((l) => l.side === "above");
  const below = lv.filter((l) => l.side === "below");
  assert.equal(above.length, 2);
  assert.equal(below.length, 2);
  assert.deepEqual(above.map((l) => l.label), ["密集區", "20日高"]);
  assert.deepEqual(below.map((l) => l.label), ["密集區", "20日低"]);
  // 120 日最高在 af=0.5 那天 → 原始價 270
  const far = chartLevels(ok({ highs: { "120": { p: 135, t: "2026-09-12" } }, dense_above: null }), candles, 2);
  assert.equal(far.find((l) => l.label === "120日高")?.price, 270);
  // 沒有 af 資料 → 用還原價
  assert.equal(chartLevels(ok({ highs: { "120": { p: 135, t: "2026-09-12" } }, dense_above: null }))[0].price, 135);
});

test("禁用詞鎖:所有會上畫面的字", () => {
  const texts: string[] = [...HOWTO_LINES, insufficientText(3), ...Object.values(PL_LABELS)];
  for (const pl of [ok(), ok({ ma_align: "bull", new_high_20: true, vol_price_2d: "up" }), ok({ new_low_20: true, vol_price_2d: "down" })]) {
    for (const rsi of [30, 60, 90]) {
      texts.push(...priceLevelFacts(pl, "2026-10-03", rsi).map((f) => f.text));
      const v = priceLevelsView(pl);
      if (v.state !== "ok") continue;
      texts.push(...[...v.above, ...v.below].map((r) => r.label));
      if (v.volume) texts.push(volumeSplitText(v.volume));
    }
    texts.push(...chartLevels(pl).map((l) => l.label));
  }
  for (const t of texts) for (const w of BANNED) assert.ok(!t.includes(w), `「${t}」含禁用詞「${w}」`);
});
