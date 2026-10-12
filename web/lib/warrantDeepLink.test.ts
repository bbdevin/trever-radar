// 執行: node --test web/lib/warrantDeepLink.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { branchFromParams, timeframeContaining, warrantTabHref } from "./warrantDeepLink.ts";

test("網址:id、tab=warrant、branch 編碼", () => {
  assert.equal(warrantTabHref("2330"), "/stock?id=2330&tab=warrant");
  assert.equal(warrantTabHref("2330", "群益金鼎-板橋"), "/stock?id=2330&tab=warrant&branch=%E7%BE%A4%E7%9B%8A%E9%87%91%E9%BC%8E-%E6%9D%BF%E6%A9%8B");
  assert.equal(warrantTabHref("2330", null), "/stock?id=2330&tab=warrant");
  // 來回:URLSearchParams 解得回原名(含括號與空白的券商名)。
  const name = "(牛牛牛)亞-鑫豐 A";
  const url = new URL(warrantTabHref("6488", name), "https://x.test");
  assert.equal(url.searchParams.get("tab"), "warrant");
  assert.equal(branchFromParams(url.searchParams), name);
});

test("branch 參數:缺、空白 → null", () => {
  assert.equal(branchFromParams(new URLSearchParams("id=2330")), null);
  assert.equal(branchFromParams(new URLSearchParams("branch=%20%20")), null);
  assert.equal(branchFromParams(null), null);
  assert.equal(branchFromParams(new URLSearchParams("branch=凱基")), "凱基");
});

test("找含有這家券商的區間", () => {
  const order = ["5d", "30d", "120d", "2d", "1d"] as const;
  const byTf = {
    "1d": [], "2d": [], "5d": [{ branch_name: "凱基" }], "30d": [{ branch_name: "凱基" }, { branch_name: "統一-嘉義" }],
    "120d": [{ branch_name: "統一-嘉義" }],
  };
  assert.equal(timeframeContaining(byTf, "凱基", "5d", order), "5d");          // 目前有 → 不換
  assert.equal(timeframeContaining(byTf, "統一-嘉義", "5d", order), "30d");    // 依序找到第一個
  assert.equal(timeframeContaining(byTf, "統一-嘉義", "120d", order), "120d"); // 目前就有
  assert.equal(timeframeContaining(byTf, "不存在", "5d", order), null);
  assert.equal(timeframeContaining(null, "凱基", "5d", order), null);
});
