// 執行: node --test --experimental-strip-types web/lib/instiGroupFlow.test.ts
//
// 首頁「法人族群」(docs/49 MVP):句子、格式、集中於 X 的 70% 門檻、拆兩邊、空/partial/stale 文案、禁詞。
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CONCENTRATION_RATIO,
  IDENTITIES,
  IDENTITY_LABEL,
  INSTI_EMPTY,
  INSTI_NO_GROUPS,
  INSTI_OTHER_LABEL,
  INSTI_TAB_HINT,
  INSTI_TAB_LABEL,
  MODE_LABEL,
  barRatio,
  clsStaleText,
  concentratedIn,
  concentrationText,
  countFull,
  countShort,
  dateLine,
  definitionText,
  fmtAmt,
  fmtAmtEst,
  fmtNetLots,
  marketLine,
  memberHref,
  missingText,
  mmdd,
  moreText,
  partialText,
  splitSides,
  staleText,
} from "./instiGroupFlow.ts";
import type { InstiFlowGroup, InstiFlowJson, InstiFlowMember } from "./types.ts";

function member(id: string, net_lots: number, amt_est: number): InstiFlowMember {
  return { id, name: `股${id}`, market: "twse", net_lots, amt_est, chg_pct: 1.2 };
}

function group(name: string, amt_est: number, over: Partial<InstiFlowGroup> = {}): InstiFlowGroup {
  return { name, n: 10, buy_n: 6, sell_n: 3, net_lots: Math.round(amt_est / 1e5), amt_est, buy_top: [], sell_top: [], ...over };
}

function payload(over: Partial<InstiFlowJson> = {}): InstiFlowJson {
  const m = { net_lots: 45210, amt_est: 12_030_000_000 };
  const empty = { foreign: [], trust: [], dealer: [], total: [] };
  return {
    version: 1, window: 1, days_actual: 1, as_of: "2026-10-07", data_date: "2026-10-07",
    generated_at: "2026-10-07T21:00:00+08:00", stale: false,
    coverage: { twse: 980, tpex: 790, partial: false }, amt_missing_n: 0,
    market: { foreign: m, trust: m, dealer: m, total: m },
    groups: { industry: empty, theme: empty },
    ...over,
  };
}

test("分頁名與身分/模式標籤", () => {
  assert.equal(INSTI_TAB_LABEL, "法人族群");
  assert.deepEqual(IDENTITIES.map((k) => IDENTITY_LABEL[k]), ["外資", "投信", "自營", "合計"]);
  assert.deepEqual([MODE_LABEL.industry, MODE_LABEL.theme], ["產業", "題材"]);
});

test("定義句:身分、估算、題材重疊、自營口徑", () => {
  assert.equal(definitionText("foreign", "industry"), "族群內成分股的外資買賣超張數相加;金額＝張數×當日收盤(估)。只整理資料,不下判斷。");
  assert.match(definitionText("trust", "theme"), /投信.*題材成分重疊,只供組間比較。/);
  assert.match(definitionText("dealer", "industry"), /自營＝自行買賣＋避險合計/);
  assert.match(definitionText("total", "industry"), /三大法人合計/);
});

test("格式:金額帶估、張數帶正負號", () => {
  assert.equal(fmtAmtEst(3_820_000_000), "+38.2億(估)");
  assert.equal(fmtAmtEst(-2_240_000_000), "-22.4億(估)");
  assert.equal(fmtAmt(32_000_000), "+3,200萬");
  assert.equal(fmtAmt(-15_000_000), "-1,500萬");
  assert.equal(fmtAmt(1_000), "0萬");
  assert.equal(fmtNetLots(12480), "+12,480張");
  assert.equal(fmtNetLots(-8310), "-8,310張");
  assert.equal(fmtNetLots(0), "0張");
  assert.equal(mmdd("2026-10-07"), "10/07");
  assert.equal(mmdd(null), "—");
});

test("資料日、全市場、計數", () => {
  assert.equal(dateLine(payload({ as_of: "2026-10-06" })), "法人 10/06 · 收盤 10/07");
  assert.equal(marketLine(payload(), "foreign"), "外資全市場 +45,210張 · +120.3億(估)");
  const partial = payload({ coverage: { twse: 980, tpex: 0, partial: true } });
  assert.equal(marketLine(partial, "trust"), "投信已到齊市場 +45,210張 · +120.3億(估)");
  assert.equal(countShort({ buy_n: 18, sell_n: 6 }), "18買/6賣");
  assert.equal(countFull({ buy_n: 18, sell_n: 6, n: 42 }), "買超 18 檔/賣超 6 檔/有資料 42 檔");
});

test("partial / stale / 缺收盤 / 分類過期 文案", () => {
  assert.equal(partialText(payload()), null);
  assert.equal(partialText(payload({ coverage: { twse: 980, tpex: 0, partial: true } })), "上櫃法人尚未到齊,目前只有上市。");
  assert.equal(partialText(payload({ coverage: { twse: 0, tpex: 790, partial: true } })), "上市法人尚未到齊,目前只有上櫃。");
  assert.equal(staleText(payload()), null);
  assert.equal(staleText(payload({ as_of: "2026-10-06", stale: true })), "法人資料為 10/06,今日法人 16:00 起輪詢,到齊後更新。");
  assert.equal(missingText(0), null);
  assert.equal(missingText(undefined), null);
  assert.equal(missingText(2), "2 檔無當日收盤,金額未計");
  assert.equal(clsStaleText("2026-09-01"), "分類 09/01");
  assert.equal(clsStaleText(undefined), null);
  assert.equal(moreText(12, 10), "顯示前 10 組,共 12 組");
  assert.equal(moreText(8, 8), null);
});

test("集中於 X:同方向第一檔 ≥ 70%", () => {
  assert.equal(CONCENTRATION_RATIO, 0.7);
  const at = group("半導體", 1000, { buy_top: [member("2330", 10, 700)] });
  assert.equal(concentratedIn(at), "股2330");
  assert.equal(concentrationText(at), "集中於 股2330");
  assert.equal(concentratedIn(group("半導體", 1000, { buy_top: [member("2330", 10, 699)] })), null);
  // 賣超組看 sell_top[0]
  assert.equal(concentratedIn(group("金融", -1000, { sell_top: [member("2881", -10, -800)] })), "股2881");
  assert.equal(concentratedIn(group("金融", -1000, { buy_top: [member("2881", 10, 900)] })), null);
  assert.equal(concentratedIn(group("零", 0, { buy_top: [member("1", 1, 1)] })), null);
});

test("拆兩邊:買超照檔內順序,賣超最負在前,同分看張數再看名稱", () => {
  const groups = [group("甲", 300), group("乙", 100), group("丙", 0), group("丁", -50),
    group("戊", -200, { net_lots: -5 }), group("己", -200, { net_lots: -9 }), group("庚", -200, { net_lots: -9 })];
  const { buy, sell } = splitSides(groups);
  assert.deepEqual(buy.map((g) => g.name), ["甲", "乙"]);
  // 己(U+5DF1) < 庚(U+5E9A):同金額同張數看 codepoint
  assert.deepEqual(sell.map((g) => g.name), ["己", "庚", "戊", "丁"]);
});

test("條長與連結", () => {
  assert.equal(barRatio(50, 100), 0.5);
  assert.equal(barRatio(-1, 100), 0.06);
  assert.equal(barRatio(5, 0), 0.06);
  assert.equal(memberHref("2330"), "/stock?id=2330#insti");
});

test("禁詞:分頁名、說明、定義句、狀態句", () => {
  // 用字碼組字,避免本測試檔自己被 test_label_honesty 掃到。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const bannedWords = [
    word(0x52dd, 0x7387), // 勝率
    word(0x7372, 0x5229), // 獲利
    word(0x5831, 0x916c), // 報酬
    word(0x95dc, 0x9375, 0x5206, 0x9ede), // 關鍵分點
    word(0x5927, 0x6f32), // 大漲
    word(0x5674), // 噴
    word(0x6975, 0x54c1), // 極品
    word(0x6a5f, 0x7387), // 機率
    word(0x76ee, 0x6a19, 0x50f9), // 目標價
    word(0x8cb7, 0x9032), // 買進
    word(0x8ce3, 0x51fa), // 賣出
    word(0x770b, 0x591a), // 看多
    word(0x770b, 0x7a7a), // 看空
    word(0x5c07, 0x6703), // 將會
    word(0x6709, 0x6548, 0x652f, 0x6490), // 有效支撐
    word(0x58d3, 0x529b, 0x6c89, 0x91cd), // 壓力沉重
    word(0x505a, 0x591a), // 做多
    word(0x505a, 0x7a7a), // 做空
    word(0x5efa, 0x8b70), // 建議
    word(0x558a, 0x55ae), // 喊單
  ];
  const banned = new RegExp(bannedWords.join("|"));
  const p = payload({ as_of: "2026-10-06", stale: true, coverage: { twse: 1, tpex: 0, partial: true } });
  const g = group("半導體", 1000, { buy_top: [member("2330", 10, 900)], cls_date: "2026-09-01" });
  const texts = [
    INSTI_TAB_LABEL, INSTI_TAB_HINT, INSTI_EMPTY, INSTI_NO_GROUPS, INSTI_OTHER_LABEL,
    ...IDENTITIES.flatMap((k) => [IDENTITY_LABEL[k], definitionText(k, "industry"), definitionText(k, "theme"), marketLine(p, k)]),
    dateLine(p), staleText(p)!, partialText(p)!, countShort(g), countFull(g), concentrationText(g)!,
    clsStaleText(g.cls_date)!, missingText(3)!, moreText(20, 10)!,
  ];
  for (const t of texts) assert.ok(!banned.test(t), t);
  assert.ok(banned.test(word(0x505a, 0x591a)), "regex 本身有效");
  // 買超/賣超 是允許的
  assert.ok(!banned.test(countFull(g)));
  assert.match(countFull(g), /買超/);
});
