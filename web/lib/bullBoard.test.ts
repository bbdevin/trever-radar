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
  type BoardCandidate,
} from "./bullBoard.ts";
import type { BullBoardJson } from "./types.ts";

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
    "bear", "bear_key_n", "bull", "bull_key_n", "chg_pct", "close", "counts", "final", "id", "industry", "market", "name", "state", "turnover",
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
  assert.equal(incompleteText(both), "法人、分點尚未到齊:目前只有技術面與價格事實;法人 16:00 起、分點 17:30 起到齊後重算。");
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
  ];
  const banned = new RegExp(bannedWords.join("|"));
  const b = board({ data_date: "2026-10-01", inputs: { ...board().inputs, insti: { date: null, stale: true }, branch: { date: null, stale: true } } });
  const texts = [
    BOARD_TAB_LABEL, BOARD_DEFINITION, BOARD_MISSING, BOARD_NO_BEAR,
    emptyText(b), staleText(b, RADAR)!, incompleteText(b)!, countLine(b), inputsLine(b), recordLine(b),
  ];
  for (const t of texts) assert.ok(!banned.test(t), t);
  assert.ok(banned.test(word(0x6a5f, 0x7387)), "regex 本身有效");
  assert.equal(BOARD_TAB_LABEL.length, 3);
});
