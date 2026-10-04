// 執行: node --test --experimental-strip-types web/lib/facts/chipsFacts.test.ts
//
// 籌碼段(docs/46 v2 §2.3–2.5、2.7):法人、資券、分點、權證、期貨、題材、公司。
import assert from "node:assert/strict";
import { test } from "node:test";

import type { DerivedFact } from "../bullBear.ts";
import { branchFacts } from "./branchFacts.ts";
import { LAST, branchMonth, branchWeek, insti20d, instiBothBuy, instiBothSell, instiSellStreak, marginHotUp, marginOkDown } from "./fixtures.ts";
import { instFacts } from "./instFacts.ts";
import { marginFacts } from "./marginFacts.ts";
import { futuresFacts, themeFacts, warrantFacts } from "./otherFacts.ts";

const byCode = (fs: DerivedFact[]) => new Map(fs.map((f) => [f.code, f]));

test("法人:外資連 5 日賣超(取代 R_FOREIGN_SELL5、rank 5)、投信買超、三大法人合計", () => {
  const { ih, candles } = instiSellStreak();
  const m = byCode(instFacts(ih, candles, LAST));
  const fs = m.get("C_FOREIGN_SELL")!;
  assert.equal(fs.text, "外資賣超 2,245 張(佔量 9.2%),連 5 日累計 −11,245 張");
  assert.deepEqual(fs.mirrors, ["R_FOREIGN_SELL5"]);
  assert.equal(fs.rank, 5);
  assert.equal(m.get("C_TRUST_BUY")?.text, "投信買超 983 張(佔量 4.0%),連 25 日累計 +1,223 張");
  assert.deepEqual(m.get("C_TRUST_BUY")?.mirrors, ["I_TRUST_BUY", "I_TRUST_STREAK"]);
  assert.equal(m.get("C_NET_SHARE_SELL")?.text, "三大法人合計賣超 1,262 張(佔量 5.2%)");
  assert.ok(!m.has("C_BOTH_SELL") && !m.has("C_BOTH_BUY"));
  // 資料日落後 → 帶日期、不取代
  const late = byCode(instFacts(ih, candles, "2026-10-02"));
  assert.equal(late.get("C_FOREIGN_SELL")?.date, "10/01");
  assert.equal(late.get("C_FOREIGN_SELL")?.mirrors, undefined);
});

test("法人:同步買超/賣超、近 20 日累計只在單日不成立時列", () => {
  const b = byCode(instFacts(instiBothBuy().ih, instiBothBuy().candles, LAST));
  assert.equal(b.get("C_BOTH_BUY")?.text, "外資、投信同步買超");
  assert.deepEqual(b.get("C_NET_SHARE_BUY")?.mirrors, ["I_NET_SHARE"]);
  assert.deepEqual(b.get("C_FOREIGN_BUY")?.mirrors, ["I_FOREIGN_BUY", "I_FOREIGN_STREAK"]);
  const s = byCode(instFacts(instiBothSell().ih, instiBothSell().candles, LAST));
  assert.ok(s.has("C_BOTH_SELL") && s.has("C_TRUST_SELL") && s.has("C_FOREIGN_SELL"));
  const d = byCode(instFacts(insti20d().ih, insti20d().candles, LAST));
  assert.equal(d.get("C_FOREIGN_20D_BUY")?.text, "外資近20日累計買超 +7,650 張(佔期間量 3.8%)");
  assert.equal(d.get("C_TRUST_20D_SELL")?.text, "投信近20日累計賣超 −4,770 張(佔期間量 2.4%)");
  assert.ok(!d.has("C_FOREIGN_BUY") && !d.has("C_TRUST_SELL"));
  assert.deepEqual(instFacts(undefined, [], LAST), []);
});

test("資券:使用率過熱、融資增價跌、融券變化;健康、融資減價漲、券資比", () => {
  const h = byCode(marginFacts(marginHotUp().mh, marginHotUp().adjusted, LAST));
  assert.equal(h.get("C_MARGIN_HOT")?.text, "融資使用率 70%,高於 60%");
  assert.equal(h.get("C_MARGIN_UP_PRICE_DOWN")?.text, "融資 5 日增加 +200 張(+18.2%),股價 5 日 −2.5%");
  assert.equal(h.get("C_SHORT_CHANGE")?.text, "融券 5 日增加 +50 張(+50.0%)");
  const o = byCode(marginFacts(marginOkDown().mh, marginOkDown().adjusted, LAST));
  assert.deepEqual(o.get("C_MARGIN_OK")?.mirrors, ["I_MARGIN_OK"]);
  assert.equal(o.get("C_MARGIN_DOWN_PRICE_UP")?.side, "bull");
  assert.equal(o.get("C_SHORT_MARGIN_RATIO")?.text, "券資比 44%");
  assert.deepEqual(marginFacts(undefined, [], LAST), []);
});

test("分點:前 12 大淨流、1 月囤貨/出貨、隔日沖買超、地緣、區間損益(估算)", () => {
  const f = branchMonth();
  const m = byCode(branchFacts(f, f.candles, LAST, new Set()));
  assert.equal(m.get("C_TOP15_FLOW_BUY")?.text, "前12大分點今日淨買超 1,000 張(佔量 10.0%)");
  assert.equal(m.get("C_ACC_1M")?.text, "近1月囤貨分點 1 家:A分點 +6,000 張,合計 +6,000 張");
  assert.equal(m.get("C_DIST_1M")?.text, "近1月出貨分點 1 家:B分點 −6,000 張,合計 −6,000 張");
  assert.equal(m.get("C_DIST_1M")?.risk, true);
  assert.ok(!m.has("C_ACC_1W"), "1 週名單與 1 月重疊過半 → 不另列");
  assert.equal(m.get("C_DAYTRADE_BUY")?.text, "今日買超分點中有隔日沖紀錄者 1 家,合計 +1,000 張(佔量 10.0%)");
  assert.deepEqual(m.get("C_GEO_BUY")?.mirrors, ["G1_GEO_BUY"]);
  assert.equal(m.get("C_PNL_LOSERS_HOLDING")?.text, "近60日仍有持股且帳面為負的分點 2 家,合計持股 600 張(估算)");
  assert.equal(m.get("C_PNL_GAINERS_HOLDING")?.side, "bull");
});

test("分點:只有 1 週的囤貨/出貨、追蹤分點賣超(關掉的不算)、地緣賣超、前 12 大淨賣", () => {
  const f = branchWeek();
  const m = byCode(branchFacts(f, f.candles, LAST, new Set(["靜音分點"])));
  assert.ok(m.has("C_ACC_1W") && m.has("C_DIST_1W") && !m.has("C_ACC_1M") && !m.has("C_DIST_1M"));
  assert.equal(m.get("C_TRACKED_SELL")?.text, "追蹤分點今日淨賣超 1 家:H分點 −1,500 張");
  assert.deepEqual(m.get("C_GEO_SELL")?.mirrors, ["G2_GEO_SELL"]);
  assert.equal(m.get("C_TOP15_FLOW_SELL")?.text, "前12大分點今日淨賣超 1,500 張(佔量 15.0%)");
  const muted = byCode(branchFacts(f, f.candles, LAST, new Set(["H分點"])));
  assert.ok(!muted.has("C_TRACKED_SELL"));
  assert.deepEqual(branchFacts({}, [], LAST, new Set()), []);
});

test("權證、期貨、題材、庫藏股", () => {
  const w = byCode(warrantFacts(
    { call_turnover: 5_000_000, call_volume: 0, call_count: 1, put_turnover: 6_500_000, put_volume: 0, put_count: 1, call_avg20: null, call_turnover_ratio: null, put_call_ratio: 1.3 },
    [...Array.from({ length: 20 }, (_, i) => ({ t: `2026-09-${String(i + 1).padStart(2, "0")}`, call_turnover: 0, put_turnover: 1_000_000, call_count: 0, put_count: 1 })),
      { t: LAST, call_turnover: 0, put_turnover: 8_000_000, call_count: 0, put_count: 1 }],
    LAST,
  ));
  assert.equal(w.get("C_PUT_DOMINANT")?.text, "認售權證成交 650 萬,為認購的 1.3 倍");
  assert.equal(w.get("C_PUT_SURGE")?.text, "認售權證成交 800 萬,為前20日均值 8.0 倍");
  const fut = futuresFacts({
    version: 1, list_as_of: "2026-09-30", daily_as_of: "2026-09-30",
    contracts: [{ code: "XYZ", multiplier: 2000, is_futures: true, is_option: false, is_weekly_option: false, anomaly: { today: 5000, window_max: 3000, window_median: 1000, window_days: 60 } }],
  }, "2330");
  assert.equal(fut[0].text, "個股期貨一般時段成交 5,000 口,為前 60 個比較日最高(方向未定)");
  assert.equal(fut[0].side, "context");
  assert.equal(fut[0].date, "行情 09/30");
  const th = byCode(themeFacts(
    [
      { id: "1", name: "矽晶圓", status: "active", data_date: null, heat_date: LAST, vs20: 2.38, avg_chg: 1, turnover: 1, up: 1, down: 0, eligible: true },
      { id: "2", name: "冷題材", status: "active", data_date: null, heat_date: LAST, vs20: 0.6, avg_chg: 0, turnover: 1, up: 0, down: 1, eligible: true },
      { id: "3", name: "不合格", status: "active", data_date: null, heat_date: LAST, vs20: 5, avg_chg: 0, turnover: 1, up: 0, down: 1, eligible: false },
    ],
    { plan_id: "p", stock_id: "2330", name: "x", market: "twse", board_date: null, purpose: null, total_amount_limit: null, planned_shares: null, price_min: null, price_max: null,
      start_date: "2026-09-01", end_date: "2026-10-31", completed_flag: null, status: "in_progress", executed_shares: null, transferred_shares: null, execution_pct: 35, executed_amount: null,
      avg_price: null, share_ratio_pct: null, incomplete_reason: null, report_date: null, source_updated_at: null, source: "mops" },
    LAST,
  ));
  assert.equal(th.get("C_THEME_HOT")?.text, "所屬題材成交為20日均:【矽晶圓】2.38 倍");
  assert.deepEqual(th.get("C_THEME_HOT")?.mirrors, ["T_THEME_HOT", "H1_HOT_THEME"]);
  assert.equal(th.get("C_THEME_COLD")?.side, "context");
  assert.equal(th.get("C_BUYBACK")?.text, "庫藏股買回期間 09/01–10/31,已執行 35%");
  assert.deepEqual(futuresFacts(undefined, "2330"), []);
  assert.deepEqual(themeFacts(undefined, null, LAST), []);
  assert.deepEqual(warrantFacts(null, [], LAST), []);
});
