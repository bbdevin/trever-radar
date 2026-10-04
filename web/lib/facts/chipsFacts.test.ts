// 執行: node --test --experimental-strip-types web/lib/facts/chipsFacts.test.ts
//
// 籌碼段(docs/46 v2 §2.3–2.5、2.7):法人、資券、分點、權證、期貨、題材、公司。
import assert from "node:assert/strict";
import { test } from "node:test";

import type { DerivedFact } from "../bullBear.ts";
import { branchFacts } from "./branchFacts.ts";
import {
  LAST, branchMonth, branchSmart, branchWeek, insti20d, instiBothBuy, instiBothSell, instiSellStreak, marginConcBuildup, marginConcForeignOnly,
  marginConcGap, marginConcTdccDown, marginDispersedDown, marginHotUp, marginInstDominant, marginOkDown,
} from "./fixtures.ts";
import { instFacts } from "./instFacts.ts";
import { marginFacts } from "./marginFacts.ts";
import { marginFlowFacts } from "./marginFlowFacts.ts";
import { isForeignBroker } from "./seat.ts";
import { CHIPS_HOWTO_LINES, MARGIN_FLOW_DEFINITION } from "../priceLevels.ts";
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

test("融資×分點集中度:2476 型 20 日集中 + 堆積集中(背景),C_MARGIN_HOT 仍空方但 rank 2(docs/46 §7)", () => {
  const f = marginConcBuildup();
  const r = marginFlowFacts(f.data, f.candles, f.candles, LAST);
  const m = byCode(r.facts);
  const up = m.get("C_MARGIN_UP_CONC")!;
  assert.equal(up.text, "融資 20 日增加 +2,000 張(+11.1%),同期囤貨分點 2 家合計淨買超 +4,200 張(為融資增量的 210%),股價 20 日 +1.7%;400張以上大戶 +0.30 個百分點(集保 10/01)");
  assert.equal(up.side, "context");
  assert.equal(up.rank, 4);
  assert.equal(up.mirrors, undefined);
  const bu = m.get("C_MARGIN_BUILDUP_CONC")!;
  // 美林(外資席位)不算進囤貨分點:統一-敦南 18,000 + 康和 7,200
  assert.equal(bu.text, "融資餘額自 05/14 的 10,000 張增至 20,000 張(+10,000 張,使用率 75%);近6月囤貨分點 2 家合計淨買超 +25,200 張、400張以上大戶 +1.90 個百分點、股價 +9.1%");
  assert.equal(bu.side, "context");
  assert.equal(bu.rank, 3);
  assert.ok(r.buildupConc && !r.dispersed20);
  const hot = byCode(marginFacts(f.data.margin_history, f.candles, LAST, r)).get("C_MARGIN_HOT")!;
  assert.equal(hot.side, "bear");
  assert.equal(hot.rank, 2);
  assert.deepEqual(hot.mirrors, ["R_MARGIN_HOT"]);
  assert.equal(hot.text, "融資使用率 75%,高於 60%");
  // 資料日落後 → 帶日期
  assert.equal(byCode(marginFlowFacts(f.data, f.candles, f.candles, "2026-10-02").facts).get("C_MARGIN_UP_CONC")?.date, "10/01");
});

test("融資×分點集中度:分散且股價跌(空方 ⚠),取代 5 日融資增價跌;法人主導/外資席位/集保大戶減/分點缺日 → 不判讀", () => {
  const d = marginDispersedDown();
  const r = marginFlowFacts(d.data, d.candles, d.candles, LAST);
  const x = byCode(r.facts).get("C_MARGIN_UP_DISPERSED")!;
  assert.equal(x.text, "融資 20 日增加 +2,000 張(+20.0%),同期無囤貨分點,外資投信合計賣超 14,000 張,股價 20 日 −16.7%;400張以上大戶 −1.50 個百分點、未滿400張股東 +6.1%(集保 10/01)");
  assert.equal(x.side, "bear");
  assert.equal(x.risk, true);
  assert.equal(x.rank, 4);
  assert.equal(r.facts.length, 1);
  assert.ok(r.dispersed20);
  assert.ok(!byCode(marginFacts(d.data.margin_history, d.candles, LAST, r)).has("C_MARGIN_UP_PRICE_DOWN"));
  // 有囤貨但只佔融資增量 24%(融資改 +5,000 張、元大-士林 20 日 +1,200 張):改寫比例
  const p = marginDispersedDown();
  p.data.margin_history = p.data.margin_history!.map((row, i) => ({ ...row, balance: i < 5 ? 10000 + (5 - i) * 1000 : 10000 }));
  p.data.branch_history = p.data.branch_history!.map((day) => ({ ...day, branches: [...day.branches, { n: "元大-士林", b: 60, s: 0, net: 60 }] }));
  assert.ok(byCode(marginFlowFacts(p.data, p.candles, p.candles, LAST).facts).get("C_MARGIN_UP_DISPERSED")!.text
    .includes(",同期囤貨分點合計僅為融資增量的 24%,外資投信合計賣超"));

  const inst = marginInstDominant();
  const ri = marginFlowFacts(inst.data, inst.candles, inst.candles, LAST);
  assert.deepEqual(ri.facts, []);
  assert.ok(byCode(marginFacts(inst.data.margin_history, inst.candles, LAST, ri)).has("C_MARGIN_UP_PRICE_DOWN"));
  for (const f of [marginConcForeignOnly(), marginConcTdccDown(), marginConcGap()]) {
    const rr = marginFlowFacts(f.data, f.candles, f.candles, LAST);
    assert.deepEqual(rr.facts, []);
    assert.equal(byCode(marginFacts(f.data.margin_history, f.candles, LAST, rr)).get("C_MARGIN_HOT")?.rank, 3);
  }
  // 融資不顯著(< 200 張)→ 不判讀
  const small = marginDispersedDown();
  small.data.margin_history = small.data.margin_history!.map((row, i) => ({ ...row, balance: i < 5 ? 10100 : 10000 }));
  assert.deepEqual(marginFlowFacts(small.data, small.candles, small.candles, LAST).facts, []);
  assert.deepEqual(marginFlowFacts({}, [], [], LAST), { facts: [], buildupConc: false, dispersed20: false });
});

test("融資×分點集中度:只並列不歸因——事實句與定義句不出現歸因/操作字眼;定義句常駐籌碼段底", () => {
  // 以「·」拆開,避免這個檔案本身被 test_label_honesty 掃到
  const banned = ["主·力", "鎖·碼", "大戶·融資", "散戶·融資", "買·進", "賣·出", "看·多", "看·空", "建·議", "將·會"].map((w) => w.replace("·", ""));
  const texts = [marginConcBuildup(), marginDispersedDown()].flatMap((f) => marginFlowFacts(f.data, f.candles, f.candles, LAST).facts.map((x) => x.text));
  assert.equal(texts.length, 3);
  for (const t of [...texts, MARGIN_FLOW_DEFINITION]) for (const w of banned) assert.ok(!t.includes(w), `「${t}」含「${w}」`);
  assert.ok(CHIPS_HOWTO_LINES.includes(MARGIN_FLOW_DEFINITION));
});

test("外資席位:X商前綴、常見外資券商名、去掉 (…) 前綴後比對;本土分點/總公司不算", () => {
  for (const n of ["美商高盛", "(港商)麥格理", "美林", "摩根大通", "新加坡商瑞銀", "法國興業"]) assert.ok(isForeignBroker(n), n);
  for (const n of ["統一-敦南", "康和", "元大-士林", "凱基-台北"]) assert.ok(!isForeignBroker(n), n);
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
  // 區間損益估算前 3 名(甲乙戊)由 C_SMART_HOLDING 逐家寫(戊沒持股不寫),家數句不重算、改「另有」
  assert.equal(m.get("C_SMART_HOLDING")?.text,
    "區間損益估算前段分點【甲】(3月 +200 萬)仍有持股 500 張,帳面為正(估算);區間損益估算前段分點【乙】(3月 +100 萬)仍有持股 300 張,帳面為正(估算)");
  assert.equal(m.get("C_PNL_GAINERS_HOLDING")?.text, "另有近60日仍有持股且帳面為正的分點 2 家,合計持股 200 張(估算)");
  assert.equal(m.get("C_PNL_GAINERS_HOLDING")?.side, "bull");
});

test("分點:低買高賣/區間損益估算前段分點的買超、賣超、持股(docs/46 §6.8)", () => {
  const f = branchSmart();
  const facts = branchFacts(f, f.candles, LAST, new Set());
  const m = byCode(facts);
  const buy = m.get("C_SMART_BUY")!;
  assert.equal(buy.text,
    "區間損益估算前段分點【凱基-台北】(3月 +500 萬)今日買超 +600 張(佔量 6.0%);"
    + "低買高賣分點【群益金鼎-板橋】(短線派 買低 70%,本股 40%)近5日買超 +1,500 張(佔量 3.0%)");
  assert.equal(buy.side, "bull");
  assert.equal(buy.rank, 5);
  assert.equal(buy.magnitude, 6);
  const sell = m.get("C_SMART_SELL")!;
  assert.equal(sell.text,
    "低買高賣分點【B1】(長線派 賣高 60%,本股 40%)今日賣超 −600 張(佔量 6.0%);"
    + "區間損益估算前段分點【富邦-建國】(3月 +300 萬)近5日賣超 −180 張(佔量 0.4%),估算持股減少 64%");
  assert.equal(sell.side, "bear");
  assert.equal(sell.risk, true);
  assert.equal(m.get("C_SMART_HOLDING")?.text, "區間損益估算前段分點【國泰-敦南】(1年 +900 萬)仍有持股 800 張,帳面為正(估算)");
  assert.equal(m.get("C_SMART_HOLDING")?.rank, 3);
  assert.equal(m.get("C_SMART_HOLDING")?.side, "bull");
  // 帳面為負 → 背景,不是多方
  const neg = m.get("C_SMART_HOLDING_NEG")!;
  assert.equal(neg.text, "低買高賣分點【A2】(短線派 買低 70%,本股 40%)仍有持股 300 張,帳面為負(3月估算)");
  assert.equal(neg.side, "context");
  assert.equal(neg.rank, 2);
  // 份量不足(元大-士林 40 張)、超出前 5 名(永豐-竹北)、買側紀錄不足 → 都不點名
  const all = facts.map((x) => x.text).join("\n");
  for (const n of ["元大-士林", "永豐-竹北", "紀錄不足", "A1"]) assert.ok(!all.includes(`【${n}】`), n);
  // 一家分點只出現在一句
  for (const n of ["凱基-台北", "群益金鼎-板橋", "B1", "富邦-建國", "國泰-敦南", "A2"])
    assert.equal(facts.filter((x) => x.text.includes(`【${n}】`)).length, 1, n);
});

test("分點:強分點門檻——佔量 0.5% 或 500 張、50 張下限;前 2 家點名,其餘「等 N 家」", () => {
  const f = branchSmart();
  // 量放大到 200,000 張/日:群益 5 日 1,500 = 0.15%、凱基今日改 450 = 0.23%,都未達 0.5%;
  // 群益 1,500 ≥500 張 → 仍成立,凱基 450 <500 張 → 不列
  const k = f.branch_history![0].branches.find((b) => b.n === "凱基-台北")!;
  k.b = 450; k.net = 450;
  const big = f.candles.map((c) => ({ ...c, v: 200_000 }));
  const m = byCode(branchFacts(f, big, LAST, new Set()));
  assert.equal(m.get("C_SMART_BUY")?.text, "低買高賣分點【群益金鼎-板橋】(短線派 買低 70%,本股 40%)近5日買超 +1,500 張(佔量 0.1%)");
  assert.equal(m.get("C_SMART_BUY")?.rank, 4);
  // 3 家都成立 → 點名前 2 家 + 等 3 家
  const g = branchSmart();
  g.branch_history![0].branches.push({ n: "A1", b: 900, s: 0, net: 900 });
  const t = byCode(branchFacts(g, g.candles, LAST, new Set())).get("C_SMART_BUY")!.text;
  assert.ok(t.endsWith(" 等 3 家"), t);
  assert.equal((t.match(/【/g) ?? []).length, 2);
});

test("分點:強分點賣超與追蹤分點賣超不重複;資料日落後帶日期;舊 JSON 不丟例外", () => {
  const f = branchSmart();
  f.branch_tags!.tracked = ["B1"];
  const m = byCode(branchFacts(f, f.candles, LAST, new Set()));
  assert.equal(m.get("C_TRACKED_SELL")?.text, "追蹤分點今日淨賣超 1 家:B1 −600 張");
  assert.ok(!m.get("C_SMART_SELL")!.text.includes("【B1】"));
  const late = byCode(branchFacts(f, f.candles, "2026-10-02", new Set()));
  assert.equal(late.get("C_SMART_BUY")?.date, "10/01");
  assert.ok(late.get("C_SMART_BUY")!.text.includes("【凱基-台北】(3月 +500 萬)買超 +600 張"));
  // 舊 JSON:沒有 branch_pctile_counts / branch_pnl_est、v1 分位(沒有長線派)
  const g = branchSmart();
  assert.ok(!byCode(branchFacts({ branch_history: g.branch_history }, g.candles, LAST, new Set())).has("C_SMART_BUY"));
  const v1 = {
    version: 1 as const, as_of: LAST, window_market_days: 20, window_from: null, computed_at: null, definitions_version: null,
    min_known_episodes_per_side: 5, max_branches: 10, stock_buy_pctile_known: null, stock_low_buy_count: null,
    stock_sell_pctile_known: null, stock_high_sell_count: null,
    branches: [{ branch_name: "群益金鼎-板橋", buy_pctile_known: 10, buy_pctile_unknown: 0, low_buy_count: 7, sell_pctile_known: 10, sell_pctile_unknown: 0, high_sell_count: 8 }],
  };
  const old = byCode(branchFacts({ branch_history: g.branch_history, branch_pctile_counts: v1 }, g.candles, LAST, new Set()));
  assert.equal(old.get("C_SMART_BUY")?.text, "低買高賣分點【群益金鼎-板橋】(短線派 買低 70%)近5日買超 +1,500 張(佔量 3.0%)");
  assert.doesNotThrow(() => branchFacts({ branch_pctile_counts: { version: 2 } as never, branch_pnl_est: { as_of: LAST, definitions_version: "x", windows: {} } }, [], LAST, new Set()));
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
