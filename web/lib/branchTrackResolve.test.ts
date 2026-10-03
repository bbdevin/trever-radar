// 執行: node --test web/lib/branchTrackResolve.test.ts
//
// 全站追蹤名單的管理員覆寫(見 branchTrackResolve.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  effectiveTracked,
  effectiveTrackedSet,
  nextAction,
  pocketBadgeVisible,
} from "./branchTrackResolve.ts";

const none = new Set<string>();

test("沒有任何覆寫 → 跟系統名單一樣", () => {
  assert.equal(effectiveTracked("凱基-新竹", true, none, none), true);
  assert.equal(effectiveTracked("永豐-板橋", false, none, none), false);
  assert.deepEqual([...effectiveTrackedSet(["凱基-新竹", "富邦-台北"], none, none)].sort(),
    ["凱基-新竹", "富邦-台北"].sort());
});

test("取消追蹤手動種子:寫 mute,之後不算追蹤", () => {
  assert.deepEqual(nextAction("凱基-新竹", true, none, none), { kind: "upsert", state: "mute" });
  const muted = new Set(["凱基-新竹"]);
  assert.equal(effectiveTracked("凱基-新竹", true, muted, none), false);
  assert.deepEqual([...effectiveTrackedSet(["凱基-新竹", "富邦-台北"], muted, none)], ["富邦-台北"]);
});

test("取消追蹤演算法自動入選的分點:同樣寫 mute(不分來源)", () => {
  assert.deepEqual(nextAction("元大-竹科", true, none, none), { kind: "upsert", state: "mute" });
  assert.equal(effectiveTracked("元大-竹科", true, new Set(["元大-竹科"]), none), false);
});

test("追蹤系統名單外的分點:寫 track;再按一次刪掉那一列", () => {
  assert.deepEqual(nextAction("永豐-板橋", false, none, none), { kind: "upsert", state: "track" });
  const added = new Set(["永豐-板橋"]);
  assert.equal(effectiveTracked("永豐-板橋", false, none, added), true);
  assert.ok(effectiveTrackedSet(["凱基-新竹"], none, added).has("永豐-板橋"));
  assert.deepEqual(nextAction("永豐-板橋", false, none, added), { kind: "delete" });
});

test("恢復追蹤(un-mute):刪掉 mute 那一列,回到系統預設", () => {
  const muted = new Set(["凱基-新竹"]);
  assert.deepEqual(nextAction("凱基-新竹", true, muted, none), { kind: "delete" });
  assert.equal(effectiveTracked("凱基-新竹", true, none, none), true);
});

test("多餘列:按下去一定翻轉,翻完和系統預設相同就刪", () => {
  // 系統後來自己收錄了,卻還留著 track → 現在算追蹤,按下去要變不追蹤 → 覆寫成 mute
  const added = new Set(["凱基-新竹"]);
  assert.equal(effectiveTracked("凱基-新竹", true, none, added), true);
  assert.deepEqual(nextAction("凱基-新竹", true, none, added), { kind: "upsert", state: "mute" });
  // 系統已移除,卻還留著 mute → 現在不算追蹤,按下去要追蹤 → 覆寫成 track
  const muted = new Set(["永豐-板橋"]);
  assert.equal(effectiveTracked("永豐-板橋", false, muted, none), false);
  assert.deepEqual(nextAction("永豐-板橋", false, muted, none), { kind: "upsert", state: "track" });
  // 任何狀態按兩下都回到原本的有效狀態
  for (const server of [true, false]) {
    for (const [m, a] of [[none, none], [new Set(["x"]), none], [none, new Set(["x"])]] as const) {
      const before = effectiveTracked("x", server, m, a);
      const act = nextAction("x", server, m, a);
      const m2 = new Set(m); const a2 = new Set(a);
      m2.delete("x"); a2.delete("x");
      if (act.kind === "upsert") (act.state === "mute" ? m2 : a2).add("x");
      assert.equal(effectiveTracked("x", server, m2, a2), !before);
    }
  }
});

test("口袋名單徽章:背後分點全被 mute 才藏,部分 mute 照常顯示", () => {
  assert.equal(pocketBadgeVisible(["凱基-新竹", "富邦-台北"], new Set(["凱基-新竹", "富邦-台北"])), false);
  assert.equal(pocketBadgeVisible(["凱基-新竹", "富邦-台北"], new Set(["凱基-新竹"])), true);
  assert.equal(pocketBadgeVisible(["凱基-新竹"], none), true);
  // 舊 payload 沒帶 branches:無從判斷 → 照常顯示
  assert.equal(pocketBadgeVisible(undefined, new Set(["凱基-新竹"])), true);
  assert.equal(pocketBadgeVisible([], new Set(["凱基-新竹"])), true);
});
