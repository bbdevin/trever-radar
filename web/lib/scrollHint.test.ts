// 執行: node --test --experimental-strip-types web/lib/scrollHint.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { scrollEdges, scrollTargetForItem } from "./scrollHint.ts";

test("沒有溢出(桌機常見):兩側都不提示", () => {
  assert.deepEqual(scrollEdges(0, 600, 600), { left: false, right: false });
  assert.deepEqual(scrollEdges(0, 600, 601.5), { left: false, right: false });
});

test("在最左:只提示右側;捲到底:只提示左側;中間:兩側", () => {
  assert.deepEqual(scrollEdges(0, 360, 700), { left: false, right: true });
  assert.deepEqual(scrollEdges(340, 360, 700), { left: true, right: false });
  assert.deepEqual(scrollEdges(339, 360, 700), { left: true, right: false });
  assert.deepEqual(scrollEdges(120, 360, 700), { left: true, right: true });
});

test("選中項已在可視範圍(扣掉提示寬):不捲", () => {
  assert.equal(scrollTargetForItem(100, 60, 0, 360, 700, 44), null);
});

test("選中項在右側被遮:捲到它右緣加提示寬", () => {
  // item 320..400, 可視 0..360 → 需 400+44-360 = 84
  assert.equal(scrollTargetForItem(320, 80, 0, 360, 700, 44), 84);
});

test("選中項在左側被遮:捲到它左緣減提示寬,不小於 0", () => {
  assert.equal(scrollTargetForItem(200, 60, 300, 360, 700, 44), 156);
  assert.equal(scrollTargetForItem(10, 60, 300, 360, 700, 44), 0);
});

test("最後一項:不超過最大捲動量", () => {
  assert.equal(scrollTargetForItem(640, 60, 0, 360, 700, 44), 340);
});
