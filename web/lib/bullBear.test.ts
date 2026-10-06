// 執行: node --test --experimental-strip-types web/lib/bullBear.test.ts
//
// 多空(docs/46 v2):分類、三段、去重(code、鏡像、讓位、事實鍵)、舊 JSON 相容、每個 code 恰一次、
// 完整性(6488 型的空方要出現)、標頭挑選規則、分組、禁用詞鎖。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COLUMN_LABEL,
  CONTEXT_LABEL,
  COUNT_NOTE,
  EMPTY_SIDE,
  EMPTY_TECH_WITH_LEVELS,
  KEY_GROUP_LABEL,
  KEY_GROUP_MAX,
  PANEL_TITLE,
  RISK_TEXT_KEYS,
  SECTION_LABEL,
  SIDE_BY_CODE,
  SIDE_DEFINITION,
  SIDE_LABEL,
  SOURCE_LABEL,
  SOURCE_ORDER,
  TF_LABEL,
  buildBullBear,
  emptySideText,
  factKey,
  groupColumn,
  keyItems,
  overviewText,
  riskCodeFromText,
  topOfSide,
  type BullBearSummary,
  type DerivedFact,
} from "./bullBear.ts";
import { FACT_CATALOGUE } from "./facts/catalogue.ts";
import { LAST, holdersBull, instiSellStreak, marginConcBuildup, marginConcTdccDown, nearResistanceStock, okLevels, techBearSeries, techBullSeries } from "./facts/fixtures.ts";
import { holdersFacts } from "./facts/holdersFacts.ts";
import { deriveAllFacts } from "./facts/index.ts";
import { techFacts } from "./facts/techFacts.ts";
import { boardKeys } from "./bullBoard.ts";
import { isNear, priceLevelFacts, priceLevelsView } from "./priceLevels.ts";
import type { PriceLevels, ReasonItem, StockJson, TechnicalSummary } from "./types.ts";

// 以「·」拆開或用字碼組回,避免這個檔案本身被 test_label_honesty 掃到。
const BANNED = [
  "勝·率", "獲·利", "報·酬", "關鍵·分點", "大·漲", "極·品", "機·率", "目標·價", "買·進", "賣·出",
  "看·多", "看·空", "將·會", "有效·支撐", "壓力·沉重", "做·多", "做·空", "建·議", "喊·單",
].map((w) => w.replace("·", "")).concat(String.fromCharCode(0x5674));

const tech = (reasons: ReasonItem[], risks: ReasonItem[] = [], volume_ratio: number | null = 1.2): TechnicalSummary => ({
  score: 40, ma20: 100, ma60: 90, rsi14: 60, volume_ratio, reasons, risks,
});

const ALL = (s: BullBearSummary) => [...s.bull, ...s.bear, ...s.context];

function pl(over: Partial<Extract<PriceLevels, { status: "ok" }>> = {}): PriceLevels {
  return {
    version: 1, status: "ok", as_of: "2026-10-03", bars: 240, close: 120,
    ma: { "5": 115, "10": 112, "20": 110, "60": 100, "120": 130, "240": 140 },
    ma_align: "bull", highs: {}, lows: {}, new_high_20: true, new_low_20: false, vol_price_2d: null,
    vol_profile: null, dense_above: null, dense_below: null, ...over,
  };
}

test("分類表:每個 code 的側別與來源都有效;籌碼事件策略歸籌碼段來源", () => {
  for (const [code, v] of Object.entries(SIDE_BY_CODE)) {
    assert.ok(["bull", "bear", "context"].includes(v.side), code);
    assert.ok(SOURCE_ORDER.includes(v.source), code);
  }
  assert.equal(SIDE_BY_CODE.S4_COMPRESSION_SETUP_V2.side, "context");
  assert.equal(SIDE_BY_CODE.S4_VOLATILITY_CONTRACTION.side, "context");
  assert.equal(SIDE_BY_CODE.G2_GEO_SELL.side, "bear");
  assert.equal(SIDE_BY_CODE.KB1_BUYBACK_WINDOW.side, "context");
  assert.equal(SIDE_BY_CODE.K1_KEY_BUY.side, "bull");
  assert.equal(SIDE_BY_CODE.S12_BRANCH_ACCUMULATION.source, "chips");
  assert.equal(SIDE_BY_CODE.S11_INSTI_BREAKOUT.source, "inst");
  assert.equal(SIDE_BY_CODE.S13_SHORT_SQUEEZE.source, "margin");
  assert.equal(SIDE_BY_CODE.F1_FUTURES_VOLUME_60D_HIGH.side, "context");
  assert.equal(SIDE_BY_CODE.R_FUTURES_VOLUME_NO_DIRECTION.side, "context");
  for (const [, code] of RISK_TEXT_KEYS) assert.equal(SIDE_BY_CODE[code].side, "bear");
  // 前端事實目錄與後端分類表不共用 code
  for (const c of Object.keys(FACT_CATALOGUE)) assert.ok(!(c in SIDE_BY_CODE), c);
});

test("技術理由在 raw_reasons 與 technical.reasons 都有 → 只出現一次;段落 tech、週期 D", () => {
  const t1 = { code: "T1_BULL_MA", points: 15, text: "5/10/20日均線多頭排列" };
  const s = buildBullBear({
    rawReasons: [{ code: "B1_BRANCH_STREAK", points: 20, text: "分點【美林】連4日買超" }, t1],
    reasons: [], risks: [], rawRisks: [],
    technical: tech([t1, { code: "T1_MA20", points: 10, text: "收盤站上20日線" }]),
    asOf: "2026-10-03",
  });
  assert.deepEqual(s.bull.map((i) => i.code), ["T1_BULL_MA", "T1_MA20", "B1_BRANCH_STREAK"]);
  assert.deepEqual(s.sections.tech.bull.map((i) => [i.code, i.tf]), [["T1_BULL_MA", "D"], ["T1_MA20", "D"]]);
  assert.deepEqual(s.sections.chips.bull.map((i) => i.code), ["B1_BRANCH_STREAK"]);
  assert.deepEqual(s.suppressed, []);
});

test("價格位置事實同方向同一天 → 取代技術理由,記入 suppressed;F1 進壓力段", () => {
  const facts = priceLevelFacts(pl(), "2026-10-03", 60);
  const s = buildBullBear({
    rawReasons: [{ code: "T1_BULL_MA", points: 15, text: "5/10/20日均線多頭排列" }],
    reasons: [], risks: [], rawRisks: [],
    technical: tech([
      { code: "T1_MA20", points: 10, text: "收盤站上20日線" },
      { code: "T1_MA60", points: 10, text: "收盤站上60日線" },
      { code: "T2_20D_HIGH", points: 15, text: "收盤創20日新高" },
      { code: "T5_RSI", points: 5, text: "RSI14位於50至70的健康動能區" },
      { code: "T3_BOX_TOP", points: 15, text: "60日箱型整理且收盤接近區間上緣" },
    ]),
    priceFacts: facts,
    asOf: "2026-10-03",
  });
  assert.deepEqual(new Set(s.suppressed), new Set(["T1_BULL_MA", "T1_MA20", "T1_MA60", "T2_20D_HIGH", "T5_RSI"]));
  assert.deepEqual(s.sections.tech.bull.map((i) => i.text), [
    "收盤創20日新高",
    "60日箱型整理且收盤接近區間上緣",
    "5/10/20日均線多頭排列",
    "RSI14 60,位於 50–70",
  ]);
  assert.deepEqual(s.sections.levels.bull.map((i) => i.text), ["站上 5/10/20/60 日線,最接近 5日線 115.0(−4.2%)"]);
  assert.deepEqual(s.sections.levels.bear.map((i) => i.text), ["120/240 日線在上方,最接近 120日線 130.0(+8.3%)"]);
  // as_of 落後資料日 → 帶日期、不取代
  const stale = buildBullBear({
    rawReasons: [{ code: "T1_BULL_MA", points: 15, text: "5/10/20日均線多頭排列" }],
    reasons: [], risks: [], technical: null,
    priceFacts: priceLevelFacts(pl(), "2026-10-06"), asOf: "2026-10-06",
  });
  assert.deepEqual(stale.suppressed, []);
  assert.ok(stale.bull.some((i) => i.code === "T1_BULL_MA"));
  assert.ok(stale.bull.filter((i) => i.code?.startsWith("F")).every((i) => i.date === "10/03"));
});

test("R_RSI_OVERHEAT 兩個來源只出現一次(取 raw_risks 那句)", () => {
  const s = buildBullBear({
    rawReasons: [], reasons: [],
    rawRisks: [{ code: "R_RSI_OVERHEAT", points: 5, text: "RSI14超過80,短線過熱" }],
    risks: ["RSI14超過80,短線過熱"],
    technical: tech([], [{ code: "R_RSI_OVERHEAT", text: "RSI14超過80,短線動能過熱" }]),
    asOf: "2026-10-03",
  });
  assert.deepEqual(s.bear.map((i) => [i.code, i.text, i.risk, i.source, i.section]), [["R_RSI_OVERHEAT", "RSI14超過80,短線過熱", true, "tech", "tech"]]);
});

test("舊 JSON:沒有 raw_reasons/raw_risks → 用字串;風險字串回推 code,未知歸空方/其他(籌碼段)", () => {
  const texts = [
    "分點【統一】昨日大買後今日反手賣出,疑似倒貨",
    "5日累漲23%,追價風險高",
    "10日累漲40%,追價風險高",
    "爆量長上影,疑高檔換手或出貨",
    "開高走低(開盤+3%以上收黑)",
    "RSI14超過80,短線過熱",
    "外資連5日賣超",
    "融資使用率75%,融資過熱",
  ];
  assert.deepEqual(texts.map(riskCodeFromText), [
    "B_RISK_REVERSAL", "R_HOT5", "R_HOT10", "R_SHOOTING", "R_GAP_FADE", "R_RSI_OVERHEAT", "R_FOREIGN_SELL5", "R_MARGIN_HOT",
  ]);
  const s = buildBullBear({ reasons: ["某段沒有代碼的理由"], risks: ["外資連5日賣超", "看不懂的新風險"], technical: null, asOf: "2026-10-03" });
  assert.deepEqual(s.bull.map((i) => [i.code, i.source, i.section]), [[null, "other", "chips"]]);
  assert.deepEqual(s.bear.map((i) => [i.code, i.source]), [["R_FOREIGN_SELL5", "inst"], [null, "other"]]);
});

test("口袋標籤、背景、來源排序與同來源依 rank/points;標頭挑 rank 最高", () => {
  const s = buildBullBear({
    rawReasons: [
      { code: "S4_COMPRESSION_SETUP_V2", points: 0, text: "壓縮蓄勢" },
      { code: "W1_TURNOVER_X2", points: 10, text: "認購權證成交2倍" },
      { code: "B2_MULTI_BRANCH", points: 10, text: "5個分點同步買超" },
      { code: "B1_BRANCH_STREAK", points: 25, text: "分點連4日買超" },
      { code: "I_TRUST_BUY", points: 8, text: "投信買超" },
    ],
    reasons: [], risks: [], rawRisks: [{ code: "B_RISK_REVERSAL", points: 20, text: "昨日大買後今日反手賣出" }],
    technical: null,
    pocketTags: [
      { code: "G2_GEO_SELL", family: "GEO", text: "地緣分點賣超" },
      { code: "KB1_BUYBACK_WINDOW", family: "BUYBACK", text: "庫藏股買回期間" },
      { code: "K1_KEY_BUY", family: "KEY", text: "舊字樣:凱基" },
    ],
    pocketText: (t) => (t.code === "K1_KEY_BUY" ? "追蹤分點同買:凱基" : t.text),
    asOf: "2026-10-03",
  });
  assert.deepEqual(s.bull.map((i) => i.code), ["B1_BRANCH_STREAK", "B2_MULTI_BRANCH", "K1_KEY_BUY", "I_TRUST_BUY", "W1_TURNOVER_X2"]);
  assert.equal(s.bull[2].text, "追蹤分點同買:凱基");
  assert.deepEqual(s.bear.map((i) => i.code), ["B_RISK_REVERSAL", "G2_GEO_SELL"]);
  assert.ok(s.bear.every((i) => i.risk));
  assert.deepEqual(s.context.map((i) => [i.code, i.section]), [["S4_COMPRESSION_SETUP_V2", "tech"], ["KB1_BUYBACK_WINDOW", "chips"]]);
  assert.equal(topOfSide(s, "bull")?.code, "B1_BRANCH_STREAK");
  assert.equal(topOfSide(s, "bear")?.code, "B_RISK_REVERSAL");
  assert.equal(topOfSide(buildBullBear({ reasons: [], risks: [], technical: null, asOf: "x" }), "bull"), null);
});

test("每個輸入 code 在 bull ∪ bear ∪ context ∪ suppressed 恰出現一次", () => {
  const codes = Object.keys(SIDE_BY_CODE);
  const isPocket = (c: string) => /^(G\d|K1_|T1_TRACKED|H1_|KB)/.test(c);
  const reasons = codes.filter((c) => !c.startsWith("R_") && c !== "B_RISK_REVERSAL" && !isPocket(c))
    .map((code, i) => ({ code, points: i % 7, text: `理由${code}` }));
  const risks = codes.filter((c) => c.startsWith("R_") || c === "B_RISK_REVERSAL").map((code) => ({ code, points: 5, text: `風險${code}` }));
  const pockets = codes.filter(isPocket).map((code) => ({ code, family: "GEO" as const, text: `口袋${code}` }));
  const half = Math.floor(reasons.length / 2);
  const s = buildBullBear({
    rawReasons: reasons.slice(0, half + 3), reasons: [],
    rawRisks: risks, risks: [],
    technical: tech(reasons.slice(half), risks.slice(0, 2)),
    pocketTags: pockets,
    priceFacts: priceLevelFacts(pl({ vol_price_2d: "up" }), "2026-10-03", 60),
    derivedFacts: techFacts(techBullSeries(), tech([], [], 2)),
    asOf: "2026-10-03",
  });
  const seen = [...ALL(s).map((i) => i.code), ...s.suppressed].filter((c): c is string => !!c && !(c in FACT_CATALOGUE));
  assert.equal(seen.length, new Set(seen).size, "有 code 重複");
  assert.deepEqual(new Set(seen), new Set(codes));
  assert.ok(s.suppressed.length > 0);
  // 事實鍵(code+週期+variant)也不重複
  const keys = ALL(s).map((i) => i.key);
  assert.equal(keys.length, new Set(keys).size);
});

/**
 * 「技術訊號原文」收合區已移除(docs/46 §6.7):technical.reasons/risks 的每個 code 都必須在多空裡有一列,
 * 或被一條仍在畫面上的事實取代(suppressed 且鏡像事實那一列存在)。
 */
function assertTechRepresented(s: BullBearSummary, t: TechnicalSummary, facts: DerivedFact[]) {
  const rows = ALL(s);
  const keys = new Set(rows.map((i) => i.key));
  for (const r of [...t.reasons, ...t.risks]) {
    if (rows.some((i) => i.code === r.code)) continue;
    assert.ok(s.suppressed.includes(r.code), `${r.code} 既不在多空列也不在 suppressed`);
    const mirror = facts.find((f) => !f.date && !f.dataDate && f.mirrors?.includes(r.code) && keys.has(factKey(f)));
    assert.ok(mirror, `${r.code} 被取代但沒有對應的鏡像事實列`);
  }
}

test("技術訊號原文:technical 每個理由/風險 code 都在多空列,或被畫面上的鏡像事實取代", () => {
  const techCodes = Object.entries(SIDE_BY_CODE).filter(([, v]) => v.source === "tech").map(([c]) => c);
  const t = tech(
    techCodes.filter((c) => SIDE_BY_CODE[c].side !== "bear").map((code) => ({ code, points: 5, text: `理由${code}` })),
    techCodes.filter((c) => SIDE_BY_CODE[c].side === "bear").map((code) => ({ code, points: 5, text: `風險${code}` })),
  );
  const scenarios: Array<[string, DerivedFact[]]> = [
    ["無前端事實", []],
    ["多頭序列+價格位置", [...priceLevelFacts(pl({ vol_price_2d: "up" }), "2026-10-03", 60), ...techFacts(techBullSeries(), tech([], [], 2))]],
    ["空頭序列", techFacts(techBearSeries(), tech([], [], 2))],
    ["資料日落後(不取代)", priceLevelFacts(pl({ vol_price_2d: "up" }), "2026-10-06", 60)],
  ];
  for (const [name, facts] of scenarios) {
    const s = buildBullBear({ rawReasons: [], reasons: [], rawRisks: [], risks: [], technical: t, derivedFacts: facts, asOf: "2026-10-03" });
    assertTechRepresented(s, t, facts);
    if (name !== "無前端事實" && name !== "資料日落後(不取代)") assert.ok(s.suppressed.length > 0, name);
  }
  // 理由同時出現在 raw_reasons(先列)也算代表
  const both = buildBullBear({ rawReasons: t.reasons, reasons: [], rawRisks: t.risks, risks: [], technical: t, asOf: "2026-10-03" });
  assertTechRepresented(both, t, []);
});

test("完整性:6488 型 —— 240 日高、密集區、現價之上成交、外資連 5 日賣超都出現在空方;R_FOREIGN_SELL5 被取代", () => {
  const { ih, candles } = instiSellStreak();
  const data = {
    id: "6488", name: "樣本", market: "tpex", candles, technical: null, price_levels: okLevels(), insti_history: ih,
    scores: null, reasons: [], risks: [], branches: [], warrant: null, warrant_history: [], active_warrants: [],
  } as unknown as StockJson;
  const s = buildBullBear({
    reasons: [], risks: [], rawReasons: [], rawRisks: [{ code: "R_FOREIGN_SELL5", points: 8, text: "外資連5日賣超" }],
    technical: null, derivedFacts: deriveAllFacts(data, LAST), asOf: LAST,
  });
  const lv = s.sections.levels.bear;
  const hi = lv.find((i) => i.code === "L_HIGH_ABOVE");
  assert.ok(hi && hi.text.includes("+46.9%"), lv.map((i) => i.text).join("\n"));
  assert.ok(lv.some((i) => i.code === "L_DENSE_ABOVE"));
  assert.ok(lv.some((i) => i.code === "L_SUPPLY_ABOVE"));
  const fs = s.sections.chips.bear.find((i) => i.code === "C_FOREIGN_SELL");
  assert.ok(fs && fs.text.includes("連 5 日"));
  assert.ok(s.suppressed.includes("R_FOREIGN_SELL5"));
  assert.ok(!s.bear.some((i) => i.code === "R_FOREIGN_SELL5"));
  // 壓力段依距離由近到遠
  const d = lv.map((i) => i.dist ?? Infinity);
  assert.deepEqual(d, [...d].sort((a, b) => a - b));
  // 有 segments 的列:接起來等於 text、價格是 price 段
  assert.equal(hi!.segments!.map((x) => x.t).join(""), hi!.text);
  assert.ok(hi!.segments!.some((x) => x.kind === "price" && x.t === "1,594"));
});

test("讓位規則:R_HOT5/R_HOT10 → 不列 X_CHG5_UP;R_GAP_FADE → 不列 X_GAP_UP_TODAY;R_SHOOTING → 不列 X_BIG_BLACK", () => {
  const bull = techFacts(techBullSeries(), tech([], [], 2));
  const bear = techFacts(techBearSeries(), tech([], [], 2));
  const s = buildBullBear({
    reasons: [], risks: [], rawReasons: [],
    rawRisks: [{ code: "R_HOT10", text: "10日累漲40%" }, { code: "R_GAP_FADE", text: "開高走低" }, { code: "R_SHOOTING", text: "爆量長上影" }],
    technical: null, derivedFacts: [...bull, ...bear], asOf: LAST,
  });
  const codes = ALL(s).map((i) => i.code);
  for (const c of ["X_CHG5_UP", "X_GAP_UP_TODAY", "X_BIG_BLACK"]) {
    assert.ok(!codes.includes(c), c);
    assert.ok(s.suppressed.includes(c), c);
  }
  assert.ok(codes.includes("X_CHG5_DOWN"));
});

test("鏡像:口袋標籤與風險也會被取代;帶日期/資料日的事實不取代;同一事實鍵只列一次", () => {
  const geo: DerivedFact = { code: "C_GEO_BUY", side: "bull", source: "chips", section: "chips", text: "地緣分點 2 家淨買超", mirrors: ["G1_GEO_BUY"], rank: 4 };
  const s = buildBullBear({
    reasons: [], risks: [], technical: null,
    pocketTags: [{ code: "G1_GEO_BUY", family: "GEO", text: "2 家地緣分點買超" }],
    derivedFacts: [geo, { ...geo }],
    asOf: LAST,
  });
  assert.deepEqual(s.suppressed, ["G1_GEO_BUY"]);
  assert.deepEqual(s.bull.map((i) => i.code), ["C_GEO_BUY"]);
  const lagged = buildBullBear({
    reasons: [], risks: [], technical: null,
    pocketTags: [{ code: "G1_GEO_BUY", family: "GEO", text: "2 家地緣分點買超" }],
    derivedFacts: [{ ...geo, date: "09/30" }],
    asOf: LAST,
  });
  assert.deepEqual(lagged.suppressed, []);
  assert.equal(lagged.bull.length, 2);
});

test("標頭:rank 高者優先;同 rank 比 magnitude;再比段序(壓力 ≤3% → 籌碼 → 技術)", () => {
  const f = (code: string, section: DerivedFact["section"], rank: number, extra: Partial<DerivedFact> = {}): DerivedFact =>
    ({ code, side: "bear", source: section === "chips" ? "inst" : section === "levels" ? "levels" : "tech", section, text: code, rank, ...extra });
  const pick = (facts: DerivedFact[]) => topOfSide(buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: facts, asOf: LAST }), "bear")?.code;
  assert.equal(pick([f("T", "tech", 4), f("C", "chips", 5)]), "C");
  assert.equal(pick([f("C1", "chips", 4, { magnitude: 2 }), f("C2", "chips", 4, { magnitude: 9 })]), "C2");
  assert.equal(pick([f("T", "tech", 5), f("C", "chips", 5), f("L", "levels", 5, { dist: 1.2 })]), "L");
  assert.equal(pick([f("T", "tech", 5), f("L", "levels", 5, { dist: 12 })]), "T");
});

test("分組:技術段 日K/週K/月K;籌碼段依來源,大戶附集保資料日;壓力段不分組;總覽字串", () => {
  const derived = [...techFacts(techBullSeries(), tech([], [], 2)), ...holdersFacts(holdersBull(), undefined, null)];
  const s = buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: derived, asOf: LAST, rawReasons: [{ code: "I_TRUST_BUY", text: "投信買超" }] });
  const labels = (gs: ReturnType<typeof groupColumn>) => gs.filter((g) => !g.keyGroup).map((g) => g.label);
  assert.deepEqual(groupColumn(s.sections.tech.bull, "tech")[0].label, KEY_GROUP_LABEL);
  assert.deepEqual(labels(groupColumn(s.sections.tech.bull, "tech")), [TF_LABEL.D, TF_LABEL.W, TF_LABEL.M]);
  const dd = holdersBull()[0].t;
  // 投信買超(rank 4)進重點;大戶不因此失去集保資料日群組頭
  assert.deepEqual(labels(groupColumn(s.sections.chips.bull, "chips")), [`大戶(集保 ${dd.slice(5, 7)}/${dd.slice(8, 10)})`]);
  assert.deepEqual(groupColumn([], "levels"), []);
  assert.match(overviewText(s, "tech"), /^技術 ▲\d+ ▼\d+$/);
  // 週K 事實出現在日K 之後
  const tfs = s.sections.tech.bull.map((i) => i.tf);
  assert.deepEqual(tfs, [...tfs].sort((a, b) => "DWM".indexOf(a!) - "DWM".indexOf(b!)));
});

// ── 重點(docs/46 §6.6) ──
const SRC: Record<DerivedFact["section"], DerivedFact["source"]> = { tech: "tech", chips: "inst", levels: "levels" };
const fx = (code: string, section: DerivedFact["section"], rank: number, extra: Partial<DerivedFact> = {}): DerivedFact =>
  ({ code, side: "bear", source: SRC[section], section, text: code, rank, ...extra });
const col = (facts: DerivedFact[], section: DerivedFact["section"] = "chips") =>
  buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: facts, asOf: LAST }).sections[section].bear;
const flat = (gs: ReturnType<typeof groupColumn>) => gs.flatMap((g) => g.items.map((i) => i.code));

test("重點:rank ≥4 最多 3 條,從原群組移出(每個 code 全欄恰一次)", () => {
  const items = col([
    fx("A5", "chips", 5, { source: "chips" }), fx("B4", "chips", 4, { source: "margin" }), fx("C4", "chips", 4),
    fx("D4", "chips", 4, { source: "warrant" }), fx("E3", "chips", 3), fx("F2", "chips", 2, { source: "chips" }),
  ]);
  const gs = groupColumn(items, "chips");
  assert.equal(gs[0].label, KEY_GROUP_LABEL);
  assert.ok(gs[0].keyGroup);
  assert.equal(gs[0].items.length, KEY_GROUP_MAX);
  assert.equal(gs.filter((g) => g.keyGroup).length, 1);
  const all = flat(gs);
  assert.equal(all.length, items.length);
  assert.deepEqual(new Set(all), new Set(items.map((i) => i.code)));
  // 第 4 條 rank 4(D4)留在原群組
  assert.ok(gs.slice(1).some((g) => g.items.some((i) => i.code === "D4")));
});

test("重點排序:當日先於滯後 → rank↓ → magnitude↓ → 原順序;沒有 ≥4 時取一條 ≥3;否則沒有", () => {
  const k = (facts: DerivedFact[]) => keyItems(col(facts)).map((i) => i.code);
  assert.deepEqual(k([fx("LAG5", "chips", 5, { date: "09/30" }), fx("T4", "chips", 4)]), ["T4", "LAG5"]);
  assert.deepEqual(k([fx("H4", "chips", 4, { dataDate: "09/26", source: "holders" }), fx("T4", "chips", 4, { magnitude: 1 })]), ["T4", "H4"]);
  assert.deepEqual(k([fx("R4", "chips", 4), fx("R5", "chips", 5)]), ["R5", "R4"]);
  assert.deepEqual(k([fx("M2", "chips", 4, { magnitude: 2 }), fx("M9", "chips", 4, { magnitude: 9 })]), ["M9", "M2"]);
  assert.deepEqual(k([fx("X", "chips", 4), fx("Y", "chips", 4)]), ["X", "Y"]);
  assert.deepEqual(k([fx("S2", "chips", 2), fx("S3a", "chips", 3), fx("S3b", "chips", 3, { magnitude: 5 })]), ["S3b"]);
  assert.deepEqual(k([fx("S2", "chips", 2), fx("S1", "chips", 1)]), []);
  assert.ok(!groupColumn(col([fx("S2", "chips", 2)]), "chips").some((g) => g.keyGroup));
});

test("其餘群組依群組內最高 rank 排序;同 rank 維持固定序(日→週→月、來源序)", () => {
  const top = [fx("K1", "chips", 5, { source: "chips" }), fx("K2", "chips", 5, { source: "chips" }), fx("K3", "chips", 5, { source: "chips" })];
  const chips = groupColumn(col([...top, fx("BR", "chips", 2, { source: "chips" }), fx("MG", "chips", 3, { source: "margin" }), fx("IN", "chips", 3, { source: "inst" })]), "chips");
  assert.deepEqual(chips.map((g) => g.label), [KEY_GROUP_LABEL, SOURCE_LABEL.inst, SOURCE_LABEL.margin, SOURCE_LABEL.chips]);
  const techTop = [5, 5, 5].map((r, i) => fx(`TK${i}`, "tech", r));
  const tech = groupColumn(col([...techTop, fx("D2", "tech", 2, { tf: "D" }), fx("W3", "tech", 3, { tf: "W" }), fx("M2", "tech", 2, { tf: "M" })], "tech"), "tech");
  assert.deepEqual(tech.map((g) => g.label), [KEY_GROUP_LABEL, TF_LABEL.W, TF_LABEL.D, TF_LABEL.M]);
  const tie = groupColumn(col([...techTop, fx("W2", "tech", 2, { tf: "W" }), fx("D2", "tech", 2, { tf: "D" })], "tech"), "tech");
  assert.deepEqual(tie.map((g) => g.label), [KEY_GROUP_LABEL, TF_LABEL.D, TF_LABEL.W]);
  // 群組內 rank↓ → magnitude↓
  const g = groupColumn(col([...top, fx("a", "chips", 2, { source: "margin" }), fx("b", "chips", 3, { source: "margin", magnitude: 1 }), fx("c", "chips", 3, { source: "margin", magnitude: 8 })]), "chips");
  assert.deepEqual(g[1].items.map((i) => i.code), ["c", "b", "a"]);
});

test("壓力段:重點取接近(rank ≥4)者由近到遠,其餘維持由近到遠、不分組", () => {
  const items = col([
    fx("FAR", "levels", 2, { dist: 20 }), fx("N2", "levels", 5, { dist: 2.5 }), fx("MID", "levels", 2, { dist: 8 }),
    fx("N1", "levels", 5, { dist: 0.4 }), fx("MA", "levels", 4, { dist: 1.1 }), fx("ATH", "levels", 1, { dist: 40 }),
  ], "levels");
  const gs = groupColumn(items, "levels");
  assert.deepEqual(gs.map((g) => g.label), [KEY_GROUP_LABEL, null]);
  assert.deepEqual(gs[0].items.map((i) => i.code), ["N1", "N2", "MA"]);
  assert.deepEqual(gs[1].items.map((i) => i.code), ["MID", "FAR", "ATH"]);
});

test("標頭與重點一致:單段時 topOfSide = 該欄重點第一條", () => {
  const facts = [fx("LAG5", "chips", 5, { date: "09/30" }), fx("A4", "chips", 4, { magnitude: 2 }), fx("B4", "chips", 4, { magnitude: 7 })];
  const s = buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: facts, asOf: LAST });
  assert.equal(topOfSide(s, "bear")?.code, groupColumn(s.sections.chips.bear, "chips")[0].items[0].code);
  assert.equal(topOfSide(s, "bear")?.code, "B4");
});

test("rank 表:集保大戶封頂 4;狀態型風險 R_RSI_OVERHEAT/R_MARGIN_HOT 為 3;事件型風險 4、反手賣出 5", () => {
  const s = buildBullBear({
    reasons: [], risks: [], technical: null, asOf: LAST,
    rawRisks: [{ code: "R_RSI_OVERHEAT", text: "RSI" }, { code: "R_MARGIN_HOT", text: "融資" }, { code: "R_SHOOTING", text: "長上影" }, { code: "B_RISK_REVERSAL", text: "反手" }],
  });
  const r = Object.fromEntries(s.bear.map((i) => [i.code, i.rank]));
  assert.deepEqual(r, { R_RSI_OVERHEAT: 3, R_MARGIN_HOT: 3, R_SHOOTING: 4, B_RISK_REVERSAL: 5 });
  assert.ok(holdersFacts(holdersBull(), undefined, null).every((f) => (f.rank ?? 0) <= 4));
});

test("禁用詞鎖:標籤、定義句、欄頭、F 句", () => {
  const texts = [
    PANEL_TITLE, SIDE_DEFINITION, COUNT_NOTE, CONTEXT_LABEL, KEY_GROUP_LABEL, ...Object.values(EMPTY_SIDE), ...Object.values(EMPTY_TECH_WITH_LEVELS), ...Object.values(SIDE_LABEL),
    ...Object.values(SOURCE_LABEL), ...Object.values(SECTION_LABEL), ...Object.values(TF_LABEL),
    ...Object.values(COLUMN_LABEL).flatMap((x) => Object.values(x)),
    ...priceLevelFacts(pl(), "2026-10-03", 60).map((f) => f.text),
    ...priceLevelFacts(pl({ ma_align: "bear", new_low_20: true, new_high_20: false, vol_price_2d: "down" }), "2026-10-03", 30).map((f) => f.text),
  ];
  for (const t of texts) for (const w of BANNED) assert.ok(!t.includes(w), `「${t}」含禁用詞`);
});

test("融資堆積且同期分點集中(docs/46 §7):C_MARGIN_HOT 仍空方、取代 R_MARGIN_HOT,但 rank 2 → 不進重點、不當標頭;每 code 恰一次", () => {
  const run = (f: ReturnType<typeof marginConcBuildup>) => {
    const data = { id: "2476", name: "樣本", market: "twse", technical: null, scores: null, reasons: [], risks: [], branches: [], warrant: null, warrant_history: [], active_warrants: [], ...f.data, candles: f.candles } as unknown as StockJson;
    return buildBullBear({
      reasons: [], risks: [], rawReasons: [],
      rawRisks: [{ code: "R_MARGIN_HOT", points: 5, text: "融資使用率過高" }, { code: "R_RSI_OVERHEAT", points: 5, text: "RSI過熱" }],
      technical: null, derivedFacts: deriveAllFacts(data, LAST), asOf: LAST,
    });
  };
  const s = run(marginConcBuildup());
  const hot = s.sections.chips.bear.find((i) => i.code === "C_MARGIN_HOT")!;
  assert.equal(hot.rank, 2);
  assert.ok(s.suppressed.includes("R_MARGIN_HOT"));
  assert.ok(!keyItems(s.sections.chips.bear).some((i) => i.code === "C_MARGIN_HOT"));
  assert.notEqual(topOfSide(s, "bear")?.code, "C_MARGIN_HOT");
  const ctx = s.sections.chips.context.map((i) => i.code);
  assert.ok(ctx.includes("C_MARGIN_UP_CONC") && ctx.includes("C_MARGIN_BUILDUP_CONC"), ctx.join(","));
  // 後端 code 恰一次(列出或被取代);事實鍵(code+週期)不重複
  const backend = [...ALL(s).map((i) => i.code), ...s.suppressed].filter((c): c is string => !!c && !(c in FACT_CATALOGUE));
  assert.deepEqual(backend.sort(), ["R_MARGIN_HOT", "R_RSI_OVERHEAT"]);
  const keys = ALL(s).map((i) => i.key);
  assert.equal(keys.length, new Set(keys).size, "有事實重複");
  assert.equal(ALL(s).filter((i) => i.code === "C_MARGIN_HOT").length, 1);
  // 集保大戶減(2236 型)→ 沒有集中事實,C_MARGIN_HOT 維持 rank 3
  const t = run(marginConcTdccDown());
  assert.equal(t.sections.chips.bear.find((i) => i.code === "C_MARGIN_HOT")?.rank, 3);
  assert.ok(!ALL(t).some((i) => i.code?.startsWith("C_MARGIN_UP_") || i.code === "C_MARGIN_BUILDUP_CONC"));
});
// ── 技術段與壓力分析一致(使用者:「技術分析有時候會沒有空方理由 但是在壓力分析又有」) ──
const summaryOf = (data: StockJson) =>
  buildBullBear({ reasons: [], risks: [], rawReasons: [], rawRisks: [], technical: null, derivedFacts: deriveAllFacts(data, LAST), asOf: LAST });

test("1342 型:壓力段有 ≤3% 的上方密集區 → 技術段空方不再空白,點名同一個價位", () => {
  const data = nearResistanceStock();
  const s = summaryOf(data);
  assert.ok(s.sections.levels.bear.some((i) => i.code === "L_DENSE_ABOVE" && i.rank === 5), "壓力段照舊有接近的密集區");
  assert.deepEqual(s.sections.tech.bear.map((i) => i.text), ["上方 3% 內有壓力價位:成交最密集區 116.5–117.7(貼近現價)"]);
  assert.equal(s.sections.levels.bear.find((i) => i.code === "L_DENSE_ABOVE")?.text, "成交最密集區 116.5–117.7 自現價向上(佔近120日成交 2.8%)");
  assert.deepEqual(s.sections.tech.bull.map((i) => i.text), ["下方 3% 內有支撐價位:5日線 115.0(−1.3%)"]);
  // 技術段只有 rank 3 的那一句時,它就是該欄重點
  assert.equal(keyItems(s.sections.tech.bear)[0].code, "X_LEVEL_ABOVE_NEAR");
  // 標頭仍是壓力段那條(rank 5),不被技術段的對應句搶走
  assert.equal(topOfSide(s, "bear")?.code, "L_DENSE_ABOVE");
});

test("不變式:壓力段或價格階梯有 ≤3% 的價位,技術段同側一定有對應句;沒有時技術段空欄說明原因", () => {
  const cases = [
    nearResistanceStock(),
    nearResistanceStock({ dense_above: { lo: 122.3, hi: 123.5, share: 0.03 } }),
    nearResistanceStock({ dense_above: { lo: 116.5, hi: 117.7, share: 0.001 } }),
    nearResistanceStock({ ma: { "5": 117, "10": 113.4 }, dense_above: null }),
    nearResistanceStock({ highs: { "20": { p: 119.9, t: "2026-09-20" } }, dense_above: null }),
    { ...nearResistanceStock(), price_levels: okLevels() } as StockJson,
  ];
  for (const data of cases) {
    const s = summaryOf(data);
    const v = priceLevelsView(data.price_levels);
    assert.equal(v.state, "ok");
    if (v.state !== "ok") continue;
    for (const [side, rows, code] of [["bear", v.above, "X_LEVEL_ABOVE_NEAR"], ["bull", v.below, "X_LEVEL_BELOW_NEAR"]] as const) {
      const nearLevels = s.sections.levels[side].some((i) => i.dist != null && isNear(i.dist));
      const nearLadder = rows.some((r) => isNear(r.dist));
      const has = s.sections.tech[side].some((i) => i.code === code);
      assert.equal(has, nearLevels || nearLadder, `${side} ${JSON.stringify(data.price_levels)}`);
    }
  }
  // 遠距(+5.0%)的密集區:技術段空方空欄改說明「上方 3% 內沒有壓力價位」;籌碼段照舊
  const far = summaryOf(nearResistanceStock({ dense_above: { lo: 122.3, hi: 123.5, share: 0.03 } }));
  assert.equal(far.sections.tech.bear.length, 0);
  assert.ok(far.sections.levels.bear.length > 0);
  assert.equal(emptySideText(far, "tech", "bear"), EMPTY_TECH_WITH_LEVELS.bear);
  assert.equal(emptySideText(far, "chips", "bear"), EMPTY_SIDE.bear);
  assert.equal(emptySideText(far, "levels", "bear"), EMPTY_SIDE.bear);
  // 壓力段也空時不提壓力
  const none = buildBullBear({ reasons: [], risks: [], technical: null, asOf: LAST });
  assert.equal(emptySideText(none, "tech", "bear"), EMPTY_SIDE.bear);
});

test("多方榜不受影響:技術段對應句 rank 3,不進 K_bull/K_bear(rank ≥4)也不觸發排除(rank 5)", () => {
  for (const data of [nearResistanceStock(), { ...nearResistanceStock(), price_levels: okLevels() } as StockJson]) {
    const all = deriveAllFacts(data, LAST);
    const without = all.filter((f) => !f.code.startsWith("X_LEVEL_"));
    assert.ok(all.length > without.length);
    const k = (facts: DerivedFact[]) => {
      const bk = boardKeys(buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: facts, asOf: LAST }));
      return { bull: bk.bull.map((i) => i.key), bear: bk.bear.map((i) => i.key), excl: bk.excl.map((i) => i.key) };
    };
    assert.deepEqual(k(all), k(without));
  }
});

test("多方榜不受影響(docs/45 P2):連續天數 F11 rank 2、缺口在壓力段 → K_bull/K_bear/排除與沒有這些鍵時相同", () => {
  const k = (data: StockJson) => {
    const bk = boardKeys(buildBullBear({ reasons: [], risks: [], technical: null, derivedFacts: deriveAllFacts(data, LAST), asOf: LAST }));
    return { bull: bk.bull.map((i) => i.key), bear: bk.bear.map((i) => i.key), excl: bk.excl.map((i) => i.key) };
  };
  const base = nearResistanceStock();
  const p2 = (over: Partial<Extract<PriceLevels, { status: "ok" }>>) => ({ ...base, price_levels: { ...base.price_levels, ...over } } as StockJson);
  const cases = [
    p2({ ma20_streak: { n: 15, side: "above", capped: false } }),
    p2({ ma20_streak: { n: 221, side: "below", capped: true } }),
    // 3% 內的缺口:壓力段 rank 4,但壓力段不進 K 鍵;技術段只多一句 rank 3 的 3% 內句
    p2({ gaps_above: [{ lo: 117, hi: 118, t: "2026-09-10" }], gaps_below: [{ lo: 114, hi: 115.5, t: "2026-09-20" }] }),
    p2({ ma20_streak: { n: 5, side: "below", capped: false }, gaps_above: [{ lo: 117, hi: 118, t: "2026-09-10" }], gaps_below: [] }),
  ];
  for (const data of cases) {
    const facts = deriveAllFacts(data, LAST);
    assert.ok(facts.some((f) => f.code.startsWith("F11") || f.code.startsWith("L_GAP")), "新事實有產生");
    assert.deepEqual(k(data), k(base));
  }
});