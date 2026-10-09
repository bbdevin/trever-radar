// 執行: node --test --experimental-strip-types web/lib/resample.test.ts
//
// 分K(docs/50):5 分 → 30/60 分的交易時段切桶、台北時間標記、退回日K的規則、分K檔抓取。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  barTimeLabel,
  barsForDays,
  chartTimeOf,
  effectiveTf,
  intradayCandles,
  MINUTE_LOADING_NOTICE,
  MINUTE_NONE_NOTICE,
  minuteCaption,
  minuteNotice,
  resample,
  twWallKey,
  type IntradayFile,
} from "./resample.ts";
import { fetchStockIntraday, STOCK_INTRADAY_PATH, type Fetcher } from "./stockLoad.ts";

/** 台北 YYYY-MM-DD HH:MM → epoch 秒 */
const ep = (day: string, hhmm: string) => Date.parse(`${day}T${hhmm}:00+08:00`) / 1000;

/** 一整天 54 根 5 分 K:第 i 根 開=i、高=i+0.5、低=i-0.5、收=i+0.25、量=1(13:25 那根量=10,含收盤)。 */
function fullDay(day: string): IntradayFile["bars"] {
  const out: IntradayFile["bars"] = [];
  for (let i = 0; i < 54; i++) {
    const m = 9 * 60 + i * 5;
    const hhmm = `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
    out.push([ep(day, hhmm), i, i + 0.5, i - 0.5, i + 0.25, i === 53 ? 10 : 1]);
  }
  return out;
}

const FILE: IntradayFile = {
  id: "2330", tf: "5", from: "2026-10-07", to: "2026-10-08", adjusted: false,
  bars: [...fullDay("2026-10-07"), ...fullDay("2026-10-08")],
};

test("twWallKey:epoch → 台北牆上時間(09:00 不是 01:00)", () => {
  assert.equal(twWallKey(ep("2026-10-08", "09:00")), "2026-10-08T09:00");
  assert.equal(twWallKey(ep("2026-10-08", "13:25")), "2026-10-08T13:25");
});

test("chartTimeOf:分K = 台北牆上時間當 UTC 秒;日K照舊字串", () => {
  const t = chartTimeOf("2026-10-08T09:00") as number;
  assert.equal(t, ep("2026-10-08", "09:00") + 8 * 3600);
  assert.equal(new Date(t * 1000).getUTCHours(), 9); // 圖表以 UTC 畫軸 → 顯示 09:00
  assert.equal(chartTimeOf("2026-10-08"), "2026-10-08");
});

test("5 分照原樣,t 為開始時間", () => {
  const cs = intradayCandles(FILE, "5");
  assert.equal(cs.length, 108);
  assert.deepEqual(cs[0], { t: "2026-10-07T09:00", o: 0, h: 0.5, l: -0.5, c: 0.25, v: 1, amt: 0, af: 1 });
  assert.equal(cs[53].t, "2026-10-07T13:25");
  assert.equal(cs[54].t, "2026-10-08T09:00");
});

test("30 分:每天 9 根,13:00 那根涵蓋到 13:30", () => {
  const cs = intradayCandles(FILE, "30");
  assert.equal(cs.length, 18);
  assert.deepEqual(cs.slice(0, 9).map((c) => c.t.slice(11)),
    ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00"]);
  // 09:00 桶 = 5 分第 0..5 根
  assert.deepEqual(cs[0], { t: "2026-10-07T09:00", o: 0, h: 5.5, l: -0.5, c: 5.25, v: 6, amt: 0, af: 1 });
  // 13:00 桶 = 5 分第 48..53 根(含 13:25 那根的收盤量)
  assert.deepEqual(cs[8], { t: "2026-10-07T13:00", o: 48, h: 53.5, l: 47.5, c: 53.25, v: 15, amt: 0, af: 1 });
  assert.equal(cs[9].t, "2026-10-08T09:00"); // 不跨日併桶
});

test("60 分:每天 5 根,13:00 是半小時那根", () => {
  const cs = intradayCandles(FILE, "60");
  assert.equal(cs.length, 10);
  assert.deepEqual(cs.slice(0, 5).map((c) => c.t.slice(11)), ["09:00", "10:00", "11:00", "12:00", "13:00"]);
  assert.equal(cs[0].v, 12);
  assert.deepEqual([cs[4].o, cs[4].c, cs[4].v], [48, 53.25, 15]);
});

test("缺根:某桶裡只有部分 5 分 K 仍成一根,整桶沒有就沒有那根", () => {
  const day = "2026-10-08";
  const file: IntradayFile = { ...FILE, bars: [
    [ep(day, "09:10"), 1, 2, 1, 2, 1],
    [ep(day, "10:05"), 3, 3, 3, 3, 1],
  ] };
  assert.deepEqual(intradayCandles(file, "30").map((c) => c.t.slice(11)), ["09:00", "10:00"]);
  assert.deepEqual(intradayCandles(file, "60").map((c) => [c.t.slice(11), c.o]), [["09:00", 1], ["10:00", 3]]);
});

test("barsForDays:分K以每日根數換算", () => {
  assert.equal(barsForDays(5, "5"), 270);
  assert.equal(barsForDays(20, "30"), 180);
  assert.equal(barsForDays(60, "60"), 300);
  assert.equal(barsForDays(10, "D"), 10);
});

test("resample:分K與日K不經週月重取樣", () => {
  const cs = [{ t: "2026-10-08", o: 1, h: 1, l: 1, c: 1, v: 1, amt: 1, af: 1 }];
  assert.equal(resample(cs, "D"), cs);
  assert.equal(resample(cs, "5"), cs);
});

test("legend 時間:分K MM-DD HH:MM", () => {
  assert.equal(barTimeLabel("2026-10-08T09:05", true), "10-08 09:05");
  assert.equal(barTimeLabel("2026-10-08T13:00", false), "10-08 13:00");
  assert.equal(barTimeLabel("2026-10-08", true), "10-08");
  assert.equal(barTimeLabel("2026-10-08", false), "2026-10-08");
});

test("退回日K:沒提供分K、載入中、沒有檔 → D;有檔才是分K", () => {
  assert.equal(effectiveTf("5", true, "ok"), "5");
  assert.equal(effectiveTf("60", true, "none"), "D");
  assert.equal(effectiveTf("30", true, "loading"), "D");
  assert.equal(effectiveTf("5", false, "ok"), "D"); // 權證分頁等不提供分K的圖
  assert.equal(effectiveTf("W", true, "none"), "W");
  assert.equal(minuteNotice("5", true, "none"), MINUTE_NONE_NOTICE);
  assert.equal(MINUTE_NONE_NOTICE, "此股未提供分K,改看日K");
  assert.equal(minuteNotice("5", true, "loading"), MINUTE_LOADING_NOTICE);
  assert.equal(minuteNotice("5", true, "ok"), null);
  assert.equal(minuteNotice("5", false, "none"), null);
  assert.equal(minuteNotice("D", true, "none"), null);
});

test("分K說明列", () => {
  assert.equal(minuteCaption({ to: "2026-10-08" }), "分K · 原始價(未還原) · 盤後更新至 10-08");
});

test("fetchStockIntraday:404 → null;有檔 → 檔;空檔 → null;其他錯誤丟出", async () => {
  const files: Record<string, unknown> = { [STOCK_INTRADAY_PATH("2330")]: FILE, [STOCK_INTRADAY_PATH("0050")]: { ...FILE, bars: [] } };
  const fetcher: Fetcher = async (path) => {
    if (path.includes("9999")) return new Response("boom", { status: 500 });
    const hit = files[path];
    return hit === undefined ? new Response("not found", { status: 404 }) : new Response(JSON.stringify(hit), { status: 200 });
  };
  assert.equal(STOCK_INTRADAY_PATH("2330"), "/data/stocks/intraday/2330.json");
  assert.deepEqual(await fetchStockIntraday("2330", fetcher), FILE);
  assert.equal(await fetchStockIntraday("1101", fetcher), null);
  assert.equal(await fetchStockIntraday("0050", fetcher), null);
  await assert.rejects(fetchStockIntraday("9999", fetcher));
});

test("禁用詞不出現在分K文案", () => {
  // 用字碼組字(同 changelog.test.ts),避免本測試檔自己被 test_label_honesty 掃到。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const banned = [
    word(0x52dd, 0x7387), word(0x7372, 0x5229), word(0x5831, 0x916c), word(0x95dc, 0x9375, 0x5206, 0x9ede),
    word(0x5927, 0x6f32), word(0x5674), word(0x6975, 0x54c1), word(0x6a5f, 0x7387), word(0x76ee, 0x6a19, 0x50f9),
    word(0x8cb7, 0x9032), word(0x8ce3, 0x51fa), word(0x770b, 0x591a), word(0x770b, 0x7a7a), word(0x5c07, 0x6703),
    word(0x6709, 0x6548, 0x652f, 0x6490), word(0x58d3, 0x529b, 0x6c89, 0x91cd), word(0x505a, 0x591a),
    word(0x505a, 0x7a7a), word(0x5efa, 0x8b70), word(0x558a, 0x55ae),
  ];
  assert.equal(banned.length, 20);
  const copy = [MINUTE_NONE_NOTICE, MINUTE_LOADING_NOTICE, minuteCaption({ to: "2026-10-08" })].join("|");
  for (const w of banned) assert.ok(!copy.includes(w), w);
});
