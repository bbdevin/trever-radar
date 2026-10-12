// 執行: node --test web/lib/urlState.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { mergeSearch } from "./urlState.ts";
import { DEFAULT_SCREEN_FILTER, screenFilterFromParams, screenFilterToParams } from "./warrantPositions.ts";

test("mergeSearch:設定、移除、保留其他鍵、空結果", () => {
  assert.equal(mergeSearch("", { tab: "warrant" }), "?tab=warrant");
  assert.equal(mergeSearch("?tab=warrant", { view: "holders" }), "?tab=warrant&view=holders");
  assert.equal(mergeSearch("?tab=warrant&view=holders", { view: null }), "?tab=warrant");
  assert.equal(mergeSearch("?tab=warrant", { tab: null }), "");
  assert.equal(mergeSearch("?a=1&b=2", { a: "3", c: "" }), "?a=3&b=2");
  assert.equal(mergeSearch("tab=x", { tab: "y" }), "?tab=y");
  // 中文值會被編碼,解回來一樣
  const s = mergeSearch("", { branch: "群益金鼎-板橋" });
  assert.equal(new URLSearchParams(s).get("branch"), "群益金鼎-板橋");
});

test("篩選 ↔ 參數:預設不寫、非預設才寫、不認得的值回預設", () => {
  assert.deepEqual(screenFilterToParams(DEFAULT_SCREEN_FILTER), { wk: null, wpct: null, wsort: null });
  const f = { ...DEFAULT_SCREEN_FILTER, kind: "put" as const, maxPct: 0, sort: "cost" as const };
  assert.deepEqual(screenFilterToParams(f), { wk: "put", wpct: "0", wsort: "cost" });
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wk=put&wpct=0&wsort=cost")), f);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wk=bull&wpct=-15&wsort=zzz")), DEFAULT_SCREEN_FILTER);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("")), DEFAULT_SCREEN_FILTER);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wpct=-40")), { ...DEFAULT_SCREEN_FILTER, maxPct: -40 });
});
