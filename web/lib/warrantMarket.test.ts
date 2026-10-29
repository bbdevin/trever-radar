// 執行: node --test web/lib/warrantMarket.test.ts
// /branch 權證分點異動的載入狀態(docs/51 §3.5):區間檔、失敗(含 404)不當成無資料、展開明細。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyMarketResult,
  breakdownPath,
  createMarketLoader,
  marketTfPath,
  parseMarketTimeframe,
  breakdownKey,
  classifyStockBreakdowns,
  rowBreakdown,
  type FetchLike,
  type MarketRow,
} from "./warrantMarket.ts";

const ROW: MarketRow = { branch_name: "凱基-台北", underlying_id: "2330", underlying_name: "台積電", net_amount: 6_000_000 };
const BRK = [{ warrant_id: "123456", warrant_name: "台積電凱基5C購01", kind: "call", net_lots: 600, net_amount: 6_000_000 }];
const tfFile = (tf: string, rows: MarketRow[] = [ROW]) => ({ version: 1, threshold: 5_000_000, data_date: "2026-10-22", timeframe: tf, rows });
/** 假 fetch:路徑 → [status, body];記錄呼叫順序。 */
function fakeFetch(routes: Record<string, [number, unknown] | (() => [number, unknown])>) {
  const calls: string[] = [];
  const fn: FetchLike = async (path) => {
    calls.push(path);
    const r = routes[path];
    const [status, body] = typeof r === "function" ? r() : r ?? [404, null];
    if (status === -1) throw new TypeError("Failed to fetch");
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  return { fn, calls };
}

test("路徑:每個區間一個檔,明細抓該股 breakdown 檔", () => {
  assert.equal(marketTfPath("1d"), "/data/branches/warrant_branches_1d.json");
  assert.equal(marketTfPath("120d"), "/data/branches/warrant_branches_120d.json");
  assert.equal(breakdownPath("2330"), "/data/branches/warrant-stock-details/2330.breakdown.json");
});

test("區間檔:格式對才算數;timeframe 不符、缺 rows、版本不對都是 null(失敗,不是無資料)", () => {
  assert.deepEqual(parseMarketTimeframe(tfFile("1d"), "1d"), { data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(parseMarketTimeframe(tfFile("1d", []), "1d"), { data_date: "2026-10-22", rows: [] });
  assert.equal(parseMarketTimeframe(tfFile("2d"), "1d"), null);
  assert.equal(parseMarketTimeframe({ version: 2, timeframe: "1d", rows: [] }, "1d"), null);
  assert.equal(parseMarketTimeframe({ version: 1, timeframe: "1d" }, "1d"), null);
  assert.equal(parseMarketTimeframe(null, "1d"), null);
  assert.equal(parseMarketTimeframe({ ...tfFile("1d"), data_date: "bad" }, "1d")?.data_date, null);
});

test("載入器:有區間檔就只抓它,絕不碰 21 MB 的舊檔", async () => {
  const { fn, calls } = fakeFetch({ [marketTfPath("1d")]: [200, tfFile("1d")] });
  const r = await createMarketLoader(fn)("1d");
  assert.deepEqual(r, { kind: "tf", tf: "1d", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(calls, [marketTfPath("1d")]);
});

test("載入器:404、500、斷線、格式錯都 reject(畫面顯示錯誤＋重試),不去抓舊的全市場檔", async () => {
  for (const route of [[404, null], [500, null], [-1, null], [200, { nope: 1 }]] as [number, unknown][]) {
    const { fn, calls } = fakeFetch({ [marketTfPath("1d")]: route });
    await assert.rejects(createMarketLoader(fn)("1d"));
    assert.deepEqual(calls, [marketTfPath("1d")]);
  }
});

test("載入器:失敗後重試會再抓一次區間檔", async () => {
  let status = 500;
  const { fn, calls } = fakeFetch({ [marketTfPath("1d")]: () => [status, tfFile("1d")] });
  const load = createMarketLoader(fn);
  await assert.rejects(load("1d"));
  status = 200;
  assert.equal((await load("1d")).rows.length, 1);
  assert.deepEqual(calls, [marketTfPath("1d"), marketTfPath("1d")]);
});

test("狀態合併:區間檔只填自己,其他區間不動", () => {
  const s = applyMarketResult({ "2d": { status: "loading" } }, { kind: "tf", tf: "1d", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(s["1d"], { status: "ready", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(s["2d"], { status: "loading" });
});

test("明細檔:同一天 ok;畫面載入後又部署(資料日不同)是 stale 並帶回它自己的資料日;格式錯 bad", () => {
  const file = { version: 1, data_date: "2026-10-22", stock_id: "2330", timeframes: { "1d": { "凱基-台北": BRK } } };
  assert.deepEqual(classifyStockBreakdowns(file, "2330", "2026-10-22"), { kind: "ok", timeframes: file.timeframes });
  // 區間檔還是 10-21、明細已是 10-22:頁面要重抓區間檔,明細存在 10-22 鍵底下。
  assert.deepEqual(classifyStockBreakdowns(file, "2330", "2026-10-21"), { kind: "stale", data_date: "2026-10-22", timeframes: file.timeframes });
  assert.deepEqual(classifyStockBreakdowns(file, "2317", "2026-10-22"), { kind: "bad" });
  assert.deepEqual(classifyStockBreakdowns({ ...file, version: 2 }, "2330", "2026-10-22"), { kind: "bad" });
  assert.deepEqual(classifyStockBreakdowns({ ...file, data_date: 5 }, "2330", "2026-10-22"), { kind: "bad" });
  assert.deepEqual(classifyStockBreakdowns({ ...file, timeframes: [] }, "2330", "2026-10-22"), { kind: "bad" });
  assert.equal(classifyStockBreakdowns({ ...file, data_date: null }, "2330", null).kind, "ok");
});

test("明細快取鍵含資料日:不同資料日的明細不互用(不拼兩個日子)", () => {
  assert.equal(breakdownKey("2026-10-22", "2330"), "2026-10-22|2330");
  assert.notEqual(breakdownKey("2026-10-22", "2330"), breakdownKey("2026-10-23", "2330"));
  assert.equal(breakdownKey(null, "2330"), "null|2330");
});

test("列的明細:依該股快取 → 未抓/載入中/失敗/找到/找不到([])", () => {
  assert.equal(rowBreakdown(ROW, "1d", undefined), undefined);
  assert.equal(rowBreakdown(ROW, "1d", "loading"), "loading");
  assert.equal(rowBreakdown(ROW, "1d", "error"), "error");
  assert.equal(rowBreakdown(ROW, "1d", { "1d": { "凱基-台北": BRK } }), BRK);
  assert.deepEqual(rowBreakdown(ROW, "2d", { "1d": { "凱基-台北": BRK } }), []);
});
