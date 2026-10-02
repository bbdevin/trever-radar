// 執行: node --test web/lib/warrantBranches.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  branchSeries,
  defaultBranch,
  fmtWanSigned,
  kindNet,
  rankBranches,
  toWanSeries,
  fmtWanValueSigned,
} from "./warrantBranches.ts";

const rows = [
  { branch_name: "兆豐-嘉義", net_amount: 10_430_000,
    breakdown: [{ kind: "call", net_amount: 10_430_000 }] },
  { branch_name: "群益金鼎", net_amount: -23_850_000,
    breakdown: [{ kind: "call", net_amount: -23_850_000 }] },
  // 大買認售 = 看空。總額是「買超」,但它不可以出現在認購的買超排行裡。
  { branch_name: "看空券商", net_amount: 30_000_000,
    breakdown: [{ kind: "put", net_amount: 30_000_000 }] },
  { branch_name: "兩邊都做", net_amount: 2_000_000,
    breakdown: [{ kind: "call", net_amount: 5_000_000 }, { kind: "put", net_amount: -3_000_000 }] },
];

test("依種類加總淨額", () => {
  assert.equal(kindNet(rows[3], "call"), 5_000_000);
  assert.equal(kindNet(rows[3], "put"), -3_000_000);
  assert.equal(kindNet({ branch_name: "x", net_amount: 1 }, "call"), 0);
});

test("認購買超排行不含大買認售的券商(那是看空)", () => {
  const buys = rankBranches(rows, "call", "buy");
  assert.deepEqual(buys.map((r) => r.branch_name), ["兆豐-嘉義", "兩邊都做"]);
  assert.ok(!buys.some((r) => r.branch_name === "看空券商"));
  assert.deepEqual(rankBranches(rows, "put", "buy").map((r) => r.branch_name), ["看空券商"]);
});

test("賣超由最負排起,0 元兩邊都不進", () => {
  const sells = rankBranches(rows, "call", "sell");
  assert.deepEqual(sells.map((r) => r.branch_name), ["群益金鼎"]);
  assert.equal(sells[0].amount, -23_850_000);
  assert.ok(!rankBranches(rows, "put", "sell").some((r) => r.branch_name === "兆豐-嘉義"));
});

test("前 N 名", () => {
  const many = Array.from({ length: 15 }, (_, i) => ({
    branch_name: `b${i}`, net_amount: (i + 1) * 1_000_000,
    breakdown: [{ kind: "call", net_amount: (i + 1) * 1_000_000 }],
  }));
  const top = rankBranches(many, "call", "buy");
  assert.equal(top.length, 10);
  assert.equal(top[0].branch_name, "b14");
});

test("逐日序列依種類取值,缺的日子不補 0", () => {
  const daily = { "兆豐-嘉義": [["2026-09-01", 1_000_000, -200_000], ["2026-09-03", 2_000_000, 0]] as [string, number, number][] };
  assert.deepEqual(branchSeries(daily, "兆豐-嘉義", "call"),
    [{ t: "2026-09-01", net: 1_000_000 }, { t: "2026-09-03", net: 2_000_000 }]);
  assert.deepEqual(branchSeries(daily, "兆豐-嘉義", "put"),
    [{ t: "2026-09-01", net: -200_000 }, { t: "2026-09-03", net: 0 }]);
});

test("沒有逐日資料(舊 payload 或該券商不在畫圖名單)→ undefined,不是空陣列", () => {
  assert.equal(branchSeries(undefined, "x", "call"), undefined);
  assert.equal(branchSeries({}, "x", "call"), undefined);
  assert.equal(branchSeries({ x: [] }, "x", "call"), undefined);
  assert.equal(branchSeries({ x: [["2026-09-01", 1, 0]] }, null, "call"), undefined);
});

test("金額以萬為單位、帶正負號", () => {
  assert.equal(fmtWanSigned(10_430_000), "+1,043萬");
  assert.equal(fmtWanSigned(-23_850_000), "-2,385萬");
  assert.equal(fmtWanSigned(0), "0萬");
});

test("副圖序列以萬為單位(座標軸才會是 800 而不是 8M)", () => {
  assert.deepEqual(toWanSeries([{ t: "2026-09-30", net: 8_000_000 }, { t: "2026-10-01", net: -123_456 }]),
    [{ t: "2026-09-30", net: 800 }, { t: "2026-10-01", net: -12.3 }]);
  assert.equal(toWanSeries(undefined), undefined);
  assert.equal(fmtWanValueSigned(800), "+800萬");
  assert.equal(fmtWanValueSigned(-1234.4), "-1,234萬");
});

test("預設選買超第一名,沒有就賣超第一名", () => {
  assert.equal(defaultBranch([{ branch_name: "a", amount: 1 }], [{ branch_name: "b", amount: -1 }]), "a");
  assert.equal(defaultBranch([], [{ branch_name: "b", amount: -1 }]), "b");
  assert.equal(defaultBranch([], []), null);
});
