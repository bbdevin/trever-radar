// 執行: node --test web/lib/accumulation.test.ts
//
// 個股頁「囤貨／出貨分點」的判準(見 accumulation.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_VISIBLE,
  HOLD_MIN,
  MAX_ROWS,
  MIN_DAYS,
  MIN_LOTS,
  MIN_SHARE,
  computeWindow,
  definitionText,
  fmtMonthDay,
  fmtShare,
  visibleRows,
  type BranchDay,
} from "./accumulation.ts";

/** n 個連續日期(舊→新),2026-01-01 起 */
function dates(n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(2026, 0, 1 + i));
    return d.toISOString().slice(0, 10);
  });
}

/**
 * 建資料:plan[name] = 每天 net 的陣列(舊→新,0 = 當天不在名單)。
 * branch_history 為新→舊,與正式 JSON 相同。
 */
function build(days: number, plan: Record<string, number[]>, volume = 100) {
  const ds = dates(days);
  const candles = ds.map((t) => ({ t, v: volume }));
  const history: BranchDay[] = ds
    .map((t, i) => ({
      t,
      branches: Object.entries(plan)
        .filter(([, nets]) => (nets[i] ?? 0) !== 0)
        .map(([n, nets]) => ({ n, b: Math.max(nets[i], 0), s: Math.max(-nets[i], 0), net: nets[i] })),
    }))
    .reverse();
  return { candles, history, ds };
}

/** 20 日視窗內,前段放 buys 個買超日(各 +q),接著 sells 個賣超日(各 -1) */
function series(len: number, buys: number, sells: number, q = 100): number[] {
  const out = new Array(len).fill(0);
  for (let i = 0; i < buys; i++) out[i] = q;
  for (let i = 0; i < sells; i++) out[buys + i] = -1;
  return out;
}

const names = (rows: { name: string }[]) => rows.map((r) => r.name);

test("MIN_DAYS boundary: exactly MIN buy days qualifies, one fewer does not", () => {
  const min = MIN_DAYS[20];
  const { candles, history } = build(20, {
    exact: series(20, min, 0),
    short: series(20, min - 1, 0),
  });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["exact"]);
});

/** 前段 buys 個買超日(各 +q),接著依 sellLots 陣列放賣超日 */
function retain(len: number, buys: number, q: number, sellLots: number[]): number[] {
  const out = new Array(len).fill(0);
  for (let i = 0; i < buys; i++) out[i] = q;
  sellLots.forEach((s, i) => (out[buys + i] = -s));
  return out;
}

test("retention boundary (lots): keeping exactly 60% qualifies, 10 lots less does not", () => {
  const { candles, history } = build(20, {
    exact: retain(20, 6, 100, [100, 100, 40]), // 買 600、賣回 240 → 淨 360 = 60%
    below: retain(20, 6, 100, [100, 100, 50]), // 賣回 250 → 淨 350 < 60%
  });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["exact"]);
  assert.equal(r.acc[0].buyLots, 600);
  assert.equal(r.acc[0].sellLots, 240);
  assert.equal(r.acc[0].retainPct, 60);
});

test("size floor (lots): net 50 qualifies, 49 does not (share floor non-binding)", () => {
  const { candles, history } = build(20, {
    at: [10, 10, 10, 10, 10], // 淨 50;成交量 2000 → 佔量門檻 10 張
    under: [10, 10, 10, 10, 9], // 淨 49
  });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["at"]);
});

test("size floor (share): exactly 0.5% of window volume qualifies, just under does not (lot floor non-binding)", () => {
  // 成交量 20×1000 = 20000 → 門檻 100 張
  const { candles, history } = build(
    20,
    { at: [20, 20, 20, 20, 20], under: [20, 20, 20, 20, 19] },
    1000,
  );
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["at"]);
  assert.equal(r.acc[0].net, 100);
  assert.equal(MIN_LOTS, 50);
  assert.equal(MIN_SHARE, 0.005);
});

test("share floor is skipped only when window volume is 0", () => {
  const { candles, history } = build(20, { a: series(20, 5, 0, 10), small: series(20, 5, 0, 9) }, 0);
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["a"]);
  assert.equal(r.acc[0].volumeSharePct, null);
});

test("使用者 2026-10-02:主力大量買、同分點散戶小賣很多天,仍算囤貨(看張數不看天數)", () => {
  // 5 天各買 800 張,另有 10 天各賣 3 張:舊版「買超天數 ≥ 賣超天數 2 倍」會把它剔除
  const { candles, history } = build(20, { whale: retain(20, 5, 800, new Array(10).fill(3)) });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["whale"]);
  assert.equal(r.acc[0].sellDays, 10);
  assert.equal(r.acc[0].net, 3970);
  assert.ok(r.acc[0].retainPct > 99);
});

test("同名分點同一天兩列:先加總成一天,不重複計買超天數", () => {
  const { candles, history } = build(20, { dup: series(20, 5, 0) });
  for (const day of history) {
    const row = day.branches.find((b) => b.n === "dup");
    if (row && row.net) day.branches.push({ ...row });
  }
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.equal(r.acc[0].buyDays, 5);
  assert.equal(r.acc[0].net, 1000);
});

test("recent-dump boundary: last-5 net exactly -0.3x window net qualifies, beyond does not", () => {
  // 6 天買共 1300、最後一天賣 -300 → 期間 +1000,近 5 日 -300(恰好 -0.3 倍)
  const ok = new Array(20).fill(0);
  [300, 200, 200, 200, 200, 200].forEach((q, i) => (ok[i] = q));
  ok[19] = -300;
  const bad = new Array(20).fill(0);
  [310, 200, 200, 200, 200, 200].forEach((q, i) => (bad[i] = q));
  bad[19] = -310; // 期間 +1000,近 5 日 -310
  const { candles, history } = build(20, { ok, bad });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["ok"]);
  assert.equal(r.acc[0].net, 1000);
  assert.equal(r.acc[0].recentNet, -300);
});

test("distributing is the exact mirror", () => {
  const min = MIN_DAYS[20];
  const neg = (xs: number[]) => xs.map((x) => -x);
  const okDump = new Array(20).fill(0);
  [-300, -200, -200, -200, -200, -200].forEach((q, i) => (okDump[i] = q));
  okDump[19] = 300;
  const badDump = new Array(20).fill(0);
  [-310, -200, -200, -200, -200, -200].forEach((q, i) => (badDump[i] = q));
  badDump[19] = 310;
  const { candles, history } = build(20, {
    minExact: neg(series(20, min, 0)),
    minShort: neg(series(20, min - 1, 0)),
    ratioExact: neg(retain(20, 6, 100, [100, 100, 40])),
    ratioBelow: neg(retain(20, 6, 100, [100, 100, 50])),
    lotsAt: neg([10, 10, 10, 10, 10]),
    lotsUnder: neg([10, 10, 10, 10, 9]),
    okDump,
    badDump,
  });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.dist).sort(), ["lotsAt", "minExact", "okDump", "ratioExact"]);
  assert.equal(r.acc.length, 0);
  for (const row of r.dist) assert.ok(row.net < 0);
  const ratio = r.dist.find((x) => x.name === "ratioExact")!;
  assert.equal(ratio.sellLots, 600);
  assert.equal(ratio.buyLots, 240);
  assert.equal(ratio.retainPct, 60);
});

test("distributing share floor: exactly 0.5% of window volume qualifies, just under does not", () => {
  const { candles, history } = build(
    20,
    { at: [-20, -20, -20, -20, -20], under: [-20, -20, -20, -20, -19] },
    1000,
  );
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.deepEqual(names(r.dist), ["at"]);
  assert.equal(r.dist[0].net, -100);
});

test("1-week window: recent check is the whole window and MIN is 3", () => {
  const { candles, history } = build(5, { a: [50, 50, 50, 0, 0], b: [50, 50, 0, 0, 0] });
  const r = computeWindow(history, candles, 5);
  assert.ok(r.available);
  assert.equal(MIN_DAYS[5], 3);
  assert.deepEqual(names(r.acc), ["a"]);
});

test("a day where the branch is not in the top list counts as 0 (neither buy nor sell day)", () => {
  const nets = new Array(20).fill(0);
  [0, 3, 7, 11, 15].forEach((i) => (nets[i] = 100));
  const { candles, history } = build(20, { gappy: nets, other: series(20, 20, 0, 10) });
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  const row = r.acc.find((x) => x.name === "gappy")!;
  assert.equal(row.buyDays, 5);
  assert.equal(row.sellDays, 0);
  assert.equal(row.net, 500);
});

test("history shorter than the window -> unavailable with message", () => {
  const { candles, history } = build(20, { a: series(20, 10, 0) });
  const truncated = history.slice(0, 19); // 少最舊一天
  const r = computeWindow(truncated, candles, 20);
  assert.equal(r.available, false);
  if (!r.available) {
    assert.equal(r.covered, 19);
    assert.equal(r.message, "分點資料只涵蓋 19 天，不足 20 天");
  }
  // 60 日視窗,只有 20 天候選
  const r60 = computeWindow(history, candles, 60);
  assert.equal(r60.available, false);
  // 沒有任何分點資料
  assert.equal(computeWindow(undefined, candles, 5).available, false);
});

test("a missing day inside the window makes it unavailable", () => {
  const { candles, history } = build(20, { a: series(20, 10, 0) });
  const holed = history.filter((_, i) => i !== 7);
  const r = computeWindow(holed, candles, 20);
  assert.equal(r.available, false);
});

test("window ends at the newest branch date when quotes are a day ahead", () => {
  const { candles, history, ds } = build(21, { a: series(21, 10, 0) });
  const lagging = history.slice(1); // 最新一天沒有分點資料
  const r = computeWindow(lagging, candles, 20);
  assert.ok(r.available);
  assert.equal(r.end, ds[19]);
  assert.equal(r.start, ds[0]);
});

test("sorted by |net| desc, capped at MAX_ROWS, totals and counts use the full list", () => {
  const plan: Record<string, number[]> = {};
  for (let k = 1; k <= 25; k++) plan[`b${String(k).padStart(2, "0")}`] = series(20, 5, 0, 10 * k);
  const { candles, history } = build(20, plan, 100);
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  assert.equal(r.accCount, 25);
  assert.equal(r.acc.length, MAX_ROWS);
  assert.equal(r.acc[0].name, "b25");
  assert.equal(r.acc[MAX_ROWS - 1].name, "b06");
  let total = 0;
  for (let k = 1; k <= 25; k++) total += 50 * k;
  assert.equal(r.accTotal, total);
  assert.equal(visibleRows(r.acc, false).length, DEFAULT_VISIBLE);
  assert.equal(visibleRows(r.acc, true).length, MAX_ROWS);
});

test("volume share = |net| / window volume, and last buy / sell date", () => {
  const nets = new Array(20).fill(0);
  [0, 2, 4, 6, 9].forEach((i) => (nets[i] = 90));
  nets[1] = 10; // 90×5 + 10 = 460 張;成交量 20×100 = 2000 → 23%
  const { candles, history, ds } = build(20, { a: nets }, 100);
  const r = computeWindow(history, candles, 20);
  assert.ok(r.available);
  const row = r.acc[0];
  assert.equal(row.net, 460);
  assert.equal(row.buyDays, 6);
  assert.ok(Math.abs((row.volumeSharePct ?? 0) - 23) < 1e-9);
  assert.equal(row.lastDate, ds[9]);
  assert.equal(fmtShare(row.volumeSharePct), "23.0%");

  const sells = new Array(20).fill(0);
  [1, 3, 5, 8, 12].forEach((i) => (sells[i] = -40));
  const b = build(20, { s: sells }, 100);
  const rs = computeWindow(b.history, b.candles, 20);
  assert.ok(rs.available);
  assert.equal(rs.dist[0].lastDate, b.ds[12]);
  assert.equal(rs.distTotal, -200);
});

test("definition text comes from the constants", () => {
  assert.equal(
    definitionText(20, "acc"),
    "囤貨＝期間淨買 ≥50 張且 ≥ 期間成交量 0.5%、買超 ≥5 天、留倉率 ≥60%（賣回不到買進的四成）、近 5 日沒有倒貨（淨賣 ≤ 期間淨買 3 成）",
  );
  assert.equal(
    definitionText(60, "dist"),
    "出貨＝期間淨賣 ≥50 張且 ≥ 近 20 日成交量 0.5%、賣超 ≥10 天、目前空出 ≥ 期間最大賣出部位的 60%（賣出後沒有買回四成以上）、近 5 日沒有回補（淨買 ≤ 期間淨賣 3 成）",
  );
  assert.equal(
    definitionText(120, "acc"),
    "囤貨＝期間淨買 ≥50 張且 ≥ 近 20 日成交量 0.5%、買超 ≥15 天、目前持倉 ≥ 期間最高持倉的 60%（建倉後沒有跑掉四成以上）、近 5 日沒有倒貨（淨賣 ≤ 期間淨買 3 成）",
  );
  assert.ok(definitionText(120, "acc").includes("目前持倉 ≥ 期間最高持倉的 60%"));
  assert.equal(fmtMonthDay("2026-10-01"), "10-01");
  assert.equal(fmtShare(0.04), "<0.1%");
  assert.equal(fmtShare(null), "—");
});

test("6月、1年:門檻依期間延伸,歷史不足整段不列", () => {
  assert.equal(MIN_DAYS[120], 15);
  assert.equal(MIN_DAYS[240], 20);
  const { candles, history } = build(60, { a: new Array(60).fill(0) });
  const r = computeWindow(history, candles, 240);
  assert.equal(r.available, false);
});
/** 偶數日買 +buy、奇數日賣 −sell,共 len 天(len 為奇數時以買日收尾) */
function zigzag(len: number, buy: number, sell: number): number[] {
  return Array.from({ length: len }, (_, i) => (i % 2 === 0 ? buy : -sell));
}

test("長期間改用持倉保有率:留倉率 0.3 但結尾在高點,20 日不過、120 日通過", () => {
  const short = build(20, { z: zigzag(19, 100, 70) });
  const rs = computeWindow(short.history, short.candles, 20);
  assert.ok(rs.available);
  assert.equal(rs.acc.length, 0); // 淨 370 / 買 1000 = 0.37 < 0.6
  assert.equal(HOLD_MIN, 0.6);

  const long = build(120, { z: zigzag(41, 100, 70) });
  const rl = computeWindow(long.history, long.candles, 120);
  assert.ok(rl.available);
  assert.deepEqual(names(rl.acc), ["z"]);
  assert.equal(rl.acc[0].net, 700);
  assert.equal(rl.acc[0].peakNet, 700);
  assert.equal(rl.acc[0].holdPct, 100);
  assert.ok(rl.acc[0].retainPct < 40);
});

test("長期間:建倉後倒出一半(保有 50%)不算囤貨;短期間 holdPct 為 null", () => {
  const plan = new Array(120).fill(0);
  for (let i = 0; i < 20; i++) plan[i] = 100; // 峰值 2000
  for (let i = 20; i < 30; i++) plan[i] = -100; // 剩 1000 = 50%
  const keep = new Array(120).fill(0);
  for (let i = 0; i < 20; i++) keep[i] = 100;
  for (let i = 20; i < 28; i++) keep[i] = -100; // 剩 1200 = 60%
  const { candles, history } = build(120, { dump: plan, keep });
  const r = computeWindow(history, candles, 120);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["keep"]);
  assert.equal(r.acc[0].holdPct, 60);

  const s = build(20, { a: series(20, 5, 0) });
  const rs = computeWindow(s.history, s.candles, 20);
  assert.ok(rs.available);
  assert.equal(rs.acc[0].holdPct, null);
});

test("長期間出貨為鏡像:賣出後買回超過四成不算,holdPct 以最低累計淨持倉計", () => {
  const neg = (xs: number[]) => xs.map((x) => -x);
  const z = build(120, { z: neg(zigzag(41, 100, 70)) });
  const rz = computeWindow(z.history, z.candles, 120);
  assert.ok(rz.available);
  assert.deepEqual(names(rz.dist), ["z"]);
  assert.equal(rz.dist[0].troughNet, -700);
  assert.equal(rz.dist[0].holdPct, 100);

  const plan = new Array(120).fill(0);
  for (let i = 0; i < 20; i++) plan[i] = -100;
  for (let i = 20; i < 30; i++) plan[i] = 100; // 買回一半
  const d = build(120, { dump: plan });
  const rd = computeWindow(d.history, d.candles, 120);
  assert.ok(rd.available);
  assert.equal(rd.dist.length, 0);
});

test("長期間的規模門檻以 20 日均量計,不隨期間放大", () => {
  // 240 天、每天量 1,000 張:整段 24 萬張的 0.5% = 1,200 張;改以 20 日均量 = 2 萬張的 0.5% = 100 張
  const days = 240;
  const series = new Array(days).fill(0);
  for (let i = 0; i < 20; i++) series[i] = 10; // 20 天各買 10 張 → 淨 200 張
  const { candles, history } = build(days, { a: series });
  for (const c of candles) c.v = 1000;
  const r = computeWindow(history, candles, days);
  assert.ok(r.available);
  assert.deepEqual(names(r.acc), ["a"]);
});