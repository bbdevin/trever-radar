// 執行測試: node --test web/lib/watchedBranches.test.ts
// 自選「特定分點」(docs/52):組合篩選、排序、持有估算顯示、禁用詞。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  addBranch,
  amountEst,
  avgLine,
  buildRows,
  cellLine,
  combinedAvg,
  coverageText,
  fmtWan,
  gapPct,
  participants,
  sideWarrantAmount,
  WARRANT_NOTE,
  WARRANT_OFF,
  WARRANT_RULE,
  warrantChips,
  warrantCoverageLine,
  warrantHeldLines,
  warrantOnlyCount,
  warrantStaleText,
  DEFAULT_BRANCH_SET,
  emptyText,
  filterRows,
  holdCapText,
  holdQualifies,
  HONESTY_NOTE,
  isBigHold,
  looseName,
  MAX_BRANCHES,
  modeDefinition,
  modeLabel,
  normalizeSet,
  PUSH_NOTE,
  NO_DATA_TODAY,
  NOT_TOP15_TODAY,
  PENDING_TODAY,
  removeBranch,
  SEARCH_EMPTY,
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
      // 7777:小型股,這檔今天整檔還沒匯入;持有 80 張 ≥ 20 日均量 30 張
      ["7777", null, null, null, 80, "2026-09-20", 2, 80, "2026-10-15"],
      // 8888:今天沒列但不會再補(確認空或 ETF):無分點資料;持有 60 < 100 且 < 均量 → 不進持有檢視
      ["8888", null, null, null, 60, "2026-09-25", 1, 60, "2026-09-25"],
    ],
    [C]: [
      ["1111", 10, 0, 10, 10, "2026-10-16", 1, 10, "2026-10-16"],
      ["5555", 0, 80, -80, 0, null, 1, -80, "2026-10-16"],
    ],
  }, {
    "1111": ["甲", 10, 1.5, 500], "2222": ["乙", 100, -2, 1000], "3333": ["丙", 5, 0, 10],
    "5555": ["戊", 50, null, 100], "6666": ["己", 20, 3, 5000, 1], "7777": ["庚", 12, 1, 30, 0], "8888": ["辛", 40, 0, 80, 2],
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
  coverage: { covered: 1500, expected: 1956, complete: false },
  branches: [[A, 1, 3, 1, 60, 85], [B, 7, 3, 0, 0, 0], [C, 1, 1, 1, 0], ["富邦-新竹", 9, 0, 0, 0], ["凱基-台北", 3, 5, 2, 0], ["華南永昌-臺中", 4, 0, 0, 0]],
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
  assert.deepEqual(ids(filterRows(ROWS, SET, "hold", "anchor", 100)).sort(), ["1111", "2222", "3333", "4444", "6666", "7777"]);
  assert.deepEqual(ids(filterRows(ROWS, SET, "hold", "anchor", 1000)).sort(), ["1111", "3333", "6666", "7777"]);
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
  // ≥ 均量那條有 20 張地板
  assert.equal(isBigHold(15, 10), false);
  assert.equal(isBigHold(25, 10), true);
  assert.equal(holdQualifies(80, 30), true);
  assert.equal(holdQualifies(50, 60), false);
  assert.equal(holdQualifies(100, 5000), true);
});

test("今天狀態:未進前 15 大／尚未匯入／無分點資料", () => {
  const r7 = ROWS.find((r) => r.stock_id === "7777")!;
  assert.equal(r7.today, "pending");
  assert.equal(ROWS.find((r) => r.stock_id === "6666")!.today, "rows");
  assert.equal(ROWS.find((r) => r.stock_id === "5555")!.today, "rows"); // 舊檔沒有第 5 欄 → 視為有列
  const r8 = ROWS.find((r) => r.stock_id === "8888")!;
  assert.equal(r8.today, "nodata");
  assert.equal(cellLine(r7.cells[A], r7.today).today, PENDING_TODAY);
  assert.equal(cellLine(r8.cells[A], r8.today).today, NO_DATA_TODAY);
  assert.equal(cellLine(ROWS.find((r) => r.stock_id === "6666")!.cells[A], "rows").today, NOT_TOP15_TODAY);
  assert.equal(cellLine(undefined, "pending").today, PENDING_TODAY);
  // 今天的篩選不會把未匯入的股票當成主分點沒動
  assert.ok(!ids(filterRows(ROWS, SET, "buy", "any")).includes("7777"));
});

test("coverageText / holdCapText", () => {
  assert.equal(coverageText(INDEX), "10/16 分點已匯入 1,500 / 1,956 檔,其餘待下一輪更新;還沒匯入的股票今天的進出未知(標「尚未匯入」),不會出現在買超／賣超篩選裡。");
  assert.equal(coverageText({ ...INDEX, coverage: { covered: 1956, expected: 1956, complete: false } }), null);
  // 匯入端記為完成:確認空的 ~2% 不是待補,不出提示
  assert.equal(coverageText({ ...INDEX, coverage: { covered: 1910, expected: 1956, complete: true } }), null);
  assert.equal(coverageText({ ...INDEX, coverage: null }), null);
  assert.equal(coverageText({ ...INDEX, coverage: undefined }), null);
  assert.equal(holdCapText(INDEX, [A, B, C]), "今天沒進出的估計仍持有:富邦-新店 共 85 檔,只列持有最多的 60 檔。");
  assert.equal(holdCapText(INDEX, [B, C]), null);
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
  assert.deepEqual(searchBranches(INDEX, "富邦", []).map((b) => b[0]), [A, "富邦-新竹"]);
  assert.deepEqual(searchBranches(INDEX, "  ", []), []);
  // 使用者自己的寫法:不打連字號、全形、空白、臺／台
  assert.deepEqual(searchBranches(INDEX, "富邦新店", []).map((b) => b[0]), [A]);
  assert.deepEqual(searchBranches(INDEX, "永豐金 內湖", []).map((b) => b[0]), [B]);
  assert.deepEqual(searchBranches(INDEX, "元大－松江", []).map((b) => b[0]), [C]);
  assert.deepEqual(searchBranches(INDEX, "華南永昌台中", []).map((b) => b[0]), ["華南永昌-臺中"]);
  assert.equal(looseName("ＡＢ－c d"), "abcd");
});

test("cellLine:未知不寫成 0", () => {
  const r6 = ROWS.find((r) => r.stock_id === "6666")!;
  assert.deepEqual(cellLine(r6.cells[A]), { today: "今天未進前 15 大", hold: "估計仍持有 3,000 張 · 進場 08/01" });
  assert.equal(cellLine(undefined).today, "近 60 日未見");
  assert.equal(cellLine(ROWS.find((r) => r.stock_id === "5555")!.cells[C]).today, "今天賣超 80 張");
});

// ── 權證(docs/52 §8)──
// 4444:B 現股買、主分點 A 沒有現股列、只買認購 320 萬;9999:沒有任何現股列,C 買認購、A 買認售;
// 5555:A 現股賣、C 認售淨賣(只列不算);1111:A 認購淨賣 150 萬(現股買)→ 同時在賣方
const W_SHARDS: WatchShard[] = [
  { ...SHARDS[0], warrants: {
    [A]: [
      ["1111", -1_500_000, null, null, null, null, null],
      ["4444", 3_200_000, null, 6_000_000, 95.3, null, null],
      ["9999", null, 2_000_000, null, null, null, null],
    ],
    [C]: [
      ["5555", null, -1_200_000, null, null, null, null],
      ["9999", 1_100_000, null, null, null, null, null],
    ],
  }, stocks: { ...SHARDS[0].stocks, "9999": ["壬", 80, 2, 3000, 1] } },
  SHARDS[1],
];
const WMETA = { data_date: "2026-10-16", day: "2026-10-16", counted: true, min_amount: 1_000_000 };
const W_ROWS = buildRows(SET, W_SHARDS, true);
const W_STALE = buildRows(SET, W_SHARDS, false);
const row = (rs: typeof W_ROWS, id: string) => rs.find((r) => r.stock_id === id)!;

test("權證:認購淨買 → 同買、認購淨賣／認售淨買 → 同賣、認售淨賣不計", () => {
  assert.deepEqual(row(W_ROWS, "4444").wBuyers, [A]);
  assert.deepEqual(participants(row(W_ROWS, "4444"), "buy"), [A, B]);
  assert.deepEqual(participants(row(W_ROWS, "4444"), "buy", false), [B]);
  assert.deepEqual(participants(row(W_ROWS, "9999"), "buy"), [C]);
  assert.deepEqual(participants(row(W_ROWS, "9999"), "sell"), [A]);
  // 認售淨賣:不進賣方、也不進買方
  assert.deepEqual(row(W_ROWS, "5555").wSellers, []);
  assert.deepEqual(row(W_ROWS, "5555").wBuyers, []);
  // 現股買超＋認購淨賣:兩邊都有
  assert.deepEqual(participants(row(W_ROWS, "1111"), "sell"), [A]);
  assert.equal(warrantOnlyCount(row(W_ROWS, "4444"), "buy"), 1);
});

test("權證:組合篩選與計數(主分點只買認購也算主分點買超;含權證關掉回到只看現股)", () => {
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "buy", "anchor")).sort(), ["1111", "2222", "3333", "4444"]);
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "buy", "anchor_plus")).sort(), ["1111", "2222", "4444"]);
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "buy", "any")).sort(), ["1111", "2222", "3333", "4444", "9999"]);
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "sell", "anchor")).sort(), ["1111", "5555", "9999"]);
  // 關掉含權證:與沒有權證時相同
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "buy", "anchor", 100, false)).sort(), ["1111", "2222", "3333"]);
  assert.deepEqual(ids(filterRows(W_ROWS, SET, "buy", "any", 100, false)).sort(), ["1111", "2222", "3333", "4444"]);
  assert.equal(todayCount(W_ROWS), 6);
  assert.equal(todayCount(W_ROWS, false), 5);
});

test("權證:資料日比現股舊 → 只列出、不算同買／同賣", () => {
  assert.deepEqual(row(W_STALE, "4444").wBuyers, []);
  assert.deepEqual(ids(filterRows(W_STALE, SET, "buy", "any")).sort(), ["1111", "2222", "3333", "4444"]);
  assert.equal(todayCount(W_STALE), 5);
  const stale = { ...WMETA, data_date: "2026-10-15", day: "2026-10-15", counted: false };
  const chips = warrantChips(row(W_STALE, "4444").warrants[A], stale);
  assert.deepEqual(chips, [{ text: "權證分點 10/15 認購 +320萬", side: null }]);
  assert.equal(
    warrantStaleText({ ...INDEX, warrant: stale }),
    "權證分點資料日 10/15,比現股分點 10/16 舊:權證進出只列出(標日期),不算進今天的同買／同賣,待下一輪更新。",
  );
  assert.equal(warrantStaleText({ ...INDEX, warrant: WMETA }), null);
  assert.equal(warrantStaleText(INDEX), null);
});

test("權證:匯入未完整 → 不計、標未完整;未收集的標的有一句話", () => {
  const inc = { ...WMETA, counted: false, complete: false };
  assert.deepEqual(warrantChips(row(W_STALE, "4444").warrants[A], inc), [{ text: "權證分點 10/16 未完整 認購 +320萬", side: null }]);
  assert.equal(
    warrantStaleText({ ...INDEX, warrant: inc }),
    "權證分點尚未完整:10/16 權證分點有一部分還沒抓到,權證進出只列出(標「未完整」),不算進今天的同買／同賣,待下一輪更新。",
  );
  const pooled = buildRows(SET, [SHARDS[1], { ...W_SHARDS[0], stocks: { ...W_SHARDS[0].stocks, "1111": ["甲", 10, 1.5, 500, 1, 0], "4444": ["丁", 30, 1, 2000, 1, 1] } }], true);
  const idx = { ...INDEX, warrant: WMETA };
  assert.equal(row(pooled, "1111").warrantPooled, false);
  assert.equal(warrantCoverageLine(row(pooled, "1111"), idx), "權證:未收集(10/16 這檔沒有成交 ≥ 100 萬的認購／認售)");
  assert.equal(warrantCoverageLine(row(pooled, "4444"), idx), null);
  assert.equal(warrantCoverageLine(row(pooled, "4444"), { ...INDEX, warrant: inc }), "權證:10/16 分點尚未完整,只列出不計");
  assert.equal(warrantCoverageLine(row(pooled, "4444"), { ...INDEX, warrant: { ...WMETA, day: "2026-10-15", counted: false } }), "權證:10/16 未收集(權證分點只到 10/15)");
  assert.equal(warrantCoverageLine(row(pooled, "4444"), INDEX), null);
});

test("權證:膠囊與持有文案", () => {
  assert.deepEqual(warrantChips(row(W_ROWS, "4444").warrants[A], WMETA), [{ text: "權證 認購 +320萬", side: "buy" }]);
  assert.deepEqual(warrantChips(row(W_ROWS, "1111").warrants[A], WMETA), [{ text: "權證 認購 −150萬", side: "sell" }]);
  assert.deepEqual(warrantChips(row(W_ROWS, "5555").warrants[C], WMETA), [{ text: "權證 認售 −120萬", side: null }]);
  assert.deepEqual(warrantChips(row(W_ROWS, "9999").warrants[A], WMETA), [{ text: "權證 認售 +200萬", side: "sell" }]);
  assert.deepEqual(warrantHeldLines(row(W_ROWS, "4444").warrants[A], WMETA), ["權證 認購 仍持有(估) 600萬 · 換算均價 95.3"]);
  assert.deepEqual(warrantChips(undefined, WMETA), []);
  assert.deepEqual(warrantChips(row(W_ROWS, "4444").warrants[A], null), []);
  assert.equal(fmtWan(150_000_000), "+1.5億");
});

test("權證:金額排序含權證金額", () => {
  const buy = filterRows(W_ROWS, SET, "buy", "any");
  // 2222:現股 3,400 萬;4444:現股 900 × 30 × 1000 = 2,700 萬 + 權證 320 萬;9999:只有權證 110 萬
  assert.equal(sideWarrantAmount(row(W_ROWS, "4444"), "buy"), 3_200_000);
  assert.equal(sideWarrantAmount(row(W_ROWS, "9999"), "sell"), 2_000_000);
  assert.equal(sideWarrantAmount(row(W_ROWS, "1111"), "sell"), 1_500_000);
  assert.deepEqual(ids(sortRows(buy, "buy", "amount")), ["2222", "4444", "3333", "1111", "9999"]);
  // 權證金額大到超過:4444 的認購換成 800 萬 → 3,500 萬 > 3,400 萬
  const big = { ...row(W_ROWS, "4444"), warrants: { [A]: { ...row(W_ROWS, "4444").warrants[A], call: 8_000_000 } } };
  assert.deepEqual(ids(sortRows([row(W_ROWS, "2222"), big], "buy", "amount")), ["4444", "2222"]);
  assert.deepEqual(ids(sortRows([row(W_ROWS, "2222"), big], "buy", "amount", false)), ["2222", "4444"]);
  // 3333(1,000 萬)vs 一檔只有權證 1,200 萬的情形:含權證時權證金額也比
  const only = { ...row(W_ROWS, "9999"), stock_id: "0001", wBuyers: [C], warrants: { [C]: { call: 12_000_000, put: null, callHeld: null, callAvg: null, putHeld: null, putAvg: null } } };
  assert.deepEqual(ids(sortRows([row(W_ROWS, "3333"), only], "buy", "amount")), ["0001", "3333"]);
  assert.deepEqual(ids(sortRows([row(W_ROWS, "3333"), only], "buy", "amount", false)), ["3333", "0001"]);
});

test("均價(估):文案、合計與排序", () => {
  assert.equal(avgLine(100, 104.2), "均價(估) 100.0 · 現價高於均價 +4.2%");
  assert.equal(avgLine(100, 96.9), "均價(估) 100.0 · 現價低於均價 −3.1%");
  assert.equal(avgLine(100, 100), "均價(估) 100.0 · 現價約等於均價");
  assert.equal(avgLine(null, 100), null);
  assert.equal(gapPct(110, 100)?.toFixed(1), "10.0");
  const mk = (id: string, close: number, avg: number | null, hold = 500) => ({
    ...row(W_ROWS, "6666"), stock_id: id, close,
    cells: { [A]: { ...row(W_ROWS, "6666").cells[A], hold, avg } },
  });
  const rs = [mk("a", 90, 100), mk("b", 120, 100), mk("c", 50, null), mk("d", 95, 100)];
  assert.deepEqual(ids(sortRows(rs, "hold", "gap", true, [A])), ["a", "d", "b", "c"]);
  const two = { ...mk("e", 100, 90, 100), cells: { [A]: { ...mk("e", 100, 90, 100).cells[A] }, [B]: { ...mk("e", 100, 120, 300).cells[A] } } };
  assert.equal(combinedAvg(two, [A, B]).avg, (100 * 90 + 300 * 120) / 400);
  const partial = { ...two, cells: { ...two.cells, [C]: { ...two.cells[A], avg: null } } };
  assert.equal(combinedAvg(partial, [A, B, C]).partial, true);
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
    HONESTY_NOTE, PUSH_NOTE, PENDING_TODAY, NO_DATA_TODAY, NOT_TOP15_TODAY, SEARCH_EMPTY, coverageText(INDEX) ?? "", holdCapText(INDEX, [A]) ?? "", ...Object.values(SIDE_LABEL), ...SORT_OPTIONS.map((s) => s.label),
    ...modes.flatMap((m) => (["buy", "sell"] as const).flatMap((s) => [modeLabel(m, s), modeDefinition(m, s, A, 3), emptyText(s, m, "2026-10-16")])),
    emptyText("hold", "anchor", "2026-10-16"), emptyText("buy", "anchor", null),
    ...ROWS.flatMap((r) => Object.values(r.cells).flatMap((c) => Object.values(cellLine(c, r.today)))),
    WARRANT_RULE, WARRANT_NOTE, WARRANT_OFF,
    warrantStaleText({ ...INDEX, warrant: { ...WMETA, day: "2026-10-15", data_date: "2026-10-15", counted: false } }) ?? "",
    ...W_ROWS.flatMap((r) => Object.values(r.warrants).flatMap((w) => [
      ...warrantChips(w, WMETA).map((c) => c.text), ...warrantChips(w, { ...WMETA, counted: false }).map((c) => c.text),
      ...warrantHeldLines(w, WMETA),
    ])),
    avgLine(100, 104.2) ?? "", avgLine(100, 96.9) ?? "", avgLine(100, 100) ?? "",
    warrantStaleText({ ...INDEX, warrant: { ...WMETA, counted: false, complete: false } }) ?? "",
    ...W_ROWS.flatMap((r) => [
      warrantCoverageLine({ ...r, warrantPooled: false }, { ...INDEX, warrant: WMETA }) ?? "",
      warrantCoverageLine(r, { ...INDEX, warrant: { ...WMETA, counted: false, complete: false } }) ?? "",
      warrantCoverageLine(r, { ...INDEX, warrant: { ...WMETA, day: "2026-10-15", counted: false } }) ?? "",
    ]),
  ];
  for (const t of texts) for (const w of banned) assert.ok(!t.includes(w), `「${t}」含禁用詞 ${w}`);
});
