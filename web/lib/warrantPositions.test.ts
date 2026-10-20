// 執行: node --test web/lib/warrantPositions.test.ts
//
// 權證持有估算(docs/51)的顯示邏輯、篩選與鎖定文案;禁用詞鎖。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_SCREEN_FILTER,
  ENTRY_CAP_NOTE,
  ENTRY_INLINE_MAX,
  ENTRY_NOTE,
  KIND_LABEL,
  entryLine,
  entryRestLine,
  fmtMD,
  type BuyDay,
  SCREEN_DEFAULT_PCT,
  SCREEN_DIR_LABEL,
  SCREEN_GAIN_STEPS,
  SCREEN_LEAD,
  SCREEN_LOSS_STEPS,
  SCREEN_PARAM_KEYS,
  SCREEN_SORTS,
  SCREEN_STEPS,
  screenEmptyText,
  withScreenDir,
  WPOS_FOOTER,
  WPOS_FORMULA,
  WPOS_HEADING,
  WPOS_LEAD,
  WPOS_UNDER_NOTE,
  branchPosition,
  filterScreenRows,
  fmtPct,
  hasHolding,
  holdingLine,
  normalizePositions,
  normalizeScreening,
  positionNotes,
  screenSummary,
  underDiffPct,
  underDiffText,
  unrealizedText,
  type PositionAgg,
  type ScreenRow,
} from "./warrantPositions.ts";

function agg(over: Partial<PositionAgg> = {}): PositionAgg {
  return {
    lots: 600, cost: 12_000_000, buy_lots: 600, sell_lots_attributed: 0, sell_lots_unattributed: 0,
    realized: 0, n_warrants: 1, n_held: 1, n_expired: 0, n_no_price: 0, n_cost_unknown: 0, self_cost: 0,
    warrants: [], avg_under: 1000, cost_valued: 12_000_000, value: 7_200_000, unrealized: -4_800_000,
    unrealized_pct: -40, last_buy_date: "2026-08-03", first_date: "2026-08-03", ...over,
  };
}

test("鎖定文案逐字", () => {
  assert.equal(WPOS_HEADING, "權證持有（估算）");
  assert.equal(
    WPOS_LEAD,
    "只用每檔權證每日前 15 大進出看得見的張數，以當日權證收盤價當成交價、平均成本法估算；近 120 個交易日的起點視為零持股，看不見的日子視為沒交易。認購與認售分開計。",
  );
  assert.equal(
    WPOS_UNDER_NOTE,
    "換算現股均價＝這家券商各筆買超當天的現股收盤，以該筆買超金額加權；只是「買的那幾天現股在哪」，不是以履約價算出的損益兩平點。",
  );
  assert.equal(
    WPOS_FOOTER,
    "估算不是帳戶損益；券商分點不等於單一個人；權證有時間價值，放著不動帳面也會縮水；發行商在自家權證上的進出多為造市／避險，請看「發行商」「同券商」標籤。",
  );
});

test("禁用詞不出現在任何文案", () => {
  // 字面不寫出來:pipeline/tests/test_label_honesty.py 會掃 web/ 的字串字面(與 bullBoard.test.ts 同一招)。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const banned = [
    word(0x52dd, 0x7387),          // 勝率
    word(0x7372, 0x5229),          // 獲利
    word(0x5831, 0x916c),          // 報酬
    word(0x95dc, 0x9375, 0x5206, 0x9ede), // 關鍵分點
    word(0x5927, 0x6f32),          // 大漲
    word(0x5674),                  // 噴
    word(0x6975, 0x54c1),          // 極品
    word(0x6a5f, 0x7387),          // 機率
    word(0x76ee, 0x6a19, 0x50f9),  // 目標價
    word(0x8cb7, 0x9032),          // 買進
    word(0x8ce3, 0x51fa),          // 賣出
    word(0x770b, 0x591a),          // 看多
    word(0x770b, 0x7a7a),          // 看空
    word(0x5c07, 0x6703),          // 將會
    word(0x6709, 0x6548, 0x652f, 0x6490), // 有效支撐
    word(0x58d3, 0x529b, 0x6c89, 0x91cd), // 壓力沉重
    word(0x505a, 0x591a),          // 做多
    word(0x505a, 0x7a7a),          // 做空
    word(0x5efa, 0x8b70),          // 建議
    word(0x558a, 0x55ae),          // 喊單
    word(0x5957, 0x7262),          // 套牢
  ];
  assert.equal(banned[0], word(0x52dd, 0x7387));
  assert.equal(banned.length, 21);
  const a = agg({ n_expired: 1, n_no_price: 1, n_cost_unknown: 1, cost_valued: 6_000_000, sell_lots_unattributed: 40, self_cost: 3_000_000 });
  const texts = [
    WPOS_HEADING, WPOS_LEAD, WPOS_UNDER_NOTE, WPOS_FOOTER, SCREEN_LEAD, ENTRY_NOTE, ENTRY_CAP_NOTE, ...WPOS_FORMULA,
    entryRestLine({ n: 8, lots: 120, cost: 360_000, first: "2026-08-20", last: "2026-10-09" }) ?? "",
    entryLine([["2026-09-15", 120, 1, 500]]) ?? "", entryLine(Array.from({ length: 5 }, () => ["2026-09-15", 1, 1, null] as BuyDay)) ?? "",
    ...positionNotes(a), holdingLine(a) ?? "", unrealizedText(a) ?? "", underDiffText(1000, 920) ?? "",
    underDiffText(1000, 1080) ?? "", underDiffText(1000, 1000) ?? "",
    screenSummary(3, { excluded_self: 2, down: { rows: [srow()], total: 5 }, up: { rows: [srow()], total: 5 } }, "down"),
    screenSummary(3, { excluded_self: 2, down: { rows: [srow()], total: 5 }, up: { rows: [srow()], total: 5 } }, "up"),
    screenEmptyText("down"), screenEmptyText("up"), ...Object.values(SCREEN_DIR_LABEL),
    ...SCREEN_SORTS.map((s) => s.label), ...SCREEN_LOSS_STEPS.map((s) => s.label),
    ...SCREEN_GAIN_STEPS.map((s) => s.label), ...Object.values(KIND_LABEL),
  ];
  for (const t of texts) for (const w of banned) assert.ok(!t.includes(w), `「${t}」含禁用詞 ${w}`);
});

test("進場日:≤3 天逐日、更多只列起訖與天數;日期 MM/DD", () => {
  assert.equal(fmtMD("2026-09-15"), "09/15");
  assert.equal(fmtMD("bad"), "bad");
  assert.equal(entryLine(undefined), null);
  assert.equal(entryLine([]), null);
  assert.equal(entryLine([["2026-09-15", 120, 1, 500], ["2026-09-16", 80, 1, 510], ["2026-09-22", 40, 1, 505]]),
    "進場 09/15 120 張 · 09/16 80 張 · 09/22 40 張");
  assert.equal(entryLine([["2026-09-15", 1200, 1, 500]]), "進場 09/15 1,200 張");
  const many: BuyDay[] = Array.from({ length: 8 }, (_, i) => [`2026-09-${String(2 + i).padStart(2, "0")}`, 10, 1, null]);
  many[7][0] = "2026-10-07";
  assert.equal(entryLine(many), "09/02 起 共 8 天，最近 10/07");
  assert.equal(ENTRY_INLINE_MAX, 3);
  // 其餘併成一段:天數相加、起訖取兩邊最早／最晚;≤3 天但有其餘 → 也走摘要寫法
  const rest = { n: 8, lots: 120, cost: 360_000, first: "2026-08-20", last: "2026-10-09" };
  assert.equal(entryLine([["2026-09-15", 120, 1, 500], ["2026-09-16", 80, 1, 510]], rest), "08/20 起 共 10 天，最近 10/09");
  assert.equal(entryLine(many, { ...rest, first: "2026-09-10", last: "2026-09-20" }), "09/02 起 共 16 天，最近 10/07");
  assert.equal(entryRestLine(rest), "其餘 8 天合計 120 張 · 成本 36 萬（08/20–10/09）");
  assert.equal(entryRestLine(undefined), null);
});

test("排行列第二行與帳面文字", () => {
  assert.equal(holdingLine(agg()), "持有(估) 1,200萬 · −40.0%");
  assert.equal(holdingLine(agg({ unrealized_pct: undefined })), "持有(估) 1,200萬 · 未估值");
  assert.equal(holdingLine(agg({ cost: 270_000_000, cost_valued: 270_000_000, unrealized_pct: 12 })), "持有(估) 2.7億 · +12.0%");
  // 只估到一部分成本 → 標「(部分)」,百分比的分母不是整筆成本。
  assert.equal(holdingLine(agg({ cost_valued: 6_000_000 })), "持有(估) 1,200萬 · −40.0%(部分)");
  assert.equal(holdingLine(agg({ lots: 0, cost: 0 })), null);
  assert.equal(holdingLine(null), null);
  assert.equal(unrealizedText(agg()), "帳面估算 −480 萬（−40.0%）");
  assert.equal(unrealizedText(agg({ unrealized: 250_000, unrealized_pct: 2.1 })), "帳面估算 +25 萬（+2.1%）");
  assert.equal(unrealizedText(agg({ unrealized: undefined })), null);
  assert.equal(fmtPct(-40), "−40.0%");
  assert.equal(fmtPct(0), "0.0%");
  assert.equal(fmtPct(null), null);
});

test("換算現股均價 vs 現股", () => {
  assert.equal(Math.round((underDiffPct(1000, 920) ?? 0) * 10) / 10, -8);
  assert.equal(underDiffPct(undefined, 920), null);
  assert.equal(underDiffPct(1000, undefined), null);
  assert.equal(underDiffText(1000, 920), "現股 920.00，較換算均價低 8.0%");
  assert.equal(underDiffText(1000, 1080), "現股 1,080.00，較換算均價高 8.0%");
  assert.equal(underDiffText(1000, 1000.2), "現股 1,000.20，與換算均價相當");
});

test("條件註記", () => {
  assert.deepEqual(positionNotes(agg()), []);
  assert.deepEqual(
    positionNotes(agg({ n_expired: 1, n_no_price: 2, cost_valued: 6_000_000, sell_lots_unattributed: 40, self_cost: 6_000_000 })),
    [
      "1 檔已到期，仍持有的張數列入成本、不估值。",
      "2 檔近 5 個交易日沒有收盤價，不估值。",
      "帳面估算只涵蓋估得出值的 600 萬 成本（共 1,200 萬）。",
      "另有 40 張賣超找不到對應的買超（窗口前已持有或榜外買超），未計入。",
      "其中 50% 的成本在同券商發行的權證上，多為發行商造市／避險。",
    ],
  );
});

test("normalize:缺鍵、版本不認得 → null;只收 wpos-avgcost-v1", () => {
  assert.equal(normalizePositions(undefined), null);
  assert.equal(normalizePositions({ version: "x", branches: {} }), null);
  const ok = normalizePositions({ version: "wpos-avgcost-v1", as_of: "2026-10-08", window_from: "2026-04-10", under_last: 920, under_last_date: "2026-10-08", branches: { 甲: { call: agg() } } });
  assert.ok(ok);
  assert.equal(ok.under_last, 920);
  assert.equal(branchPosition(ok, "甲", "call")?.lots, 600);
  assert.equal(branchPosition(ok, "甲", "put"), null);
  assert.equal(branchPosition(ok, "乙", "call"), null);
  assert.equal(hasHolding(ok.branches["甲"]), true);
  assert.equal(hasHolding({ call: agg({ lots: 0 }) }), false);
  assert.equal(hasHolding(undefined), false);
});

function srow(over: Partial<ScreenRow> = {}): ScreenRow {
  return {
    branch_name: "甲-分點", underlying_id: "2330", underlying_name: "台積電", kind: "call", lots: 600,
    cost: 12_000_000, n_held: 1, n_unvalued: 0, self_pct: 0, value: 7_200_000, unrealized: -4_800_000,
    unrealized_pct: -40, avg_under: 1000, last_buy_date: "2026-10-01", under_last: 920, ...over,
  };
}

test("篩選清單:門檻、種類、排序、估不出值的列", () => {
  const rows = [
    srow(),
    srow({ branch_name: "乙-分點", unrealized_pct: -10, unrealized: -1_000_000, cost: 10_000_000, last_buy_date: "2026-10-07" }),
    srow({ branch_name: "丙-分點", kind: "put", unrealized_pct: -60 }),
    srow({ branch_name: "丁-分點", unrealized_pct: undefined, unrealized: undefined, n_unvalued: 1, cost: 30_000_000 }),
    srow({ branch_name: "戊-分點", cost: 4_000_000, unrealized_pct: -70 }),
  ];
  assert.deepEqual(filterScreenRows(rows, DEFAULT_SCREEN_FILTER).map((r) => r.branch_name), ["甲-分點"]);
  assert.deepEqual(filterScreenRows(rows, { ...DEFAULT_SCREEN_FILTER, pct: 0 }).map((r) => r.branch_name),
    ["甲-分點", "乙-分點", "丁-分點"]);
  assert.deepEqual(filterScreenRows(rows, { ...DEFAULT_SCREEN_FILTER, pct: 0, sort: "cost" }).map((r) => r.branch_name),
    ["丁-分點", "甲-分點", "乙-分點"]);
  assert.deepEqual(filterScreenRows(rows, { ...DEFAULT_SCREEN_FILTER, pct: 0, sort: "recent" }).map((r) => r.branch_name),
    ["乙-分點", "丁-分點", "甲-分點"]);   // 同日 → 成本大的在前
  assert.deepEqual(filterScreenRows(rows, { ...DEFAULT_SCREEN_FILTER, kind: "put", pct: -20 }).map((r) => r.branch_name), ["丙-分點"]);
  assert.deepEqual(filterScreenRows(rows, { ...DEFAULT_SCREEN_FILTER, minCost: 0, pct: -20 }).map((r) => r.branch_name), ["戊-分點", "甲-分點"]);
  // 為負那邊即使「不限」也不列帳面為正的列(防禦;v3 檔本來就分開)。
  assert.deepEqual(filterScreenRows([...rows, srow({ branch_name: "正-分點", unrealized_pct: 5, unrealized: 600_000 })],
    { ...DEFAULT_SCREEN_FILTER, pct: 0 }).map((r) => r.branch_name), ["甲-分點", "乙-分點", "丁-分點"]);
});

test("篩選清單:帳面為正(由高到低、門檻 ≥、估不出值的不列)", () => {
  const up = withScreenDir(DEFAULT_SCREEN_FILTER, "up");
  const rows = [
    srow({ branch_name: "甲-分點", unrealized_pct: 35, unrealized: 4_200_000, last_buy_date: "2026-10-02" }),
    srow({ branch_name: "乙-分點", unrealized_pct: 80, unrealized: 2_400_000, cost: 3_000_000 }),            // < 500 萬
    srow({ branch_name: "丙-分點", unrealized_pct: 12.5, unrealized: 7_500_000, cost: 60_000_000, last_buy_date: "2026-10-07" }),
    srow({ branch_name: "丁-分點", unrealized_pct: 22, unrealized: 2_200_000, cost: 10_000_000 }),
    srow({ branch_name: "戊-分點", unrealized_pct: undefined, unrealized: undefined, n_unvalued: 1 }),       // 估不出
    srow({ branch_name: "己-分點", unrealized_pct: -3, unrealized: -360_000 }),                              // 為負
    srow({ branch_name: "庚-分點", kind: "put", unrealized_pct: 60, unrealized: 7_200_000 }),
  ];
  const names = (f: typeof up) => filterScreenRows(rows, f).map((r) => r.branch_name);
  assert.deepEqual(names(up), ["甲-分點", "丁-分點"]);                                   // 預設 +20% 以上,% 高的在前
  assert.deepEqual(names({ ...up, pct: 0 }), ["甲-分點", "丁-分點", "丙-分點"]);           // 不限:仍只有帳面 > 0
  assert.deepEqual(names({ ...up, pct: 0, sort: "unrealized" }), ["丙-分點", "甲-分點", "丁-分點"]);   // 金額大到小
  assert.deepEqual(names({ ...up, pct: 0, sort: "cost" }), ["丙-分點", "甲-分點", "丁-分點"]);
  assert.deepEqual(names({ ...up, pct: 0, sort: "recent" }), ["丙-分點", "甲-分點", "丁-分點"]);
  assert.deepEqual(names({ ...up, pct: 40 }), []);
  assert.deepEqual(names({ ...up, pct: 0, minCost: 0 }), ["乙-分點", "甲-分點", "丁-分點", "丙-分點"]);
  assert.deepEqual(names({ ...up, kind: "put" }), ["庚-分點"]);
  // 門檻:兩邊對稱
  assert.deepEqual(SCREEN_GAIN_STEPS.map((s) => s.key), SCREEN_LOSS_STEPS.map((s) => 0 - s.key || 0));
  assert.deepEqual(SCREEN_STEPS.up, SCREEN_GAIN_STEPS);
  assert.deepEqual(SCREEN_DEFAULT_PCT, { down: -20, up: 20 });
  assert.equal(fmtPct(12.5), "+12.5%");
});

function side(rows: ScreenRow[], total = rows.length) {
  return { rows, total };
}

test("篩選清單 payload(v3,認購／認售 × 帳面為負／為正)與摘要句", () => {
  assert.equal(normalizeScreening({ version: 1, definitions_version: "wpos-avgcost-v1", rows: [srow()] }), null);   // v1 混排:不收
  // v2(只有帳面最差的前 400,為正的大多被截掉)也不收:畫面顯示「等下一次匯出」。
  assert.equal(normalizeScreening({ version: 2, definitions_version: "wpos-avgcost-v1", kinds: { call: { rows: [srow()], total: 1, excluded_self: 0 } } }), null);
  assert.equal(normalizeScreening({ version: 3, definitions_version: "x", kinds: {} }), null);
  const p = normalizeScreening({
    version: 3, definitions_version: "wpos-avgcost-v1", data_date: "2026-10-08", window_from: "2026-04-10",
    min_cost: 5_000_000, max_rows_per_side: 400,
    kinds: {
      call: { excluded_self: 1, down: side([srow()], 2), up: side([srow({ unrealized_pct: 30, unrealized: 3_600_000 })], 5) },
      put: { excluded_self: 0, down: side([]), up: side([]) },
    },
  });
  assert.ok(p);
  assert.equal(p.max_rows_per_side, 400);
  assert.equal(p.kinds.call.down.rows.length, 1);
  assert.equal(p.kinds.call.up.total, 5);
  assert.deepEqual(p.kinds.put, { excluded_self: 0, down: { rows: [], total: 0 }, up: { rows: [], total: 0 } });
  // 缺 put 桶、缺 up 邊 → 空的,不是 undefined
  const q = normalizeScreening({ version: 3, definitions_version: "wpos-avgcost-v1", kinds: { call: { down: { rows: [srow()] } } } });
  assert.deepEqual(q?.kinds.put, { excluded_self: 0, down: { rows: [], total: 0 }, up: { rows: [], total: 0 } });
  assert.deepEqual(q?.kinds.call.up, { rows: [], total: 0 });
  assert.equal(q?.kinds.call.down.total, 1);
  // 舊檔(每邊沒有自己的 excluded_self):照實說是兩邊合計。
  assert.equal(screenSummary(1, p.kinds.call, "down"), "1 筆符合（檔內只保留帳面最差的前 1 / 共 2 筆，門檻與排序只在這 1 筆內）；另有 1 筆自家發行占過半（發行商造市／避險）未列（帳面為負、為正兩邊合計）");
  assert.equal(screenSummary(1, p.kinds.call, "up"), "1 筆符合（檔內只保留帳面最高的前 1 / 共 5 筆，門檻與排序只在這 1 筆內）；另有 1 筆自家發行占過半（發行商造市／避險）未列（帳面為負、為正兩邊合計）");
  const plain = { excluded_self: 0, down: side([srow()]), up: side([]) };
  assert.equal(screenSummary(1, plain, "down"), "1 筆符合");
  assert.equal(screenSummary(0, plain, "up"), "0 筆符合");
  assert.equal(screenSummary(0, { ...plain, excluded_self: 2 }, "up"), "0 筆符合；另有 2 筆自家發行占過半（發行商造市／避險）未列（帳面為負、為正兩邊合計）");
  // 新檔(2026-10-20):每邊只講自己那邊;那一邊是 0 就不提。
  const r = normalizeScreening({
    version: 3, definitions_version: "wpos-avgcost-v1",
    kinds: { call: { excluded_self: 3, down: { rows: [srow()], total: 1, excluded_self: 3 }, up: { rows: [], total: 0, excluded_self: 0 } } },
  });
  assert.equal(r?.kinds.call.down.excluded_self, 3);
  assert.equal(screenSummary(1, r!.kinds.call, "down"), "1 筆符合；另有 3 筆自家發行占過半（發行商造市／避險）未列");
  assert.equal(screenSummary(0, r!.kinds.call, "up"), "0 筆符合");
  assert.equal(screenEmptyText("down"), "沒有帳面估算為負、符合門檻的券商 × 標的。涵蓋已匯入權證池、每檔權證只有前 15 大分點；沒有資料不代表沒有持有。");
  assert.equal(screenEmptyText("up"), "沒有帳面估算為正、符合門檻的券商 × 標的。涵蓋已匯入權證池、每檔權證只有前 15 大分點；沒有資料不代表沒有持有。");
  assert.deepEqual(SCREEN_DIR_LABEL, { down: "帳面為負", up: "帳面為正" });
  assert.deepEqual([...SCREEN_PARAM_KEYS], ["wk", "wdir", "wpct", "wsort"]);
});
