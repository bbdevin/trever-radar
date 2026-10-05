// 執行: node --test --experimental-strip-types web/lib/stockLoad.test.ts
//
// 個股載入(docs/44 P1 §3.2):新佈局漸進(core+chips → +hist)、舊資料退回單一檔、
// hist 404 重抓 core、再不行退回舊檔、取消後不再回報、自選頁只抓核心。
import assert from "node:assert/strict";
import { test } from "node:test";

import { fetchStockCore, loadStock, type Fetcher, type StockLoadState } from "./stockLoad.ts";
import type { StockJson } from "./types.ts";

// 值由日期決定(不是索引),core 與 hist 各自切片後接回才會與 FULL 相等。
const candles = (ts: string[]) => ts.map((t) => { const d = Number(t.slice(-2)); return { t, o: d, h: d + 1, l: d - 1, c: d + 0.5, v: 1, amt: 1, af: 1 }; });

const FULL: StockJson = {
  id: "2330", name: "台積電", market: "twse",
  candles: candles(["2023-12-29", "2024-01-02", "2024-01-03"]),
  technical: null, scores: { final: 70 } as never, reasons: [], risks: [],
  branches: [], branch_history: [{ t: "2024-01-03", branches: [] }],
  warrant: null, warrant_history: [], active_warrants: [],
};
const CORE = {
  id: "2330", name: "台積電", market: "twse", candles: candles(["2024-01-02", "2024-01-03"]),
  technical: null, scores: { final: 70 }, reasons: [], risks: [], branches: [],
  warrant: null, warrant_history: [], active_warrants: [],
  parts: { version: 1, hist: { file: "hist/2330.aaaaaaaa.json", bars: 1, cut: "2024-01-01", first: "2023-12-29" }, chips: { file: "chips/2330.json", keys: ["branch_history"] } },
};
const HIST = { version: 1, id: "2330", cut: "2024-01-01", bars: 1, candles: candles(["2023-12-29"]) };
const CHIPS = { version: 1, id: "2330", branch_history: FULL.branch_history };

function fakeFetch(files: Record<string, unknown | (() => unknown)>, log: string[] = []): Fetcher {
  return async (path) => {
    log.push(path);
    const hit = files[path];
    if (hit === undefined) return new Response("not found", { status: 404 });
    const body = typeof hit === "function" ? (hit as () => unknown)() : hit;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  };
}

function collect() {
  const states: StockLoadState[] = [];
  const errors: unknown[] = [];
  const done = new Promise<void>((resolve) => {
    const tick = () => (states.some((s) => s.complete) || errors.length ? resolve() : setTimeout(tick, 5));
    tick();
  });
  return { states, errors, done };
}

test("新佈局:先 core+chips(complete=false),hist 到了 complete=true 且 == 舊單一檔", async () => {
  const log: string[] = [];
  const fetcher = fakeFetch({
    "/data/stocks/core/2330.json": CORE,
    "/data/stocks/chips/2330.json": CHIPS,
    "/data/stocks/hist/2330.aaaaaaaa.json": HIST,
  }, log);
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.deepStrictEqual(errors, []);
  assert.equal(states.length, 2);
  assert.equal(states[0].complete, false);
  assert.deepStrictEqual(states[0].data.candles, CORE.candles);
  assert.deepStrictEqual(states[0].data.branch_history, FULL.branch_history);
  assert.ok(!("parts" in states[0].data));
  assert.equal(states[1].complete, true);
  assert.deepStrictEqual(states[1].data, FULL);
  // 三個檔各抓一次,沒有碰舊單一檔
  assert.deepStrictEqual([...log].sort(), ["/data/stocks/chips/2330.json", "/data/stocks/core/2330.json", "/data/stocks/hist/2330.aaaaaaaa.json"]);
});

test("非聯集核心(parts.hist=null):一次就 complete", async () => {
  const core = { ...CORE, candles: FULL.candles, parts: { ...CORE.parts, hist: null } };
  const fetcher = fakeFetch({ "/data/stocks/core/2330.json": core, "/data/stocks/chips/2330.json": CHIPS });
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.deepStrictEqual(errors, []);
  assert.equal(states.length, 1);
  assert.equal(states[0].complete, true);
  assert.deepStrictEqual(states[0].data, FULL);
});

test("舊資料(core 404):退回 stocks/{id}.json,一次 complete,內容原樣", async () => {
  const log: string[] = [];
  const fetcher = fakeFetch({ "/data/stocks/2330.json": FULL }, log);
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.deepStrictEqual(errors, []);
  assert.equal(states.length, 1);
  assert.deepStrictEqual(states[0], { data: FULL, complete: true });
  assert.deepStrictEqual(log, ["/data/stocks/core/2330.json", "/data/stocks/2330.json"]);
});

test("hist 404(部署瞬間雜湊換了):重抓 core,用新指標抓到 hist", async () => {
  let coreCalls = 0;
  const newCore = { ...CORE, parts: { ...CORE.parts, hist: { ...CORE.parts.hist, file: "hist/2330.bbbbbbbb.json" } } };
  const fetcher = fakeFetch({
    "/data/stocks/core/2330.json": () => (coreCalls++ === 0 ? CORE : newCore),
    "/data/stocks/chips/2330.json": CHIPS,
    "/data/stocks/hist/2330.bbbbbbbb.json": HIST,
  });
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.deepStrictEqual(errors, []);
  assert.equal(coreCalls, 2);
  assert.deepStrictEqual(states.at(-1), { data: FULL, complete: true });
});

test("hist 兩次都 404:退回舊單一檔", async () => {
  const fetcher = fakeFetch({
    "/data/stocks/core/2330.json": CORE,
    "/data/stocks/chips/2330.json": CHIPS,
    "/data/stocks/2330.json": FULL,
  });
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.deepStrictEqual(errors, []);
  assert.deepStrictEqual(states.at(-1), { data: FULL, complete: true });
});

test("core 與舊檔都 404 → onError,沒有 onUpdate", async () => {
  const fetcher = fakeFetch({});
  const { states, errors, done } = collect();
  loadStock("2330", fetcher, (s) => states.push(s), (e) => errors.push(e));
  await done;
  assert.equal(states.length, 0);
  assert.equal(errors.length, 1);
});

test("取消後不再回報(換股)", async () => {
  const fetcher = fakeFetch({ "/data/stocks/2330.json": FULL });
  const states: StockLoadState[] = [];
  const cancel = loadStock("2330", fetcher, (s) => states.push(s), () => assert.fail("不該失敗"));
  cancel();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(states.length, 0);
});

test("fetchStockCore:新佈局只抓核心(不抓 chips/hist);舊資料退回舊檔", async () => {
  const log: string[] = [];
  const core = await fetchStockCore("2330", fakeFetch({ "/data/stocks/core/2330.json": CORE, "/data/stocks/2330.json": FULL }, log));
  assert.equal((core as { parts?: unknown }).parts !== undefined, true);
  assert.deepStrictEqual(log, ["/data/stocks/core/2330.json"]);
  const old = await fetchStockCore("2330", fakeFetch({ "/data/stocks/2330.json": FULL }));
  assert.deepStrictEqual(old, FULL);
  await assert.rejects(fetchStockCore("2330", fakeFetch({})));
});
