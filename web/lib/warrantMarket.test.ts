// 執行: node --test web/lib/warrantMarket.test.ts
// /branch 權證分點異動的載入狀態(docs/51 §3.5):區間檔、404 退回舊檔、失敗不當成無資料、展開明細。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MARKET_LEGACY_PATH,
  applyMarketResult,
  breakdownPath,
  createMarketLoader,
  marketTfPath,
  parseLegacyMarket,
  parseMarketTimeframe,
  parseStockBreakdowns,
  rowBreakdown,
  type FetchLike,
  type MarketRow,
} from "./warrantMarket.ts";

const ROW: MarketRow = { branch_name: "凱基-台北", underlying_id: "2330", underlying_name: "台積電", net_amount: 6_000_000 };
const BRK = [{ warrant_id: "123456", warrant_name: "台積電凱基5C購01", kind: "call", net_lots: 600, net_amount: 6_000_000 }];
const tfFile = (tf: string, rows: MarketRow[] = [ROW]) => ({ version: 1, threshold: 5_000_000, data_date: "2026-10-22", timeframe: tf, rows });
const legacyFile = {
  version: 1, threshold: 5_000_000, data_date: "2026-10-22",
  timeframes: { "1d": [{ ...ROW, breakdown: BRK }], "2d": [], "5d": [], "30d": [], "120d": [] },
};

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

test("舊全市場檔:v1 wrapper 與裸 mapping 都讀;裸 mapping 不捏造資料日;缺的區間是空陣列", () => {
  const w = parseLegacyMarket(legacyFile);
  assert.equal(w?.data_date, "2026-10-22");
  assert.equal(w?.timeframes["1d"].length, 1);
  const bare = parseLegacyMarket({ "1d": [ROW] });
  assert.equal(bare?.data_date, null);
  assert.deepEqual(bare?.timeframes["120d"], []);
  assert.equal(parseLegacyMarket(null), null);
  assert.equal(parseLegacyMarket([1, 2]), null);
});

test("載入器:有區間檔就只抓它,絕不碰 21 MB 的舊檔", async () => {
  const { fn, calls } = fakeFetch({ [marketTfPath("1d")]: [200, tfFile("1d")] });
  const r = await createMarketLoader(fn)("1d");
  assert.deepEqual(r, { kind: "tf", tf: "1d", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(calls, [marketTfPath("1d")]);
});

test("載入器:區間檔 404(程式碼先於匯出上線)才退回舊檔,且舊檔只抓一次", async () => {
  const { fn, calls } = fakeFetch({ [MARKET_LEGACY_PATH]: [200, legacyFile] });
  const load = createMarketLoader(fn);
  const [a, b] = await Promise.all([load("1d"), load("2d")]);
  assert.equal(a.kind, "legacy");
  assert.equal(b.kind, "legacy");
  assert.equal(calls.filter((c) => c === MARKET_LEGACY_PATH).length, 1);
});

test("載入器:500、斷線、格式錯都 reject(畫面顯示錯誤＋重試),不退回舊檔", async () => {
  for (const route of [[500, null], [-1, null], [200, { nope: 1 }]] as [number, unknown][]) {
    const { fn, calls } = fakeFetch({ [marketTfPath("1d")]: route, [MARKET_LEGACY_PATH]: [200, legacyFile] });
    await assert.rejects(createMarketLoader(fn)("1d"));
    assert.deepEqual(calls, [marketTfPath("1d")]);
  }
});

test("載入器:兩個檔都 404 → reject;舊檔失敗後可以重試", async () => {
  let legacyStatus = 404;
  const { fn, calls } = fakeFetch({ [MARKET_LEGACY_PATH]: () => [legacyStatus, legacyFile] });
  const load = createMarketLoader(fn);
  await assert.rejects(load("1d"));
  legacyStatus = 200;
  const r = await load("1d");
  assert.equal(r.kind, "legacy");
  assert.equal(calls.filter((c) => c === MARKET_LEGACY_PATH).length, 2);
});

test("狀態合併:區間檔只填自己;舊檔填滿五個區間但不蓋掉已 ready 的", () => {
  let s = applyMarketResult({ "2d": { status: "loading" } }, { kind: "tf", tf: "1d", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(s["1d"], { status: "ready", data_date: "2026-10-22", rows: [ROW] });
  assert.deepEqual(s["2d"], { status: "loading" });
  const legacy = parseLegacyMarket(legacyFile)!;
  s = applyMarketResult({ "1d": { status: "ready", data_date: "2026-10-23", rows: [] }, "2d": { status: "error" } }, { kind: "legacy", ...legacy });
  assert.deepEqual(s["1d"], { status: "ready", data_date: "2026-10-23", rows: [] });
  assert.deepEqual(s["2d"], { status: "ready", data_date: "2026-10-22", rows: [] });
  assert.equal(s["120d"]?.status, "ready");
});

test("明細檔:版本、股號、資料日都要對上畫面上的區間檔", () => {
  const file = { version: 1, data_date: "2026-10-22", stock_id: "2330", timeframes: { "1d": { "凱基-台北": BRK } } };
  assert.deepEqual(parseStockBreakdowns(file, "2330", "2026-10-22"), file.timeframes);
  assert.equal(parseStockBreakdowns(file, "2330", "2026-10-23"), null);
  assert.equal(parseStockBreakdowns(file, "2317", "2026-10-22"), null);
  assert.equal(parseStockBreakdowns({ ...file, version: 2 }, "2330", "2026-10-22"), null);
  assert.equal(parseStockBreakdowns({ ...file, data_date: null }, "2330", null)?.["1d"]?.["凱基-台北"], BRK);
});

test("列的明細:內嵌優先;否則依該股快取 → 未抓/載入中/失敗/找到/找不到([])", () => {
  assert.equal(rowBreakdown({ ...ROW, breakdown: BRK }, "1d", "error"), BRK);
  assert.equal(rowBreakdown(ROW, "1d", undefined), undefined);
  assert.equal(rowBreakdown(ROW, "1d", "loading"), "loading");
  assert.equal(rowBreakdown(ROW, "1d", "error"), "error");
  assert.equal(rowBreakdown(ROW, "1d", { "1d": { "凱基-台北": BRK } }), BRK);
  assert.deepEqual(rowBreakdown(ROW, "2d", { "1d": { "凱基-台北": BRK } }), []);
});
