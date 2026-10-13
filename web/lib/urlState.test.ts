// 執行: node --test web/lib/urlState.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { mergeSearch } from "./urlState.ts";
import { DEFAULT_SCREEN_FILTER, screenFilterFromParams, screenFilterToParams, withScreenDir } from "./warrantPositions.ts";

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
  assert.deepEqual(screenFilterToParams(DEFAULT_SCREEN_FILTER), { wk: null, wdir: null, wpct: null, wsort: null });
  const f = { ...DEFAULT_SCREEN_FILTER, kind: "put" as const, pct: 0, sort: "cost" as const };
  assert.deepEqual(screenFilterToParams(f), { wk: "put", wdir: null, wpct: "0", wsort: "cost" });
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wk=put&wpct=0&wsort=cost")), f);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wk=bull&wdir=sideways&wpct=-15&wsort=zzz")), DEFAULT_SCREEN_FILTER);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("")), DEFAULT_SCREEN_FILTER);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wpct=-40")), { ...DEFAULT_SCREEN_FILTER, pct: -40 });
});

test("篩選 ↔ 參數:帳面為正(wdir=up)與該方向的門檻", () => {
  const up = withScreenDir(DEFAULT_SCREEN_FILTER, "up");
  assert.deepEqual(up, { ...DEFAULT_SCREEN_FILTER, dir: "up", pct: 20 });
  // 預設門檻(+20)不寫;只寫 wdir。
  assert.deepEqual(screenFilterToParams(up), { wk: null, wdir: "up", wpct: null, wsort: null });
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wdir=up")), up);
  const up40 = { ...up, pct: 40, kind: "put" as const, sort: "recent" as const };
  assert.deepEqual(screenFilterToParams(up40), { wk: "put", wdir: "up", wpct: "40", wsort: "recent" });
  // 來回一趟不變(返回鍵還原)。
  const back = new URLSearchParams(mergeSearch("?tab=warrant&view=holders", screenFilterToParams(up40)));
  assert.deepEqual(screenFilterFromParams(back), up40);
  // 門檻與方向不合(為正卻給 −20)→ 回該方向的預設,不會變成「為正且 ≤ −20」。
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wdir=up&wpct=-20")), up);
  assert.deepEqual(screenFilterFromParams(new URLSearchParams("wpct=20")), DEFAULT_SCREEN_FILTER);
  // 為正的 0 = 不限,要寫出來(與預設 +20 不同)。
  assert.deepEqual(screenFilterToParams({ ...up, pct: 0 }).wpct, "0");
  // 換回為負:門檻回 −20,種類與排序保留;同方向不變。
  assert.deepEqual(withScreenDir(up40, "down"), { ...up40, dir: "down", pct: -20 });
  assert.equal(withScreenDir(up40, "up"), up40);
});
