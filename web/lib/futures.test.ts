// 無 React test runner(package.json 無 vitest/jest)時的既有替代作法:
// 把判斷抽成純函式,直接用 Node 內建 test runner 測(比照 scripts/verify-*.mjs
// 用純 node 執行、不進 npm scripts 的慣例)。
// 執行: node --test web/lib/futures.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { futuresState } from "./futures.ts";

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
