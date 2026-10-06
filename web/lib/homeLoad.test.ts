// 執行: node --test --experimental-strip-types web/lib/homeLoad.test.ts
//
// 首頁拆檔載入(docs/44 P2):head 先、stocks 後;舊資料退回 radar.json;兩輪夾到靠 generated_at 對齊;
// 任何一步抓不到都退回 radar.json;舊佈局一次到齊。
import assert from "node:assert/strict";
import { test } from "node:test";

import { HOME_HEAD_PATH, HOME_STOCKS_PATH, RADAR_PATH, loadHomeHead, loadHomeStocks, type Fetcher, type HomeData } from "./homeLoad.ts";
import type { RadarJson, RadarStock } from "./types.ts";

const stock = (id: string, extra: Record<string, unknown> = {}): RadarStock =>
  ({
    id, name: `股${id}`, market: "twse", industry: "半導體", close: 100, chg_pct: 1.5, volume_ratio: 1.1, turnover: 1e9,
    foreign_net_lots: 10, trust_net_lots: null, warrant: { call_turnover: 1e8, call_turnover_ratio: 1.3, call_count: 5 },
    scores: null, reasons: [], risks: [], spark: [1, 2, 3], ...extra,
  }) as RadarStock;

const RADAR: RadarJson = {
  data_date: "2026-10-06", generated_at: "2026-10-06T17:40:00+08:00", note: "n",
  summary: [{ market: "twse", turnover: 1, up: 1, down: 0 }], sectors: [], themes: [],
  lists: { score: [], hot: ["2330"], surge: [], strong: [], weak: [], warrant: [], armed: ["2330"], triggered: [], extended: [], faded: [], pocket: [] },
  concentration: [{ id: "2330", name: "x", market: "twse", buy_concentration: 0.1, concentration_avg20: 0.05, vs20: 2 }],
  stocks: [stock("2330", { technical: { score: 1 }, volume_lots: 3 })],
};
const HEAD = (generated_at = RADAR.generated_at) => {
  const { stocks: _s, concentration: _c, ...rest } = RADAR;
  return { version: 1, ...rest, generated_at };
};
const STOCKS = (generated_at = RADAR.generated_at) => ({
  version: 1, data_date: RADAR.data_date, generated_at, stocks: [stock("2330")],
});

function fakeFetch(files: Record<string, unknown | (() => unknown)>, log: string[] = []): Fetcher {
  return async (path) => {
    log.push(path);
    const hit = files[path];
    if (hit === undefined) return new Response("not found", { status: 404 });
    if (hit instanceof Error) throw hit;
    const body = typeof hit === "function" ? (hit as () => unknown)() : hit;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  };
}

test("拆檔佈局:head 先到,stocks 為 null;要用時再抓,同一輪就直接接上", async () => {
  const log: string[] = [];
  const fetcher = fakeFetch({ [HOME_HEAD_PATH]: HEAD(), [HOME_STOCKS_PATH]: STOCKS() }, log);
  const home = await loadHomeHead(fetcher);
  assert.equal(home.layout, "split");
  assert.equal(home.stocks, null);
  assert.equal(home.head.data_date, "2026-10-06");
  assert.deepStrictEqual(home.head.lists.armed, ["2330"]);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH]);

  const full = await loadHomeStocks(fetcher, home);
  assert.equal(full.layout, "split");
  assert.equal(full.head, home.head);
  assert.deepStrictEqual(full.stocks, [stock("2330")]);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, HOME_STOCKS_PATH]);

  // 已經有 stocks:原樣回傳、不再抓
  assert.equal(await loadHomeStocks(fetcher, full), full);
  assert.equal(log.length, 2);
});

test("舊資料(沒有 home/):退回 radar.json 一次到齊,head = radar 扣掉 stocks", async () => {
  const log: string[] = [];
  const fetcher = fakeFetch({ [RADAR_PATH]: RADAR }, log);
  const home = await loadHomeHead(fetcher);
  assert.equal(home.layout, "legacy");
  assert.deepStrictEqual(home.stocks, RADAR.stocks);
  assert.ok(!("stocks" in home.head));
  const { stocks: _s, ...rest } = RADAR;
  assert.deepStrictEqual(home.head, rest);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, RADAR_PATH]);
  // 舊佈局已經有 stocks → loadHomeStocks 不再發請求
  assert.equal(await loadHomeStocks(fetcher, home), home);
  assert.equal(log.length, 2);
});

test("head 抓到但 stocks 404(部署空窗):退回 radar.json", async () => {
  const log: string[] = [];
  const fetcher = fakeFetch({ [HOME_HEAD_PATH]: HEAD(), [RADAR_PATH]: RADAR }, log);
  const home = await loadHomeHead(fetcher);
  const full = await loadHomeStocks(fetcher, home);
  assert.equal(full.layout, "legacy");
  assert.deepStrictEqual(full.stocks, RADAR.stocks);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, HOME_STOCKS_PATH, RADAR_PATH]);
});

test("head 網路錯誤:退回 radar.json;radar.json 也失敗才丟錯", async () => {
  const fetcher = fakeFetch({ [HOME_HEAD_PATH]: new Error("net"), [RADAR_PATH]: RADAR });
  const home = await loadHomeHead(fetcher);
  assert.equal(home.layout, "legacy");
  const dead = fakeFetch({ [HOME_HEAD_PATH]: new Error("net"), [RADAR_PATH]: new Error("net") });
  await assert.rejects(loadHomeHead(dead));
  const gone = fakeFetch({});
  await assert.rejects(loadHomeHead(gone));
});

test("兩輪夾到:stocks 是新輪 → 重抓 head,拿到同輪就用新輪的一對", async () => {
  const log: string[] = [];
  const NEW = "2026-10-06T22:00:00+08:00";
  let headCalls = 0;
  const fetcher = fakeFetch({
    [HOME_HEAD_PATH]: () => (headCalls++ === 0 ? HEAD() : HEAD(NEW)),
    [HOME_STOCKS_PATH]: STOCKS(NEW),
  }, log);
  const home = await loadHomeHead(fetcher);
  assert.equal(home.head.generated_at, RADAR.generated_at);
  const full = await loadHomeStocks(fetcher, home);
  assert.equal(full.layout, "split");
  assert.equal(full.head.generated_at, NEW);
  assert.deepStrictEqual(full.stocks, [stock("2330")]);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, HOME_STOCKS_PATH, HOME_HEAD_PATH]);
});

test("兩輪夾到:重抓的 head 又比 stocks 新 → 再抓一次 stocks;對上就用", async () => {
  const log: string[] = [];
  const NEW = "2026-10-06T22:00:00+08:00";
  const NEWER = "2026-10-07T00:05:00+08:00";
  let headCalls = 0;
  let stocksCalls = 0;
  const fetcher = fakeFetch({
    [HOME_HEAD_PATH]: () => (headCalls++ === 0 ? HEAD() : HEAD(NEWER)),
    [HOME_STOCKS_PATH]: () => (stocksCalls++ === 0 ? STOCKS(NEW) : STOCKS(NEWER)),
  }, log);
  const full = await loadHomeStocks(fetcher, await loadHomeHead(fetcher));
  assert.equal(full.layout, "split");
  assert.equal(full.head.generated_at, NEWER);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, HOME_STOCKS_PATH, HOME_HEAD_PATH, HOME_STOCKS_PATH]);
});

test("兩輪夾到兩次都對不上:退回 radar.json(一個檔永遠自洽)", async () => {
  const log: string[] = [];
  let n = 0;
  const tick = () => `2026-10-06T17:4${n++}:00+08:00`;
  const fetcher = fakeFetch({
    [HOME_HEAD_PATH]: () => HEAD(tick()),
    [HOME_STOCKS_PATH]: () => STOCKS(tick()),
    [RADAR_PATH]: RADAR,
  }, log);
  const full = await loadHomeStocks(fetcher, await loadHomeHead(fetcher));
  assert.equal(full.layout, "legacy");
  assert.deepStrictEqual(full.stocks, RADAR.stocks);
  assert.deepStrictEqual(log, [HOME_HEAD_PATH, HOME_STOCKS_PATH, HOME_HEAD_PATH, HOME_STOCKS_PATH, RADAR_PATH]);
});

test("卡片讀的欄位都不在投影丟掉的清單裡(StockCard / ThemeGroupedList / 族群 / 期貨股名)", async () => {
  const { HOME_DROPPED_STOCK, HOME_DROPPED_TOP, HOME_WARRANT_KEYS } = await import("./homeLoad.ts");
  const cardReads = [
    "id", "name", "market", "industry", "themes", "description", "close", "chg_pct", "spark", "spark_day", "spark_open",
    "turnover", "volume_ratio", "foreign_net_lots", "trust_net_lots", "scores", "warrant", "risks", "reasons", "raw_reasons",
    "state", "sources", "strategy_signals", "pocket_tags",
  ];
  for (const k of cardReads) assert.ok(!HOME_DROPPED_STOCK.includes(k), k);
  for (const k of ["call_turnover", "call_turnover_ratio", "call_count"]) assert.ok(HOME_WARRANT_KEYS.includes(k), k);
  const headReads = [
    "data_date", "generated_at", "note", "pocket_note", "summary", "freshness", "sectors", "themes", "lists",
    "strategies", "strategy_phases", "strategy_meta", "futures_volume_anomalies", "futures_volume_anomalies_meta",
    "futures_volume_anomaly_history", "futures_volume_anomaly_history_meta", "futures_open_interest_direction",
  ];
  for (const k of headReads) assert.ok(!HOME_DROPPED_TOP.includes(k), k);
});

test("型別:HomeData 的 head 可以直接餵給多方榜(Pick<RadarJson, data_date|generated_at> & Partial<…>)", () => {
  const home: HomeData = { head: HEAD(), stocks: null, layout: "split" };
  const ctx: Pick<RadarJson, "data_date" | "generated_at"> & Partial<Pick<RadarJson, "stocks" | "themes" | "sectors">> = {
    ...home.head, stocks: home.stocks ?? undefined,
  };
  assert.equal(ctx.data_date, "2026-10-06");
  assert.equal(ctx.stocks, undefined);
});
