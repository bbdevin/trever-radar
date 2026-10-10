// 執行: node --test --experimental-strip-types web/lib/branchFlow.test.ts
//
// 籌碼日報聚合(docs/44 §3.4):1日 用當日完整列、每側 15、同名加總、N 日 = 各日前 15 大合計、
// 舊 chips(每天 12 列、一邊倒)1日 仍看得到買超、v2 解碼後與 branches 同一批列。
import assert from "node:assert/strict";
import { test } from "node:test";

import { RANGE_NOTE, SIDE_MAX, aggregateBranchFlow } from "./branchFlow.ts";
import { decodeBranchDays } from "./stockParts.ts";
import type { BranchDaysV2, BranchRow } from "./types.ts";

const row = (name: string, net: number): BranchRow => ({ name, buy: Math.max(net, 0), sell: Math.max(-net, 0), net, pct: 0 });
const hrow = (n: string, net: number) => ({ n, b: Math.max(net, 0), s: Math.max(-net, 0), net });

/** 2464 型:10/08 來源 15 列全賣超;10/07 15 買 + 15 賣。舊 chips 每天只留 |淨額| 前 12 列。 */
function day(t: string, buys: number, sells: number) {
  const rows = [
    ...Array.from({ length: buys }, (_, i) => hrow(`買${i}`, 500 - i * 20)),
    ...Array.from({ length: sells }, (_, i) => hrow(`賣${i}`, -(480 - i * 20))),
  ];
  return { t, branches: rows };
}
const trim12 = (d: ReturnType<typeof day>) => ({ t: d.t, branches: [...d.branches].sort((a, b) => Math.abs(b.net) - Math.abs(a.net)).slice(0, 12) });

test("1日:當日 branches 非空就用它(舊 chips 一邊倒的 12 列不再讓買超空白),每側最多 15", () => {
  const todayRows = [...Array.from({ length: 15 }, (_, i) => row(`買${i}`, 300 - i * 5)), ...Array.from({ length: 15 }, (_, i) => row(`賣${i}`, -(290 - i * 5)))];
  const oldHistory = [trim12({ t: "2026-10-08", branches: Array.from({ length: 15 }, (_, i) => hrow(`賣${i}`, -(480 - i * 20))) }), trim12(day("2026-10-07", 15, 15))];
  assert.equal(oldHistory[0].branches.filter((b) => b.net > 0).length, 0, "舊 chips 當天沒有一列買超");
  const agg = aggregateBranchFlow(todayRows, oldHistory, 1);
  assert.equal(agg.source, "branches");
  assert.equal(agg.topBuy.length, 15);
  assert.equal(agg.topSell.length, 15);
  assert.equal(agg.topBuy[0].name, "買0");
  assert.deepEqual(agg.topBuy[0].history, [{ t: "2026-10-08", net: 300 }]);
  assert.equal(agg.topSell[0].name, "賣0");
  // 沒有當日 branches(分點日落後報價日)→ 退回日史第一天
  const lag = aggregateBranchFlow([], oldHistory, 1);
  assert.equal(lag.source, "history");
  assert.equal(lag.topBuy.length, 0);
  assert.equal(lag.topSell.length, 12);
});

test("N 日 = 各日前 15 大合計:同一分點跨日相加、某天不在名單算 0;每側最多 15", () => {
  const h = [day("2026-10-08", 15, 15), day("2026-10-07", 15, 15), { t: "2026-10-06", branches: [hrow("買0", 100), hrow("只在六", 50)] }];
  const agg = aggregateBranchFlow([], h, 3);
  assert.equal(agg.source, "history");
  assert.equal(agg.topBuy.length, SIDE_MAX);
  assert.equal(agg.buyers.length, 16);
  assert.equal(agg.topBuy[0].name, "買0");
  assert.equal(agg.topBuy[0].net, 500 + 500 + 100);
  assert.deepEqual(agg.topBuy[0].history.map((x) => x.t), ["2026-10-06", "2026-10-07", "2026-10-08"]);
  assert.deepEqual(agg.topBuy[0].history.map((x) => x.net), [100, 500, 500]);
  const only6 = agg.buyers.find((b) => b.name === "只在六")!;
  assert.equal(only6.net, 50);
  // 第 16 家買超在 buyers 但不在 topBuy
  assert.ok(!agg.topBuy.some((b) => b.name === "只在六"));
  assert.match(RANGE_NOTE, /各日前 15 大買賣超合計/);
  assert.match(RANGE_NOTE, /不是全市場完整合計/);
});

test("同名同日多列(多個 branch_key)加總成一列;1日 與 N 日都一樣", () => {
  const h = [{ t: "2026-10-08", branches: [hrow("凱基-台北", 40), hrow("凱基-台北", 25), hrow("賣A", -10)] }];
  const n = aggregateBranchFlow([], h, 1);
  assert.deepEqual(n.topBuy.map((b) => [b.name, b.net]), [["凱基-台北", 65]]);
  const one = aggregateBranchFlow([row("凱基-台北", 40), row("凱基-台北", 25), row("賣A", -10)], h, 1);
  assert.deepEqual(one.topBuy.map((b) => [b.name, b.buy, b.net]), [["凱基-台北", 65, 65]]);
  assert.equal(one.topBuy[0].history[0].net, 65);
});

test("v2 chips 解碼後第一天與當日 branches 是同一批列 → 兩條路聚合結果相同", () => {
  const v2: BranchDaysV2 = {
    version: 2, per_side: 15, names: ["A", "B", "C"],
    days: [["2026-10-08", [[0, 10, 0], [1, 0, 7], [2, 5, 2, 4]]], ["2026-10-07", [[1, 3, 0]]]],
  };
  const hist = decodeBranchDays(v2);
  assert.deepEqual(hist[0].branches, [hrow("A", 10), hrow("B", -7), { n: "C", b: 5, s: 2, net: 4 }]);
  const branches: BranchRow[] = [{ name: "A", buy: 10, sell: 0, net: 10, pct: 0 }, { name: "B", buy: 0, sell: 7, net: -7, pct: 0 }, { name: "C", buy: 5, sell: 2, net: 4, pct: 0 }];
  const a = aggregateBranchFlow(branches, hist, 1);
  const b = aggregateBranchFlow([], hist, 1);
  assert.deepEqual(a.topBuy.map(({ name, buy, sell, net, history }) => ({ name, buy, sell, net, history })), b.topBuy);
  assert.deepEqual(a.topSell, b.topSell);
  assert.equal(aggregateBranchFlow([], hist, 2).topBuy.find((x) => x.name === "B")?.net, undefined);
  assert.equal(aggregateBranchFlow([], hist, 2).topSell.find((x) => x.name === "B")?.net, -4);
});

test("沒有任何資料:空名單,不丟例外;自訂天數 0 或負數當 1 天", () => {
  const empty = aggregateBranchFlow([], undefined, 5);
  assert.deepEqual([empty.buyers, empty.sellers, empty.topBuy, empty.topSell], [[], [], [], []]);
  const h = [day("2026-10-08", 2, 2), day("2026-10-07", 2, 2)];
  assert.equal(aggregateBranchFlow([], h, 0).topBuy[0].net, 500);
  assert.equal(aggregateBranchFlow([], h, -3).topBuy[0].net, 500);
});
