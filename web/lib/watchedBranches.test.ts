// 執行測試: node --test web/lib/watchedBranches.test.ts
// 自選「特定分點」(docs/52):組合篩選、排序、持有估算顯示、禁用詞。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addBranch,
  amountEst,
  buildRows,
  cellLine,
  DEFAULT_BRANCH_SET,
  emptyText,
  filterRows,
  HONESTY_NOTE,
  isBigHold,
  MAX_BRANCHES,
  modeDefinition,
  modeLabel,
  normalizeSet,
  PUSH_NOTE,
  removeBranch,
  searchBranches,
  setAnchor,
  shardsFor,
  SIDE_LABEL,
  sideLots,
  SORT_OPTIONS,
  sortRows,
  todayCount,
  type BranchSet,
  type ComboMode,
  type WatchIndex,
  type WatchShard,
} from "./watchedBranches.ts";

const A = "富邦-新店";
const B = "永豐金-內湖";
const C = "元大-松江";
const SET: BranchSet = { branches: [A, B, C], anchor: A };

function shard(i: number, branches: WatchShard["branches"], stocks: WatchShard["stocks"]): WatchShard {
  return { version: 1, as_of: "2026-10-16", window_days: 60, window_from: "2026-07-22", shard: i, branches, stocks };
}

// 1111:三家同買;2222:主＋B 買;3333:只有主買;4444:B 買、主沒出現;5555:主賣、C 賣;6666:主今天沒出現但持有 3,000
const SHARDS: WatchShard[] = [
  shard(1, {
    [A]: [
      ["1111", 100, 0, 100, 500, "2026-09-01", 5, 500, "2026-10-16"],
      ["2222", 300, 0, 300, 300, "2026-10-16", 1, 300, "2026-10-16"],
      ["3333", 2000, 0, 2000, 2000, "2026-10-16", 1, 2000, "2026-10-16"],
      ["5555", 0, 50, -50, 0, null, 3, -20, "2026-10-16"],
      ["6666", null, null, null, 3000, "2026-08-01", 4, 3000, "2026-10-10"],
    ],
    [C]: [
      ["1111", 10, 0, 10, 10, "2026-10-16", 1, 10, "2026-10-16"],
      ["5555", 0, 80, -80, 0, null, 1, -80, "2026-10-16"],
    ],
  }, {
    "1111": ["甲", 10, 1.5, 500], "2222": ["乙", 100, -2, 1000], "3333": ["丙", 5, 0, 10],
    "5555": ["戊", 50, null, 100], "6666": ["己", 20, 3, 5000],
  }),
  shard(7, {
    [B]: [
      ["1111", 5, 0, 5, 5, "2026-10-16", 1, 5, "2026-10-16"],
      ["2222", 40, 0, 40, 40, "2026-10-16", 1, 40, "2026-10-16"],
      ["4444", 900, 0, 900, 900, "2026-10-16", 1, 900, "2026-10-16"],
    ],
  }, { "1111": ["甲", 10, 1.5, 500], "2222": ["乙", 100, -2, 1000], "4444": ["丁", 30, 1, 2000] }),
];

const INDEX: WatchIndex = {
  version: 1, as_of: "2026-10-16", window_days: 60, window_from: "2026-07-22", shards: 64, hold_min: 100, hold_top: 60,
  branches: [[A, 1, 3, 1, 1], [B, 7, 3, 0, 0], [C, 1, 1, 1, 0], ["富邦-新竹", 9, 0, 0, 0], ["凱基-台北", 3, 5, 2, 0]],
};

const ROWS = buildRows(SET, SHARDS);
const ids = (rs: { stock_id: string }[]) => rs.map((r) => r.stock_id);

test("buildRows:一檔一列、依選的順序列買超／賣超分點,null 當日不算", () => {
  const r1 = ROWS.find((r) => r.stock_id === "1111")!;
  assert.deepEqual(r1.buyers, [A, B, C]);
  assert.equal(r1.name, "甲");
  assert.equal(r1.holdTotal, 515);
  const r6 = ROWS.find((r) => r.stock_id === "6666")!;
  assert.deepEqual(r6.buyers, []);
  assert.deepEqual(r6.sellers, []);
  assert.equal(r6.cells[A].net, null);
  assert.deepEqual(ROWS.find((r) => r.stock_id === "5555")!.sellers, [A, C]);
});

test("filterRows:主分點／主＋任一／全部／任一", () => {
  assert.deepEqual(ids(filterRows(ROWS, SET, "buy", "anchor")).sort(), ["1111", "2222", "3333"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "buy", "anchor_plus")).sort(), ["1111", "2222"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "buy", "all")), ["1111"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "buy", "any")).sort(), ["1111", "2222", "3333", "4444"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "sell", "anchor")), ["5555"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "sell", "anchor_plus")), ["5555"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "sell", "all")), []);
  // 換主分點:B 為主時,2222/4444/1111 符合
  const setB = setAnchor(SET, B);
  assert.deepEqual(ids(filterRows(ROWS, setB, "buy", "anchor")).sort(), ["1111", "2222", "4444"]);
});

test("filterRows hold:任一分點估計仍持有 ≥ 門檻(含今天沒出現的列)", () => {
  assert.deepEqual(ids(filterRows(ROWS, SET, "hold", "anchor", 100)).sort(), ["1111", "2222", "3333", "4444", "6666"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "hold", "anchor", 1000)).sort(), ["3333", "6666"]);
});

test("sortRows combo:同步家數多的在前,再依金額", () => {
  const buy = filterRows(ROWS, SET, "buy", "any");
  // 1111 三家;2222 兩家;3333 一家 金額 2000×5×1000=1,000 萬;4444 一家 900×30×1000=2,700 萬
  assert.deepEqual(ids(sortRows(buy, "buy", "combo")), ["1111", "2222", "4444", "3333"]);
  assert.deepEqual(ids(sortRows(buy, "buy", "lots")), ["3333", "4444", "2222", "1111"]);
  assert.deepEqual(ids(sortRows(buy, "buy", "amount")), ["2222", "4444", "3333", "1111"]);
  assert.deepEqual(ids(sortRows(buy, "buy", "hold")), ["3333", "4444", "1111", "2222"]);
  const hold = filterRows(ROWS, SET, "hold", "anchor");
  assert.equal(sortRows(hold, "hold", "hold")[0].stock_id, "6666");
});

test("sideLots / amountEst", () => {
  const r1 = ROWS.find((r) => r.stock_id === "1111")!;
  assert.equal(sideLots(r1, "buy"), 115);
  assert.equal(sideLots(r1, "sell"), 0);
  assert.equal(sideLots(ROWS.find((r) => r.stock_id === "5555")!, "sell"), 130);
  assert.equal(amountEst(115, 10), 1_150_000);
  assert.equal(amountEst(115, null), null);
});

test("isBigHold:≥1,000 張或 ≥ 20 日均量", () => {
  assert.equal(isBigHold(1000, null), true);
  assert.equal(isBigHold(999, null), false);
  assert.equal(isBigHold(600, 500), true);
  assert.equal(isBigHold(400, 500), false);
  assert.equal(isBigHold(0, 0), false);
  assert.equal(isBigHold(10, 0), false);
});

test("todayCount:今天有任何一家出現的檔數(估計仍持有那列不算)", () => {
  assert.equal(todayCount(ROWS), 5);
});

test("分點組合:預設、還原壞值、增刪與主分點", () => {
  assert.deepEqual(normalizeSet(null), DEFAULT_BRANCH_SET);
  assert.deepEqual(normalizeSet({ branches: [] }), DEFAULT_BRANCH_SET);
  assert.deepEqual(normalizeSet({ branches: [" 甲 ", "甲", 3, "乙"], anchor: "丙" }), { branches: ["甲", "乙"], anchor: "甲" });
  assert.equal(normalizeSet({ branches: Array.from({ length: 10 }, (_, i) => `b${i}`) }).branches.length, MAX_BRANCHES);
  assert.deepEqual(addBranch(SET, "凱基-台北").branches, [A, B, C, "凱基-台北"]);
  assert.equal(addBranch(SET, A), SET);
  const r = removeBranch(SET, A);
  assert.deepEqual(r, { branches: [B, C], anchor: B });
  assert.equal(removeBranch({ branches: [A], anchor: A }, A).branches.length, 1);
  assert.equal(setAnchor(SET, "不存在"), SET);
});

test("shardsFor / searchBranches", () => {
  assert.deepEqual(shardsFor(INDEX, [A, B, C, "沒這家"]), [1, 7]);
  assert.deepEqual(searchBranches(INDEX, "富邦", [A]).map((b) => b[0]), ["富邦-新竹"]);
  assert.deepEqual(searchBranches(INDEX, "-", []).map((b) => b[0]).slice(0, 2), ["凱基-台北", A]);
  assert.deepEqual(searchBranches(INDEX, "  ", []), []);
});

test("cellLine:未知不寫成 0", () => {
  const r6 = ROWS.find((r) => r.stock_id === "6666")!;
  assert.deepEqual(cellLine(r6.cells[A]), { today: "今天未進前 15 大", hold: "估計仍持有 3,000 張 · 進場 08/01" });
  assert.equal(cellLine(undefined).today, "近 60 日未見");
  assert.equal(cellLine(ROWS.find((r) => r.stock_id === "5555")!.cells[C]).today, "今天賣超 80 張");
});

test("禁用詞不出現在任何文案", () => {
  // 字面不寫出來:pipeline/tests/test_label_honesty.py 會掃 web/ 的字串字面(與 warrantPositions.test.ts 同一招)。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const banned = [
    word(0x52dd, 0x7387), word(0x7372, 0x5229), word(0x5831, 0x916c), word(0x95dc, 0x9375, 0x5206, 0x9ede),
    word(0x5927, 0x6f32), word(0x5674), word(0x6975, 0x54c1), word(0x6a5f, 0x7387), word(0x76ee, 0x6a19, 0x50f9),
    word(0x8cb7, 0x9032), word(0x8ce3, 0x51fa), word(0x770b, 0x591a), word(0x770b, 0x7a7a), word(0x5c07, 0x6703),
    word(0x6709, 0x6548, 0x652f, 0x6490), word(0x58d3, 0x529b, 0x6c89, 0x91cd), word(0x505a, 0x591a),
    word(0x505a, 0x7a7a), word(0x5efa, 0x8b70), word(0x558a, 0x55ae), word(0x5957, 0x7262),
  ];
  assert.equal(banned.length, 21);
  const modes: ComboMode[] = ["anchor", "anchor_plus", "all", "any"];
  const texts = [
    HONESTY_NOTE, PUSH_NOTE, ...Object.values(SIDE_LABEL), ...SORT_OPTIONS.map((s) => s.label),
    ...modes.flatMap((m) => (["buy", "sell"] as const).flatMap((s) => [modeLabel(m, s), modeDefinition(m, s, A, 3), emptyText(s, m, "2026-10-16")])),
    emptyText("hold", "anchor", "2026-10-16"), emptyText("buy", "anchor", null),
    ...ROWS.flatMap((r) => Object.values(r.cells).flatMap((c) => Object.values(cellLine(c)))),
  ];
  for (const t of texts) for (const w of banned) assert.ok(!t.includes(w), `「${t}」含禁用詞 ${w}`);
});
