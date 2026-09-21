// 無 React test runner(package.json 無 vitest/jest)時的既有替代作法:
// 把判斷抽成純函式,直接用 Node 內建 test runner 測(比照 scripts/verify-*.mjs
// 用純 node 執行、不進 npm scripts 的慣例)。
// 執行: node --test web/lib/futures.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  anomalyFacts,
  flaggedContracts,
  futuresAnomalyMarketState,
  futuresState,
} from "./futures.ts";

test("futures 鍵不存在 -> unknown(尚未 import,不可讀成沒有)", () => {
  assert.deepEqual(futuresState(undefined), { kind: "unknown" });
  assert.deepEqual(futuresState(null), { kind: "unknown" });
});

test("contracts 是空陣列 -> none,帶 list_as_of 日期(正面主張,不是缺資料)", () => {
  const state = futuresState({ version: 1, list_as_of: "2026-09-11", contracts: [] });
  assert.deepEqual(state, { kind: "none", asOf: "2026-09-11" });
});

test("contracts 非空 -> has,原樣帶出契約清單", () => {
  const contracts = [
    { code: "CDF", is_futures: true, is_option: false, is_weekly_option: false },
    { code: "CDO", is_futures: false, is_option: true, is_weekly_option: false },
  ];
  const state = futuresState({ version: 1, list_as_of: "2026-09-11", contracts });
  assert.deepEqual(state, { kind: "has", asOf: "2026-09-11", contracts });
});

test("unknown 與 none 不可塌成同一種表示(這個功能唯一要守住的事)", () => {
  const unknown = futuresState(undefined);
  const none = futuresState({ version: 1, list_as_of: "2026-09-11", contracts: [] });
  assert.notDeepEqual(unknown, none);
});

// ---- docs/38 §7:成交量異常的呈現 ----

const ANOMALY_MYF = { today: 320, window_max: 140, window_median: 45, window_days: 60, oi_change: 210 };
const ANOMALY_OMF = { today: 1200, window_max: 900, window_median: 300, window_days: 60 }; // 無 oi_change
const REASONS = [{ code: "F1_FUTURES_VOLUME_60D_HIGH", text: "創 60 個比較日新高" }];
const RISKS = [{ code: "R_FUTURES_VOLUME_NO_DIRECTION", text: "量創高不代表方向" }];

const entry = (stock_id: string, code: string, anomaly: typeof ANOMALY_MYF | typeof ANOMALY_OMF) => ({
  stock_id,
  code,
  anomaly,
  reasons: REASONS,
  risks: RISKS,
});

test("§7.5 市場層級鍵的三態:缺鍵 / 空陣列 / 非空,三者互不相同", () => {
  const notComputed = futuresAnomalyMarketState(undefined, "2026-09-18");
  const computedEmpty = futuresAnomalyMarketState([], "2026-09-18");
  const listed = futuresAnomalyMarketState([entry("1565", "MYF", ANOMALY_MYF)], "2026-09-18");

  assert.deepEqual(notComputed, { kind: "not-computed" });
  assert.deepEqual(computedEmpty, { kind: "computed-empty", dataDate: "2026-09-18" });
  assert.equal(listed.kind, "listed");
  assert.notDeepEqual(notComputed, computedEmpty);
});

test("§7.5 缺鍵不得帶日期:沒有算過就沒有任何主張可以繫在哪一天上", () => {
  const notComputed = futuresAnomalyMarketState(null, "2026-09-18");
  assert.deepEqual(Object.keys(notComputed), ["kind"]);
});

test("§7.1/§7.4 oi_change 有值時是一列,缺鍵時整列不顯示(不是 0、不是破折號)", () => {
  const withOi = anomalyFacts(ANOMALY_MYF);
  const withoutOi = anomalyFacts(ANOMALY_OMF);

  assert.deepEqual(withOi.map((f) => f.key), ["today", "window_max", "window_median", "oi_change"]);
  assert.deepEqual(withoutOi.map((f) => f.key), ["today", "window_max", "window_median"]);
  assert.equal(withOi.find((f) => f.key === "oi_change")?.value, "+210");
  // 缺鍵那一列不存在,而且沒有人用 "0"/"—"/"未公布" 之類的字把它頂起來。
  for (const f of withoutOi) {
    assert.ok(!["0", "—", "-", "未公布"].includes(f.value), `不得用 ${f.value} 頂替缺值`);
  }
});

test("§7.1 oi_change = 0 是一個真的觀測,要顯示 0(與缺鍵不同)", () => {
  const facts = anomalyFacts({ ...ANOMALY_MYF, oi_change: 0 });
  assert.equal(facts.find((f) => f.key === "oi_change")?.value, "0");
});

test("§7.10 window_days 從區塊讀,不寫死 60", () => {
  const facts = anomalyFacts({ today: 9, window_max: 8, window_median: 2, window_days: 20 });
  const labels = facts.map((f) => f.label).join(" ");
  assert.ok(labels.includes("前 20 個比較日"), labels);
  assert.ok(!labels.includes("60"), labels);
});

test("§5 不算比率、不給名次:每個顯示值都是區塊裡原本那個整數", () => {
  const facts = anomalyFacts(ANOMALY_MYF);
  const allowed = new Set([320, 140, 45, 210]);
  for (const f of facts) {
    const n = Number(f.value.replace(/[,+]/g, ""));
    assert.ok(allowed.has(n), `${f.key} 的值 ${f.value} 不是 payload 裡的整數`);
  }
  // 3.2x / 711% / 第 1 名 這類東西不可能從這裡長出來。
  assert.equal(facts.length, 4);
});

test("§5 名單列不得帶 rank / position / score / ratio 之類的鍵", () => {
  const state = futuresAnomalyMarketState(
    [entry("1565", "MYF", ANOMALY_MYF), entry("2330", "CDF", ANOMALY_OMF)],
    "2026-09-18",
  );
  assert.equal(state.kind, "listed");
  if (state.kind !== "listed") return;
  for (const row of state.rows) {
    assert.deepEqual(Object.keys(row).sort(), ["code", "facts", "name", "reasons", "risks", "stockId"]);
  }
});

test("§7.5 順序原封不動照 payload,前端不重排", () => {
  const a = entry("2330", "CDF", ANOMALY_OMF); // today − window_max = 300
  const b = entry("1565", "MYF", ANOMALY_MYF); // today − window_max = 180
  const state = futuresAnomalyMarketState([a, b], "2026-09-18");
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.deepEqual(state.rows.map((r) => r.code), ["CDF", "MYF"]);
  // 反過來餵也照樣原封不動——證明這裡真的沒有排序。
  const flipped = futuresAnomalyMarketState([b, a], "2026-09-18");
  if (flipped.kind !== "listed") throw new Error("expected listed");
  assert.deepEqual(flipped.rows.map((r) => r.code), ["MYF", "CDF"]);
});

test("§0/§7.10 同一檔股票的兩個契約都要活到名單上,不得依股票去重", () => {
  const state = futuresAnomalyMarketState(
    [entry("1565", "MYF", ANOMALY_MYF), entry("1565", "OMF", ANOMALY_OMF)],
    "2026-09-18",
    new Map([["1565", "精剛"]]),
  );
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.equal(state.rows.length, 2);
  assert.deepEqual(state.rows.map((r) => r.code), ["MYF", "OMF"]);
  assert.deepEqual(state.rows.map((r) => r.stockId), ["1565", "1565"]);
  assert.deepEqual(state.rows.map((r) => r.name), ["精剛", "精剛"]);
});

test("股名解析不到時是 null(顯示 id 本身,不編一個標籤)", () => {
  const state = futuresAnomalyMarketState([entry("9999", "ZZF", ANOMALY_MYF)], "2026-09-18", new Map());
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.equal(state.rows[0].name, null);
});

test("個股頁:只有帶 anomaly 的契約進清單,兩個契約都舉旗時兩個都在", () => {
  const contracts = [
    { code: "MYF", is_futures: true, is_option: false, is_weekly_option: false, anomaly: ANOMALY_MYF },
    { code: "OMF", is_futures: true, is_option: false, is_weekly_option: false, anomaly: ANOMALY_OMF },
    { code: "MYO", is_futures: false, is_option: true, is_weekly_option: false },
  ];
  assert.deepEqual(flaggedContracts(contracts).map((c) => c.code), ["MYF", "OMF"]);
  // 沒有 anomaly 的那個被排除,但**沒有**被標成「正常」——它根本不進這個清單(§7.7)。
  assert.equal(flaggedContracts([contracts[2]]).length, 0);
});
