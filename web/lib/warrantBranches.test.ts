// 執行: node --test web/lib/warrantBranches.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  branchAmount,
  branchSeries,
  defaultBranch,
  hasSelfIssued,
  resolveBreakdown,
  selfIssuedTag,
  fmtWanSigned,
  kindNet,
  rankBranches,
  searchBranches,
  toWanSeries,
  fmtWanValueSigned,
  buildStripItems,
  stepIndex,
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

test("合計(預設):認購＋認售一起算,與匯出的總額一致", () => {
  assert.equal(kindNet(rows[3], "all"), 2_000_000);
  assert.deepEqual(rankBranches(rows, "all", "buy").map((r) => r.branch_name),
    ["看空券商", "兆豐-嘉義", "兩邊都做"]);
  const daily = { x: [["2026-09-01", 1_000_000, -200_000]] as [string, number, number][] };
  assert.deepEqual(branchSeries(daily, "x", "all"), [{ t: "2026-09-01", net: 800_000 }]);
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

test("搜尋券商:名稱或代號都找得到,不限排行前 10", () => {
  const codes = { "兆豐-嘉義": "7001", "群益金鼎": "9100", "看空券商": "9A9X" };
  assert.deepEqual(searchBranches(rows, "7001", "call", codes).map((r) => r.branch_name), ["兆豐-嘉義"]);
  assert.deepEqual(searchBranches(rows, "9a9x", "put", codes).map((r) => r.code), ["9A9X"]);
  assert.deepEqual(searchBranches(rows, "金鼎", "call", codes)[0],
    { branch_name: "群益金鼎", code: "9100", amount: -23_850_000 });
  assert.deepEqual(searchBranches(rows, "  ", "call", codes), []);
  // 沒有代號對照(舊分片)時只比名稱,不壞
  assert.equal(searchBranches(rows, "兆豐", "call").length, 1);
});

const selfRows = [
  // 發行商總公司:總額 -800 萬,其中自家權證 -900 萬(占 90%)。
  { branch_name: "凱基", net_amount: -8_000_000, self: { net: -9_000_000, pct: 90, hq: true } },
  { branch_name: "凱基-台北", net_amount: 3_000_000, self: { net: 2_500_000, pct: 80, hq: false } },
  { branch_name: "元大-南京", net_amount: 2_000_000, self: { net: 100_000, pct: 5, hq: false } },
  { branch_name: "兆豐-嘉義", net_amount: 1_500_000 },
];

test("排除同券商發行:扣掉自家權證淨額、再套同一門檻", () => {
  assert.equal(branchAmount(selfRows[0], "all", true), 1_000_000);
  assert.equal(branchAmount(selfRows[0], "all", false), -8_000_000);
  // 單一種類時摘要不分購售,不假裝扣得準。
  assert.equal(branchAmount({ ...selfRows[0], breakdown: [{ kind: "call", net_amount: -8_000_000 }] }, "call", true), -8_000_000);
  assert.deepEqual(rankBranches(selfRows, "all", "sell").map((r) => r.branch_name), ["凱基"]);
  const opts = { excludeSelf: true, minAbs: 1_000_000 };
  // 凱基扣完剩 +100 萬 → 改到買超邊;凱基-台北剩 50 萬 < 門檻 → 掉出。
  // 元大-南京 只有 5% 在自家權證、沒有標籤 → 不扣,保留全額 200 萬。
  assert.deepEqual(rankBranches(selfRows, "all", "buy", 10, opts).map((r) => [r.branch_name, r.amount]),
    [["元大-南京", 2_000_000], ["兆豐-嘉義", 1_500_000], ["凱基", 1_000_000]]);
  assert.deepEqual(rankBranches(selfRows, "all", "sell", 10, opts), []);
  assert.equal(searchBranches(selfRows, "凱基", "all", {}, 20, true)[0].amount, 1_000_000);
});

test("排除只扣有標籤的列:未過半(含 49%)保留全額,50% 起才扣", () => {
  const row = (pct: number, hq: boolean) => ({ branch_name: "x", net_amount: 3_000_000, self: { net: 2_000_000, pct, hq } });
  assert.equal(branchAmount(row(49, true), "all", true), 3_000_000);
  assert.equal(branchAmount(row(49, false), "all", true), 3_000_000);
  assert.equal(branchAmount(row(50, true), "all", true), 1_000_000);
  assert.equal(branchAmount(row(50, false), "all", true), 1_000_000);
  assert.equal(selfIssuedTag({ net: 1, pct: 49, hq: true }), null);
  assert.deepEqual(selfIssuedTag({ net: 1, pct: 50, hq: false }), { label: "同券商", pct: 50, hq: false });
});

test("同券商標籤:總公司標發行商、分公司標同券商、未過半不標", () => {
  assert.deepEqual(selfIssuedTag(selfRows[0].self), { label: "發行商", pct: 90, hq: true });
  assert.deepEqual(selfIssuedTag(selfRows[1].self), { label: "同券商", pct: 80, hq: false });
  assert.equal(selfIssuedTag(selfRows[2].self), null);
  assert.equal(selfIssuedTag(undefined), null);
  assert.equal(rankBranches(selfRows, "all", "sell")[0].self?.pct, 90);
  assert.equal(hasSelfIssued(selfRows), true);
  assert.equal(hasSelfIssued(rows), false);
});

test("明細:舊分片內嵌優先,新分片查拆檔,未載入回 null", () => {
  const inline = { branch_name: "a", breakdown: [{ kind: "call", net_amount: 1 }] };
  const bare = { branch_name: "a" };
  const split = { "5d": { a: [{ kind: "put", net_amount: 2 }] } };
  assert.deepEqual(resolveBreakdown(inline, null, "5d"), inline.breakdown);
  assert.equal(resolveBreakdown(bare, null, "5d"), null);
  assert.deepEqual(resolveBreakdown(bare, split, "5d"), split["5d"].a);
  assert.deepEqual(resolveBreakdown(bare, split, "1d"), []);
  assert.equal(resolveBreakdown(null, split, "5d"), null);
});

test("預設選買超第一名,沒有就賣超第一名", () => {
  assert.equal(defaultBranch([{ branch_name: "a", amount: 1 }], [{ branch_name: "b", amount: -1 }]), "a");
  assert.equal(defaultBranch([], [{ branch_name: "b", amount: -1 }]), "b");
  assert.equal(defaultBranch([], []), null);
});

test("手機券商列:買超在前、賣超在後,帶代號與標籤", () => {
  const buys = rankBranches(selfRows, "all", "buy", 10, { minAbs: 1_000_000 });
  const sells = rankBranches(selfRows, "all", "sell", 10, { minAbs: 1_000_000 });
  const items = buildStripItems(buys, sells, { "凱基": "9200" });
  assert.deepEqual(items.map((i) => [i.name, i.tone]), [
    ["凱基-台北", "up"], ["元大-南京", "up"], ["兆豐-嘉義", "up"], ["凱基", "down"],
  ]);
  assert.equal(items[3].code, "9200");
  assert.equal(items[3].tag, "發行商");
  assert.equal(items[0].tag, "同券商");
  assert.equal(items[1].tag, undefined);
  assert.equal(items[1].code, undefined);
  assert.equal(items[3].amount, -8_000_000);
});

test("手機券商列:排除同券商發行時跟著排行重排,且不標標籤", () => {
  const opts = { excludeSelf: true, minAbs: 1_000_000 };
  const buys = rankBranches(selfRows, "all", "buy", 10, opts);
  const sells = rankBranches(selfRows, "all", "sell", 10, opts);
  const items = buildStripItems(buys, sells, {}, false);
  // 凱基扣掉自家 -900 萬後變 +100 萬買超;凱基-台北扣完只剩 50 萬,掉出門檻。
  assert.deepEqual(items.map((i) => [i.name, i.tone, i.amount]), [
    ["元大-南京", "up", 2_000_000], ["兆豐-嘉義", "up", 1_500_000], ["凱基", "up", 1_000_000],
  ]);
  assert.ok(items.every((i) => i.tag === undefined));
});

test("券商列前後切換:不繞回,不在列上時 › 從第一格開始", () => {
  assert.equal(stepIndex(3, 0, 1), 1);
  assert.equal(stepIndex(3, 2, 1), null);
  assert.equal(stepIndex(3, 0, -1), null);
  assert.equal(stepIndex(3, 2, -1), 1);
  assert.equal(stepIndex(3, -1, 1), 0);
  assert.equal(stepIndex(3, -1, -1), null);
  assert.equal(stepIndex(0, -1, 1), null);
});