// 執行: node --test --experimental-strip-types web/lib/bullBoard.test.ts
//
// 首頁「多方榜」(docs/48 §1):選入/排除、排序、上限、payload 形狀鎖、三態句子、禁詞。
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildBullBear, type DerivedFact, type Section, type Side, type Source } from "./bullBear.ts";
import {
  BOARD_CAP,
  BOARD_DEFINITION,
  BOARD_MISSING,
  BOARD_NO_BEAR,
  BOARD_TAB_LABEL,
  boardLogLine,
  boardView,
  buildBullBoard,
  countLine,
  emptyText,
  incompleteText,
  inputsLine,
  recordLine,
  selectBoard,
  staleText,
  BOARD_OTHER_GROUP,
  BOARD_VIEW_LABEL,
  groupBoardEntries,
  groupHeatText,
  groupSummary,
  groupSummaryText,
  GROUP_SUMMARY_LABEL,
  type BoardCandidate,
} from "./bullBoard.ts";
import { hottestListedTheme } from "./themeGroups.ts";
import type { BullBoardEntry, BullBoardJson } from "./types.ts";

const DAY = "2026-10-02";
const RADAR = { data_date: DAY, generated_at: "2026-10-02T22:05:00+08:00" };

let seq = 0;
function f(side: Side, section: Section, rank: number, extra: Partial<DerivedFact> = {}): DerivedFact {
  const source: Source = extra.source ?? (section === "tech" ? "tech" : section === "chips" ? "chips" : "levels");
  return { code: `X_T${seq++}`, side, source, section, text: `事實${seq}`, rank, ...extra };
}
const bull = (section: Section, rank = 4, extra: Partial<DerivedFact> = {}) => f("bull", section, rank, extra);
const bear = (section: Section, rank = 4, extra: Partial<DerivedFact> = {}) => f("bear", section, rank, extra);

function cand(id: string, facts: DerivedFact[], over: Partial<BoardCandidate> = {}): BoardCandidate {
  return {
    id,
    name: `股${id}`,
    market: "twse",
    industry: "電子",
    close: 100,
    chg_pct: 1.5,
    turnover: 1e8,
    final: 50,
    state: null,
    scored: true,
    lastT: DAY,
    summary: buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: facts, asOf: DAY }),
    ...over,
  };
}
const ids = (cs: BoardCandidate[]) => selectBoard(cs, DAY).qualified.map((x) => x.c.id);
const three = () => [bull("tech"), bull("chips"), bull("tech")];

test("3 條入榜、2 條不入榜", () => {
  assert.deepEqual(ids([cand("A", three()), cand("B", [bull("tech"), bull("chips")])]), ["A"]);
});

test("rank 3 的多方不算重點", () => {
  assert.deepEqual(ids([cand("A", [bull("tech"), bull("chips"), bull("tech", 3)])]), []);
});

test("技術/籌碼 rank 5 空方事件排除;rank 4 空方只計數", () => {
  const sel = selectBoard([cand("A", [...three(), bear("tech", 5)]), cand("B", [...three(), bear("chips", 5)]), cand("C", [...three(), bear("chips", 4)])], DAY);
  assert.deepEqual(sel.qualified.map((x) => x.c.id), ["C"]);
  assert.deepEqual(sel.excluded.map((x) => x.c.id), ["A", "B"]);
  assert.equal(sel.qualified[0].k.bear.length, 1);
});

test("滯後資料(date/dataDate)不計重點、也不排除", () => {
  assert.deepEqual(ids([cand("A", [bull("tech"), bull("chips"), bull("chips", 5, { date: "09/30" })])]), []);
  assert.deepEqual(ids([cand("B", [bull("tech"), bull("chips"), bull("chips", 4, { dataDate: "09/26", source: "holders" })])]), []);
  assert.deepEqual(ids([cand("C", [...three(), bear("chips", 5, { date: "09/30" })])]), ["C"]);
});

test("壓力段不計也不排除", () => {
  assert.deepEqual(ids([cand("A", [bull("tech"), bull("chips"), bull("levels", 5)])]), []);
  assert.deepEqual(ids([cand("B", [...three(), bear("levels", 5)])]), ["B"]);
});

test("母體:沒有評分、或最後一根 K 不是資料日 → 不在母體也不入榜", () => {
  const sel = selectBoard(
    [cand("A", three(), { scored: false }), cand("B", three(), { lastT: "2026-10-01" }), cand("C", three())],
    DAY,
  );
  assert.deepEqual(sel.universeIds, ["C"]);
  assert.deepEqual(sel.qualified.map((x) => x.c.id), ["C"]);
});

test("排序:重點條數 → 不同來源數 → 空方重點少 → 成交金額大 → 代號", () => {
  const four = cand("N4", [...three(), bull("tech")], { turnover: 1 });
  const srcMany = cand("S3", [bull("tech"), bull("chips", 4, { source: "inst" }), bull("chips", 4, { source: "margin" })], { turnover: 1 });
  const srcFew = cand("S1", [bull("tech"), bull("tech"), bull("tech")], { turnover: 9e9 });
  const bearMore = cand("BM", [bull("tech"), bull("tech"), bull("tech"), bear("tech")], { turnover: 9e9 });
  const bigTo = cand("T9", [bull("tech"), bull("tech"), bull("tech")], { turnover: 9e10 });
  const idB = cand("Z2", [bull("tech"), bull("tech"), bull("tech")], { turnover: 5 });
  const idA = cand("Z1", [bull("tech"), bull("tech"), bull("tech")], { turnover: 5 });
  assert.deepEqual(ids([idB, bearMore, srcFew, idA, bigTo, srcMany, four]), ["N4", "S3", "T9", "S1", "Z1", "Z2", "BM"]);
});

test("上限 40,不湊數;入榜數照實", () => {
  const cs = Array.from({ length: 45 }, (_, i) => cand(String(1000 + i), three()));
  const b = buildBullBoard(RADAR, selectBoard(cs, DAY), { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null });
  assert.equal(b.entries.length, BOARD_CAP);
  assert.equal(b.qualified, 45);
  assert.equal(b.universe, 45);
  assert.match(countLine(b), /入榜 45 檔,列出 40 檔/);
  const few = buildBullBoard(RADAR, selectBoard(cs.slice(0, 2), DAY), { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null });
  assert.equal(few.entries.length, 2);
  assert.equal(countLine(few), "檢視 2 檔 → 入榜 2 檔");
});

test("卡片:多方取重點前 3(rank 高者先);空方取最強一條;段計數", () => {
  const top = bull("chips", 5, { text: "最強多方" });
  const c = cand("A", [bull("tech"), bull("tech"), bull("chips"), top, bear("tech", 4, { text: "空方一條" }), bull("levels", 2)]);
  const b = buildBullBoard(RADAR, selectBoard([c], DAY), { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null });
  const e = b.entries[0];
  assert.equal(e.bull_key_n, 4);
  assert.equal(e.bull.length, 3);
  assert.equal(e.bull[0].text, "最強多方");
  assert.equal(e.bear?.text, "空方一條");
  assert.deepEqual(e.counts, { tech: { bull: 2, bear: 1 }, chips: { bull: 2, bear: 0 }, levels: { bull: 1, bear: 0 } });
  const none = buildBullBoard(RADAR, selectBoard([cand("B", three())], DAY), { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null });
  assert.equal(none.entries[0].bear, null);
});

test("payload 形狀鎖:沒有名次、rank、magnitude、分數、位置", () => {
  const c = cand("A", [...three(), bear("tech", 4, { magnitude: 3, date: "09/30" }), bull("tech", 4, { magnitude: 9 })]);
  const sel = selectBoard([c], DAY);
  const b = buildBullBoard(RADAR, sel, { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: "2026-09-26" });
  assert.deepEqual(Object.keys(b).sort(), [
    "data_date", "entries", "generated_at", "inputs", "log_from", "min_bull_key", "qualified", "radar_generated_at", "universe", "version",
  ]);
  assert.deepEqual(Object.keys(b.entries[0]).sort(), [
    "bear", "bear_key_n", "bull", "bull_key_n", "chg_pct", "close", "counts", "final", "id", "industry", "market", "name", "state", "theme", "turnover",
  ]);
  const banned = /^(rank|magnitude|score|position|points|dist|order|place|index)$/;
  const walk = (v: unknown, p: string) => {
    if (Array.isArray(v)) v.forEach((x, i) => walk(x, `${p}[${i}]`));
    else if (v && typeof v === "object")
      for (const [k, x] of Object.entries(v)) {
        assert.ok(!banned.test(k), `${p}.${k}`);
        walk(x, `${p}.${k}`);
      }
  };
  walk(b, "board");
  for (const it of b.entries[0].bull) assert.deepEqual(Object.keys(it).filter((k) => !["code", "source", "section", "text", "segments", "tf"].includes(k)), []);
  const line = boardLogLine(b, sel);
  assert.deepEqual(line.universe_ids, ["A"]);
  assert.equal(line.entries[0].bull_key_n, 4);
  walk(line, "log");
});

function board(over: Partial<BullBoardJson> = {}): BullBoardJson {
  return {
    version: "bull-board-v1",
    data_date: DAY,
    generated_at: "2026-10-02T22:06:00+08:00",
    radar_generated_at: RADAR.generated_at,
    log_from: "2026-10-01",
    universe: 742,
    qualified: 0,
    min_bull_key: 3,
    inputs: { insti: { date: DAY, stale: false }, branch: { date: DAY, stale: false }, margin: { date: "2026-10-01", stale: true }, holders_week: "2026-09-26" },
    entries: [],
    ...over,
  };
}

test("三態:沒算過 / 算過沒人入榜 / 名單", () => {
  assert.deepEqual(boardView(null, RADAR), { kind: "missing", text: BOARD_MISSING });
  const empty = boardView(board(), RADAR);
  assert.equal(empty.kind, "ready");
  if (empty.kind !== "ready") return;
  assert.equal(empty.empty, "今日檢視 742 檔,沒有股票同時有 3 條以上多方重點事實且無重大空方事件。");
  assert.deepEqual(empty.notices, []);
  assert.equal(empty.dateLabel, "10/02");
  assert.equal(empty.countLine, "檢視 742 檔 → 入榜 0 檔");
  assert.equal(empty.recordLine, "名單自 10/01 起每日留存;往後表現須累積 60 個交易日並通過事前登記的檢定,才會以次數顯示。");
  assert.equal(empty.inputsLine, "資料:法人 10/02、分點 10/02、資券 10/01、大戶(集保)09/26");
  const sel = selectBoard([cand("A", three())], DAY);
  const full = boardView(buildBullBoard(RADAR, sel, { generatedAt: "2026-10-02T22:06:00+08:00", logFrom: DAY, holdersWeek: null }), RADAR);
  assert.ok(full.kind === "ready" && full.empty === null && full.board.entries.length === 1);
});

test("停在上一版:資料日不同,或比 radar 舊 1 小時以上", () => {
  const old = board({ data_date: "2026-10-01", generated_at: "2026-10-01T22:06:00+08:00" });
  assert.equal(staleText(old, RADAR), "多方榜停在 10-01 22:06 那一版,其他資料已更新;下一輪會跟上。");
  assert.equal(staleText(board({ generated_at: "2026-10-02T20:59:00+08:00" }), RADAR), "多方榜停在 10-02 20:59 那一版,其他資料已更新;下一輪會跟上。");
  assert.equal(staleText(board({ generated_at: "2026-10-02T21:30:00+08:00" }), RADAR), null);
  // UTC 寫法也換成台北時間
  assert.match(staleText(board({ data_date: "2026-10-01", generated_at: "2026-10-01T14:06:00Z" }), RADAR)!, /10-01 22:06/);
  const v = boardView(old, RADAR);
  assert.ok(v.kind === "ready" && v.notices[0].key === "stale");
});

test("資料未到齊:法人、分點(時刻讀更新時間表)", () => {
  const both = board({ inputs: { ...board().inputs, insti: { date: "2026-10-01", stale: true }, branch: { date: "2026-10-01", stale: true } } });
  assert.equal(incompleteText(both), "法人、分點尚未到齊:目前只有技術面與價格事實;法人 16:00 起、分點 16:30 起到齊後重算。");
  assert.match(incompleteText(board({ inputs: { ...board().inputs, branch: { date: "2026-10-01", stale: true } } }))!, /^分點尚未到齊/);
  assert.match(incompleteText(board({ inputs: { ...board().inputs, insti: { date: "2026-10-01", stale: true } } }))!, /^法人尚未到齊/);
  assert.equal(incompleteText(board()), null);
});

test("禁詞:分頁名、定義句、狀態句", () => {
  // 用字碼組字,避免本測試檔自己被 test_label_honesty 掃到。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const bannedWords = [
    word(0x52dd, 0x7387), // 勝率
    word(0x6a5f, 0x7387), // 機率
    word(0x5927, 0x6f32), // 大漲
    word(0x8cb7, 0x9032), // 買進
    word(0x8ce3, 0x51fa), // 賣出
    word(0x770b, 0x591a), // 看多
    word(0x770b, 0x7a7a), // 看空
    word(0x5efa, 0x8b70), // 建議
    word(0x76ee, 0x6a19, 0x50f9), // 目標價
    word(0x7b2c), // 第(第 N 名)
    word(0x540d, 0x6b21), // 名次
    word(0x5674), // 噴
  ];
  const banned = new RegExp(bannedWords.join("|"));
  const b = board({ data_date: "2026-10-01", inputs: { ...board().inputs, insti: { date: null, stale: true }, branch: { date: null, stale: true } } });
  const texts = [
    BOARD_TAB_LABEL, BOARD_DEFINITION, BOARD_MISSING, BOARD_NO_BEAR,
    emptyText(b), staleText(b, RADAR)!, incompleteText(b)!, countLine(b), inputsLine(b), recordLine(b),
    BOARD_VIEW_LABEL.facts, BOARD_VIEW_LABEL.group, BOARD_OTHER_GROUP, groupHeatText(1.34)!, GROUP_SUMMARY_LABEL,
    groupSummaryText([{ key: "theme:AI", name: "AI", n: 3, target: "theme:AI" }, { key: "other:x", name: BOARD_OTHER_GROUP, n: 2, target: "x" }]),
  ];
  for (const t of texts) assert.ok(!banned.test(t), t);
  assert.ok(banned.test(word(0x6a5f, 0x7387)), "regex 本身有效");
  assert.equal(BOARD_TAB_LABEL.length, 3);
});

// ---------------------------------------------------------------------------
// 族群檢視(docs/48 §1.1):只重排畫面
// ---------------------------------------------------------------------------

function entry(id: string, over: Partial<BullBoardEntry> = {}): BullBoardEntry {
  const sel = selectBoard([cand(id, three())], DAY);
  return { ...buildBullBoard(RADAR, sel, { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null }).entries[0], ...over };
}
const T = (name: string, vs20: number | null = null) => ({ name, vs20 });
const shape = (gs: ReturnType<typeof groupBoardEntries>) => gs.map((g) => [g.name, g.kind, g.items.map((x) => x.e.id)]);

test("族群:檔數多的族群在前,同數依族群內最前面那檔的原順序;族群內維持原順序", () => {
  const es = [
    entry("A", { theme: T("散熱", 1.2) }),
    entry("B", { theme: T("CPO", 2.1) }),
    entry("C", { theme: T("散熱", 1.2) }),
    entry("D", { theme: T("CPO", 2.1) }),
    entry("E", { theme: T("CPO", 2.1) }),
    entry("F", { theme: T("機器人", 0.9) }),
    entry("G", { theme: null, industry: "航運業" }),
  ];
  assert.deepEqual(shape(groupBoardEntries(es)), [
    ["CPO", "theme", ["B", "D", "E"]],
    ["散熱", "theme", ["A", "C"]],
    ["機器人", "theme", ["F"]],
    ["航運業", "industry", ["G"]],
  ]);
  // 原陣列不被改動,i 指回原位置
  assert.deepEqual(es.map((e) => e.id), ["A", "B", "C", "D", "E", "F", "G"]);
  assert.deepEqual(groupBoardEntries(es)[0].items.map((x) => x.i), [1, 3, 4]);
  // 每檔只出現一次
  assert.equal(groupBoardEntries(es).reduce((n, g) => n + g.items.length, 0), es.length);
});

test("族群:沒有在榜題材 → 產業(熱度查 sectors)→ 「其他」永遠最後", () => {
  const es = [
    entry("A", { theme: null, industry: null }),
    entry("B", { theme: null, industry: null }),
    entry("C", { theme: null, industry: "半導體業" }),
  ];
  const gs = groupBoardEntries(es, { sectors: [T("半導體業", 1.05)] });
  assert.deepEqual(shape(gs), [["半導體業", "industry", ["C"]], [BOARD_OTHER_GROUP, "other", ["A", "B"]]]);
  assert.equal(gs[0].vs20, 1.05);
  assert.equal(gs[1].vs20, null);
});

test("族群:舊 payload(沒有 theme 鍵)從 radar.json 補查,只挑今日在榜題材中最熱的", () => {
  const old = (id: string, industry: string | null) => {
    const e = entry(id, { industry });
    delete e.theme;
    return e;
  };
  const es = [old("A", "電子"), old("B", "電子"), old("C", "電子"), old("D", null)];
  const ctx = {
    stocks: [
      { id: "A", themes: ["冷門題材", "AI", "散熱"] },
      { id: "B", themes: ["冷門題材"] },
      { id: "C" },
    ],
    themes: [T("AI", 1.1), T("散熱", 1.6)],
    sectors: [T("電子", 0.8)],
  };
  assert.deepEqual(shape(groupBoardEntries(es, ctx)), [
    ["電子", "industry", ["B", "C"]],
    ["散熱", "theme", ["A"]],
    [BOARD_OTHER_GROUP, "other", ["D"]],
  ]);
  // 沒有 radar 可查 → 全部依產業/其他,不丟例外
  assert.deepEqual(shape(groupBoardEntries(es)), [["電子", "industry", ["A", "B", "C"]], [BOARD_OTHER_GROUP, "other", ["D"]]]);
  assert.deepEqual(groupBoardEntries([]), []);
});

test("族群:熱度句", () => {
  assert.equal(groupHeatText(1.34), "成交為20日均 1.3 倍");
  assert.equal(groupHeatText(null), null);
  assert.equal(groupHeatText(Number.NaN), null);
});

test("族群欄位只影響顯示:有無 theme,入榜、排序與紀錄行完全相同", () => {
  const cs = [cand("A", [...three(), bull("tech")]), cand("B", three(), { turnover: 9e9 }), cand("C", three())];
  const withTheme = cs.map((c, i) => ({ ...c, theme: i === 1 ? T("AI", 1.5) : null }));
  const s1 = selectBoard(cs, DAY);
  const s2 = selectBoard(withTheme, DAY);
  const opts = { generatedAt: RADAR.generated_at, logFrom: DAY, holdersWeek: null };
  assert.deepEqual(s2.qualified.map((x) => x.c.id), s1.qualified.map((x) => x.c.id));
  assert.deepEqual(boardLogLine(buildBullBoard(RADAR, s2, opts), s2), boardLogLine(buildBullBoard(RADAR, s1, opts), s1));
  assert.deepEqual(buildBullBoard(RADAR, s2, opts).entries.map((e) => e.theme), [null, T("AI", 1.5), null]);
});
test("族群分布:同一個分組與順序,前 6 個有名字的族群,其餘併成「其他」放最後;點「其他」捲到第一個被併的族群", () => {
  const es: BullBoardEntry[] = [];
  const add = (n: number, over: Partial<BullBoardEntry>) => {
    for (let k = 0; k < n; k += 1) es.push(entry(`${es.length + 1000}`, over));
  };
  add(4, { theme: T("A1", 1.3) });
  add(3, { theme: null, industry: "B產業" });
  add(2, { theme: T("C3") });
  add(2, { theme: null, industry: null });
  add(1, { theme: T("D4") });
  add(1, { theme: T("E5") });
  add(1, { theme: T("F6") });
  add(1, { theme: T("G7") });
  add(1, { theme: T("H8") });
  const gs = groupBoardEntries(es);
  const chips = groupSummary(gs);
  assert.deepEqual(chips.map((c) => [c.name, c.n]), [["A1", 4], ["B產業", 3], ["C3", 2], ["D4", 1], ["E5", 1], ["F6", 1], [BOARD_OTHER_GROUP, 4]]);
  assert.equal(chips.at(-1)!.target, "theme:G7");
  assert.equal(chips.reduce((n, c) => n + c.n, 0), es.length);
  assert.equal(groupSummaryText(chips.slice(0, 2)), "多方集中:A1 4 檔、B產業 3 檔");
  // 只有「其他」時:一顆「其他」,目標就是「其他」組
  const onlyOther = groupSummary(groupBoardEntries([entry("X", { theme: null, industry: null })]));
  assert.deepEqual(onlyOther, [{ key: "other:其他", name: BOARD_OTHER_GROUP, n: 1, target: "other:其他" }]);
  // 族群少於上限 → 不加「其他」
  assert.deepEqual(groupSummary(groupBoardEntries([entry("Y", { theme: T("AI") })])).map((c) => c.name), ["AI"]);
  assert.deepEqual(groupSummary([]), []);
});
// ---------------------------------------------------------------------------
// 族群 key 碰撞(驗證者 2026-10-04):產業字面「其他」、題材與產業同名、空白題材名
// ---------------------------------------------------------------------------

test("族群:產業字面「其他」= 沒有產業,與 null 併成同一個「其他」並排最後、不標產業", () => {
  const es = [
    entry("A", { theme: null, industry: "其他" }),
    entry("B", { theme: null, industry: null }),
    entry("C", { theme: null, industry: "  " }),
    entry("D", { theme: T("AI", 1.2) }),
  ];
  const gs = groupBoardEntries(es);
  assert.deepEqual(shape(gs), [["AI", "theme", ["D"]], [BOARD_OTHER_GROUP, "other", ["A", "B", "C"]]]);
  assert.equal(gs.at(-1)!.kind, "other"); // 畫面上「產業」小標只給 kind === "industry"
  assert.equal(new Set(gs.map((g) => g.key)).size, gs.length);
});

test("族群分布:7 個題材 + 產業「其他」→ 只有一顆「其他」,鍵唯一;6 個題材時「其他」指向保底組", () => {
  const themes7 = ["T1", "T2", "T3", "T4", "T5", "T6", "T7"].map((n, k) => entry(`T${k}`, { theme: T(n) }));
  const tail = entry("Z", { theme: null, industry: "其他" });
  const chips = groupSummary(groupBoardEntries([...themes7, tail]));
  assert.deepEqual(chips.map((c) => [c.name, c.n]), [["T1", 1], ["T2", 1], ["T3", 1], ["T4", 1], ["T5", 1], ["T6", 1], [BOARD_OTHER_GROUP, 2]]);
  assert.equal(chips.filter((c) => c.name === BOARD_OTHER_GROUP).length, 1);
  assert.equal(new Set(chips.map((c) => c.key)).size, chips.length);
  assert.equal(chips.at(-1)!.target, "theme:T7"); // 捲到被併進「其他」的第一組(T7),保底組緊接其後
  const six = groupSummary(groupBoardEntries([...themes7.slice(0, 6), tail]));
  assert.deepEqual(six.at(-1), { key: "other:其他", name: BOARD_OTHER_GROUP, n: 1, target: "other:其他" });
});

test("族群:題材與產業同名 → 兩組,各自的 kind 與熱度", () => {
  const es = [
    entry("A", { theme: null, industry: "半導體業" }),
    entry("B", { theme: T("半導體業", 3) }),
    entry("C", { theme: T("半導體業", 3) }),
  ];
  const gs = groupBoardEntries(es, { sectors: [T("半導體業", 0.5)] });
  assert.deepEqual(shape(gs), [["半導體業", "theme", ["B", "C"]], ["半導體業", "industry", ["A"]]]);
  assert.deepEqual(gs.map((g) => [g.key, g.vs20]), [["theme:半導體業", 3], ["industry:半導體業", 0.5]]);
  const chips = groupSummary(gs);
  assert.equal(new Set(chips.map((c) => c.key)).size, chips.length);
});

test("族群:空白題材名不算題材,改用產業", () => {
  assert.equal(hottestListedTheme(["", "  "], [T("", 2), T("  ", 3)]), null);
  assert.deepEqual(hottestListedTheme([" ", "AI"], [T(" ", 9), T("AI", 1.1)]), T("AI", 1.1));
  // payload 裡已帶空白名 → 依產業
  const gs = groupBoardEntries([entry("A", { theme: T("  ", 2), industry: "航運業" })]);
  assert.deepEqual(shape(gs), [["航運業", "industry", ["A"]]]);
  // 舊 payload 從 radar.json 補查:空白名被略過
  const old = entry("B", { industry: "航運業" });
  delete old.theme;
  assert.deepEqual(shape(groupBoardEntries([old], { stocks: [{ id: "B", themes: [""] }], themes: [T("", 5)] })), [["航運業", "industry", ["B"]]]);
});