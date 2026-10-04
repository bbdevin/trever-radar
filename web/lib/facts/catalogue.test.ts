// 執行: node --test --experimental-strip-types web/lib/facts/catalogue.test.ts
//
// 事實目錄(docs/46 v2 §2、§4):每一個 code 都有 fixture 產生它;分類與目錄一致;segments 接起來等於 text;
// mirrors 只用目錄宣告過的;禁用詞鎖;deriveAllFacts 對全缺鍵的舊 JSON 不丟例外。
import assert from "node:assert/strict";
import { test } from "node:test";

import type { DerivedFact } from "../bullBear.ts";
import { priceLevelFacts } from "../priceLevels.ts";
import type { StockJson } from "../types.ts";
import { branchFacts } from "./branchFacts.ts";
import { FACT_CATALOGUE } from "./catalogue.ts";
import {
  DIRECTORS_PLEDGED, LAST, branchMonth, branchWeek, holdersBear, holdersBull, insti20d, instiBothBuy, instiBothSell,
  instiSellStreak, levelSeries, marginHotUp, marginOkDown, okLevels, techBearSeries, techBullSeries, techQuietSeries,
} from "./fixtures.ts";
import { holdersFacts } from "./holdersFacts.ts";
import { STOCK_KEYS_NOT_FACTS, STOCK_KEYS_USED, deriveAllFacts } from "./index.ts";
import { instFacts } from "./instFacts.ts";
import { levelFacts } from "./levelFacts.ts";
import { marginFacts } from "./marginFacts.ts";
import { futuresFacts, themeFacts, warrantFacts } from "./otherFacts.ts";
import { techFacts } from "./techFacts.ts";

// 以「·」拆開或用字碼組回,避免這個檔案本身被 test_label_honesty 掃到。
const BANNED = [
  "勝·率", "獲·利", "報·酬", "關鍵·分點", "大·漲", "極·品", "機·率", "目標·價", "買·進", "賣·出",
  "看·多", "看·空", "將·會", "有效·支撐", "壓力·沉重", "做·多", "做·空", "建·議", "喊·單", "軋·空", "保·證", "賺·錢", "盈·利",
].map((w) => w.replace("·", "")).concat(String.fromCharCode(0x5674));

const tech = (volume_ratio: number | null) => ({ score: 0, ma20: null, ma60: null, rsi14: null, volume_ratio, reasons: [], risks: [] });

function everyFixtureFact(): DerivedFact[] {
  const out: DerivedFact[] = [];
  out.push(...techFacts(techBullSeries(), tech(2.3)), ...techFacts(techBearSeries(), tech(2)), ...techFacts(techQuietSeries(), tech(null)));
  out.push(...priceLevelFacts(okLevels(), LAST, 60));
  out.push(...priceLevelFacts(okLevels({
    ma_align: "bear", new_high_20: false, new_low_20: false, vol_price_2d: "down",
    highs: { "60": { p: 1100, t: LAST } }, lows: { "20": { p: 1000, t: LAST } },
  }), LAST, 40));
  out.push(...priceLevelFacts(okLevels({ new_high_20: false, new_low_20: true }), LAST, 75));
  out.push(...levelFacts(okLevels(), levelSeries(), LAST));
  out.push(...levelFacts(okLevels({ highs: { "60": { p: 1090, t: "2026-09-30" } } }), levelSeries(), LAST));
  out.push(...levelFacts(okLevels({ lows: { "60": { p: 1080, t: "2026-09-30" } } }), levelSeries(), LAST));
  for (const f of [instiSellStreak(), instiBothBuy(), instiBothSell(), insti20d(), insti20d(true)]) out.push(...instFacts(f.ih, f.candles, LAST));
  for (const f of [marginHotUp(), marginOkDown()]) out.push(...marginFacts(f.mh, f.adjusted, LAST));
  for (const f of [branchMonth(), branchWeek()]) out.push(...branchFacts(f, f.candles, LAST, new Set()));
  out.push(...holdersFacts(holdersBull(), { display_from: "", display_to: "", db_earliest: null, insider_as_of_ym: "2026-08" }, DIRECTORS_PLEDGED));
  out.push(...holdersFacts(holdersBear(), undefined, null));
  out.push(...warrantFacts(
    { call_turnover: 5e6, call_volume: 0, call_count: 1, put_turnover: 6.5e6, put_volume: 0, put_count: 1, call_avg20: null, call_turnover_ratio: null, put_call_ratio: 1.3 },
    [...Array.from({ length: 20 }, (_, i) => ({ t: `2026-09-${String(i + 1).padStart(2, "0")}`, call_turnover: 0, put_turnover: 1e6, call_count: 0, put_count: 1 })),
      { t: LAST, call_turnover: 0, put_turnover: 8e6, call_count: 0, put_count: 1 }],
    LAST,
  ));
  out.push(...futuresFacts({
    version: 1, list_as_of: LAST, daily_as_of: LAST,
    contracts: [{ code: "XYZ", multiplier: 2000, is_futures: true, is_option: false, is_weekly_option: false, anomaly: { today: 5000, window_max: 3000, window_median: 1000, window_days: 60 } }],
  }, "2330"));
  out.push(...themeFacts(
    [
      { id: "1", name: "熱", status: "active", data_date: null, heat_date: LAST, vs20: 2, avg_chg: 1, turnover: 1, up: 1, down: 0, eligible: true },
      { id: "2", name: "冷", status: "active", data_date: null, heat_date: LAST, vs20: 0.5, avg_chg: 0, turnover: 1, up: 0, down: 1, eligible: true },
    ],
    { plan_id: "p", stock_id: "2330", name: "x", market: "twse", board_date: null, purpose: null, total_amount_limit: null, planned_shares: null, price_min: null, price_max: null,
      start_date: "2026-09-01", end_date: "2026-10-31", completed_flag: null, status: "in_progress", executed_shares: null, transferred_shares: null, execution_pct: null, executed_amount: null,
      avg_price: null, share_ratio_pct: null, incomplete_reason: null, report_date: null, source_updated_at: null, source: "mops" },
    LAST,
  ));
  return out;
}

test("目錄覆蓋率:每一個 code 都有 fixture 產生", () => {
  const produced = new Set(everyFixtureFact().map((f) => f.code));
  const missing = Object.keys(FACT_CATALOGUE).filter((c) => !produced.has(c));
  assert.deepEqual(missing, []);
});

test("每條事實:分類與目錄一致、週期在目錄允許的範圍、segments 接起來等於 text、mirrors ⊆ 目錄", () => {
  for (const f of everyFixtureFact()) {
    const cat = FACT_CATALOGUE[f.code];
    assert.ok(cat, f.code);
    assert.equal(f.side, cat.side, f.code);
    assert.equal(f.section, cat.section, f.code);
    assert.equal(f.source, cat.source, f.code);
    assert.ok(cat.tfs.includes(f.tf ?? "D"), `${f.code} tf ${f.tf}`);
    assert.ok(f.segments && f.segments.length > 0, f.code);
    assert.equal(f.segments!.map((s) => s.t).join(""), f.text, f.code);
    for (const m of f.mirrors ?? []) assert.ok(cat.mirrors?.includes(m), `${f.code} mirrors ${m} 未在目錄宣告`);
    assert.ok(f.rank == null || (f.rank >= 1 && f.rank <= 5), f.code);
  }
});

test("禁用詞鎖:所有事實句", () => {
  for (const f of everyFixtureFact()) for (const w of BANNED) assert.ok(!f.text.includes(w), `「${f.text}」含禁用詞`);
});

test("deriveAllFacts:舊 JSON 全缺鍵不丟例外;鍵清單互斥", () => {
  const legacy = { id: "1234", name: "舊", market: "twse", candles: [], scores: null, reasons: [], risks: [], technical: null, branches: [], warrant: null, warrant_history: [], active_warrants: [] } as unknown as StockJson;
  assert.deepEqual(deriveAllFacts(legacy, ""), []);
  const both = STOCK_KEYS_USED.filter((k) => (STOCK_KEYS_NOT_FACTS as readonly string[]).includes(k));
  assert.deepEqual(both, []);
});
