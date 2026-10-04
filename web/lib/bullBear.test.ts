// 執行: node --test --experimental-strip-types web/lib/bullBear.test.ts
//
// 多空摘要(docs/46):分類、去重、舊 JSON 相容、每個 code 恰一次、禁用詞鎖。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  COUNT_NOTE,
  EMPTY_SIDE,
  PANEL_TITLE,
  RISK_TEXT_KEYS,
  SIDE_BY_CODE,
  SIDE_DEFINITION,
  SIDE_LABEL,
  SOURCE_LABEL,
  SOURCE_ORDER,
  buildBullBear,
  moreText,
  riskCodeFromText,
  techDetailsSummary,
  topOfSide,
  type BullBearSummary,
} from "./bullBear.ts";
import { priceLevelFacts } from "./priceLevels.ts";
import type { PriceLevels, ReasonItem, TechnicalSummary } from "./types.ts";

// 以「·」拆開或用字碼組回,避免這個檔案本身被 test_label_honesty 掃到。
const BANNED = [
  "勝·率", "獲·利", "報·酬", "關鍵·分點", "大·漲", "極·品", "機·率", "目標·價", "買·進", "賣·出",
  "看·多", "看·空", "將·會", "有效·支撐", "壓力·沉重", "做·多", "做·空", "建·議", "喊·單",
].map((w) => w.replace("·", "")).concat(String.fromCharCode(0x5674));

const tech = (reasons: ReasonItem[], risks: ReasonItem[] = []): TechnicalSummary => ({
  score: 40, ma20: 100, ma60: 90, rsi14: 60, volume_ratio: 1.2, reasons, risks,
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

test("分類表:每個 code 的側別與來源都有效", () => {
  for (const [code, v] of Object.entries(SIDE_BY_CODE)) {
    assert.ok(["bull", "bear", "context"].includes(v.side), code);
    assert.ok(SOURCE_ORDER.includes(v.source), code);
  }
  assert.equal(SIDE_BY_CODE.S4_COMPRESSION_SETUP_V2.side, "context");
  assert.equal(SIDE_BY_CODE.S4_VOLATILITY_CONTRACTION.side, "context");
  assert.equal(SIDE_BY_CODE.G2_GEO_SELL.side, "bear");
  assert.equal(SIDE_BY_CODE.KB1_BUYBACK_WINDOW.side, "context");
  assert.equal(SIDE_BY_CODE.K1_KEY_BUY.side, "bull");
  for (const [, code] of RISK_TEXT_KEYS) assert.equal(SIDE_BY_CODE[code].side, "bear");
});

test("技術理由在 raw_reasons 與 technical.reasons 都有 → 只出現一次", () => {
  const t1 = { code: "T1_BULL_MA", points: 15, text: "5/10/20日均線多頭排列" };
  const s = buildBullBear({
    rawReasons: [{ code: "B1_BRANCH_STREAK", points: 20, text: "分點【美林】連4日買超" }, t1],
    reasons: [], risks: [], rawRisks: [],
    technical: tech([t1, { code: "T1_MA20", points: 10, text: "收盤站上20日線" }]),
    asOf: "2026-10-03",
  });
  assert.deepEqual(s.bull.map((i) => i.code), ["B1_BRANCH_STREAK", "T1_BULL_MA", "T1_MA20"]);
  assert.deepEqual(s.suppressed, []);
});

test("價格位置事實同方向同一天 → 取代技術理由,記入 suppressed", () => {
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
  assert.deepEqual(s.bull.map((i) => i.text), [
    "60日箱型整理且收盤接近區間上緣",
    "站上 5/10/20/60 日線",
    "5/10/20日均線多頭排列",
    "收盤創20日新高",
    "RSI14 60,位於 50–70",
  ]);
  assert.deepEqual(s.bear.map((i) => i.text), ["120/240 日線在上方"]);
  // as_of 落後資料日 → 帶日期、不取代
  const stale = buildBullBear({
    rawReasons: [{ code: "T1_BULL_MA", points: 15, text: "5/10/20日均線多頭排列" }],
    reasons: [], risks: [], technical: null,
    priceFacts: priceLevelFacts(pl(), "2026-10-06"), asOf: "2026-10-06",
  });
  assert.deepEqual(stale.suppressed, []);
  assert.ok(stale.bull.some((i) => i.code === "T1_BULL_MA"));
  assert.ok(stale.bull.filter((i) => i.source === "price").every((i) => i.date === "10/03"));
});

test("R_RSI_OVERHEAT 兩個來源只出現一次(取 raw_risks 那句)", () => {
  const s = buildBullBear({
    rawReasons: [], reasons: [],
    rawRisks: [{ code: "R_RSI_OVERHEAT", points: 5, text: "RSI14超過80,短線過熱" }],
    risks: ["RSI14超過80,短線過熱"],
    technical: tech([], [{ code: "R_RSI_OVERHEAT", text: "RSI14超過80,短線動能過熱" }]),
    asOf: "2026-10-03",
  });
  assert.deepEqual(s.bear.map((i) => [i.code, i.text, i.risk, i.source]), [["R_RSI_OVERHEAT", "RSI14超過80,短線過熱", true, "tech"]]);
});

test("舊 JSON:沒有 raw_reasons/raw_risks → 用字串;風險字串回推 code,未知歸空方/其他", () => {
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
  assert.deepEqual(s.bull.map((i) => [i.code, i.source]), [[null, "other"]]);
  assert.deepEqual(s.bear.map((i) => [i.code, i.source]), [["R_FOREIGN_SELL5", "inst"], [null, "other"]]);
});

test("口袋標籤、背景、來源排序與同來源依 points", () => {
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
  assert.deepEqual(s.context.map((i) => i.code), ["S4_COMPRESSION_SETUP_V2", "KB1_BUYBACK_WINDOW"]);
  assert.equal(topOfSide(s, "bull")?.code, "B1_BRANCH_STREAK");
  assert.equal(topOfSide(s, "bear")?.code, "B_RISK_REVERSAL");
  assert.equal(topOfSide(buildBullBear({ reasons: [], risks: [], technical: null, asOf: "x" }), "bull"), null);
});

test("每個輸入 code 在 bull ∪ bear ∪ context ∪ suppressed 恰出現一次", () => {
  const codes = Object.keys(SIDE_BY_CODE);
  const reasons = codes.filter((c) => !c.startsWith("R_") && c !== "B_RISK_REVERSAL" && !/^(G\d|K1_|T1_TRACKED|H1_|KB)/.test(c))
    .map((code, i) => ({ code, points: i % 7, text: `理由${code}` }));
  const risks = codes.filter((c) => c.startsWith("R_") || c === "B_RISK_REVERSAL").map((code) => ({ code, points: 5, text: `風險${code}` }));
  const pockets = codes.filter((c) => /^(G\d|K1_|T1_TRACKED|H1_|KB)/.test(c)).map((code) => ({ code, family: "GEO" as const, text: `口袋${code}` }));
  const half = Math.floor(reasons.length / 2);
  const s = buildBullBear({
    rawReasons: reasons.slice(0, half + 3), reasons: [],
    rawRisks: risks, risks: [],
    technical: tech(reasons.slice(half), risks.slice(0, 2)),
    pocketTags: pockets,
    priceFacts: priceLevelFacts(pl({ vol_price_2d: "up" }), "2026-10-03", 60),
    asOf: "2026-10-03",
  });
  const seen = [...ALL(s).map((i) => i.code), ...s.suppressed].filter((c) => c && !c.startsWith("F"));
  assert.equal(seen.length, new Set(seen).size, "有 code 重複");
  assert.deepEqual(new Set(seen), new Set(codes));
  assert.ok(s.suppressed.length > 0);
});

test("禁用詞鎖:標籤、定義句、F 句", () => {
  const texts = [
    PANEL_TITLE, SIDE_DEFINITION, COUNT_NOTE, ...Object.values(EMPTY_SIDE), ...Object.values(SIDE_LABEL),
    ...Object.values(SOURCE_LABEL), moreText(3), techDetailsSummary(4, 1),
    ...priceLevelFacts(pl(), "2026-10-03", 60).map((f) => f.text),
    ...priceLevelFacts(pl({ ma_align: "bear", new_low_20: true, new_high_20: false, vol_price_2d: "down" }), "2026-10-03", 30).map((f) => f.text),
  ];
  for (const t of texts) for (const w of BANNED) assert.ok(!t.includes(w), `「${t}」含禁用詞`);
});
