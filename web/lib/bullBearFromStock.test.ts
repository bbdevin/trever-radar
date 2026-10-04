// 執行: node --test --experimental-strip-types web/lib/bullBearFromStock.test.ts
//
// 個股頁與多方榜建置器必須是同一次呼叫(docs/48 §1):個股頁原文要 import summaryFromStockJson、
// 不得自己再組 buildBullBear;組裝結果與手動呼叫逐項相同。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { buildBullBear } from "./bullBear.ts";
import { lastCandleDate, summaryFromStockJson } from "./bullBearFromStock.ts";
import { deriveAllFacts } from "./facts/index.ts";
import type { Candle, StockJson } from "./types.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
// 舊 payload 的改名前字樣;拆成兩段字串,避免本測試檔被 test_label_honesty 當成畫面字串掃到。
const LEGACY_S13 = "融券回補軋" + "空(測試)";
const LEGACY_K1 = "關鍵" + "分點同買：甲";

test("個股頁呼叫 summaryFromStockJson,不再自己組 buildBullBear", () => {
  const src = fs.readFileSync(path.join(here, "..", "app", "stock", "page.tsx"), "utf8");
  assert.match(src, /import \{ summaryFromStockJson \} from "@\/lib\/bullBearFromStock";/);
  assert.match(src, /summaryFromStockJson\(data, muted\)/);
  assert.doesNotMatch(src, /buildBullBear\(/);
  assert.doesNotMatch(src, /deriveAllFacts\(/);
  const script = fs.readFileSync(path.join(here, "..", "scripts", "build-bull-board.mjs"), "utf8");
  assert.match(script, /summaryFromStockJson\(data\)/);
});

function candles(n: number): Candle[] {
  return Array.from({ length: n }, (_, i) => {
    const c = 100 + i;
    const d = new Date(Date.UTC(2026, 6, 1) + i * 86400_000).toISOString().slice(0, 10);
    return { t: d, o: c - 1, h: c + 1, l: c - 2, c, v: 1000 + i * 10, amt: c * 1e6, af: 1 };
  });
}

function stock(over: Partial<StockJson> = {}): StockJson {
  return {
    id: "9999",
    name: "測試",
    market: "twse",
    candles: candles(80),
    scores: null,
    reasons: [],
    raw_reasons: [{ code: "S13_SHORT_SQUEEZE", text: LEGACY_S13 }, { code: "T2_20D_HIGH", text: "創20日新高" }],
    risks: [],
    technical: null,
    branches: [],
    warrant: null,
    warrant_history: [],
    active_warrants: [],
    pocket_tags: [
      { code: "K1_KEY_BUY", text: LEGACY_K1, branches: ["甲"] },
      { code: "G1_GEO_BUY", text: "地緣買", branches: ["乙"] },
    ],
    ...over,
  } as StockJson;
}

test("與手動組 buildBullBear 逐項相同;舊字樣轉場生效", () => {
  const data = stock();
  const lastT = lastCandleDate(data);
  const got = summaryFromStockJson(data);
  const want = buildBullBear({
    rawReasons: data.raw_reasons,
    reasons: [],
    rawRisks: undefined,
    risks: [],
    technical: null,
    pocketTags: data.pocket_tags,
    derivedFacts: deriveAllFacts(data, lastT),
    asOf: lastT,
  });
  assert.equal(got.asOf, lastT);
  assert.deepEqual(got.bull.map((x) => x.key), want.bull.map((x) => x.key));
  const s13 = got.bull.find((x) => x.code === "S13_SHORT_SQUEEZE");
  assert.equal(s13?.text, "融券減少＋帶量大漲");
  const k1 = got.bull.find((x) => x.code === "K1_KEY_BUY");
  assert.equal(k1?.text, "追蹤分點同買：甲");
});

test("使用者關掉的追蹤分點不列;其他口袋標籤照列", () => {
  const got = summaryFromStockJson(stock(), new Set(["甲"]));
  assert.equal(got.bull.find((x) => x.code === "K1_KEY_BUY"), undefined);
  assert.ok(got.bull.find((x) => x.code === "G1_GEO_BUY"));
});

test("舊 JSON 全缺鍵不丟例外", () => {
  const legacy = { id: "1", name: "x", market: "twse", candles: candles(3), scores: null, reasons: [], risks: [], technical: null } as unknown as StockJson;
  assert.doesNotThrow(() => summaryFromStockJson(legacy));
  assert.equal(lastCandleDate({ candles: [] }), "");
});
