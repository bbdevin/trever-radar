// 執行: node --test --experimental-strip-types web/lib/facts/techFacts.test.ts
//
// 技術段(docs/46 v2 §2.1):日/週/月事件與狀態、每週期每指標最多一列、週/月不產 R_*、事件句尾(本週/本月)。
import assert from "node:assert/strict";
import { test } from "node:test";

import type { TechnicalSummary } from "../types.ts";
import { techBearSeries, techBullSeries, techQuietSeries } from "./fixtures.ts";
import { techFacts } from "./techFacts.ts";

const tech = (volume_ratio: number | null): TechnicalSummary => ({ score: 0, ma20: null, ma60: null, rsi14: null, volume_ratio, reasons: [], risks: [] });
const byKey = (fs: ReturnType<typeof techFacts>) => new Map(fs.map((f) => [`${f.code}:${f.tf}`, f]));

test("多方日K:站回 20 日線、MACD 翻正、KD 低檔金叉、量增、連漲、單日/5 日幅度、跳空", () => {
  const m = byKey(techFacts(techBullSeries(), tech(2.3)));
  assert.equal(m.get("X_MA_CROSS_UP:D")?.text, "收盤今日站回20日線 110.0");
  assert.equal(m.get("X_MACD_CROSS_UP:D")?.text, "MACD柱狀體今日翻正");
  assert.deepEqual(m.get("X_MACD_CROSS_UP:D")?.mirrors, ["T5_MACD_HIST_POS"]);
  assert.equal(m.get("X_KD_GOLDEN_LOW:D")?.text, "KD於50以下黃金交叉(K 40)");
  assert.equal(m.get("X_VOL_SURGE_UP:D")?.text, "成交量為20日均量 2.3 倍,收漲 +7.7%");
  assert.equal(m.get("X_UP_STREAK:D")?.text, "連 5 日收漲,累計 +12.0%");
  assert.equal(m.get("X_CHG1_UP:D")?.text, "今日上漲 +7.7%");
  assert.equal(m.get("X_CHG5_UP:D")?.text, "近 5 日上漲 +12.0%");
  assert.equal(m.get("X_GAP_UP_TODAY:D")?.text, "今日跳空上漲 +7.7%,缺口 105.0–110.0 未回補");
  assert.equal(m.get("X_MA20_SLOPE_UP:D")?.text, "20日均線較5日前 +10.0%");
  assert.equal(m.get("X_MA60_SLOPE_UP:D")?.text, "60日均線較5日前 +5.0%");
  // 價格段是藍色 price、漲跌是 up
  const gap = m.get("X_GAP_UP_TODAY:D")!;
  assert.deepEqual(gap.segments?.filter((s) => s.kind).map((s) => [s.kind, s.t]), [["up", "+7.7%"], ["price", "105.0"], ["price", "110.0"]]);
});

test("週K/月K:排列、RSI、量增價漲、創新高;事件句尾帶(本週)(本月),週/月 rank 降一級", () => {
  const m = byKey(techFacts(techBullSeries(), tech(null)));
  assert.equal(m.get("X_ALIGN_BULL:W")?.text, "5/10/20週線多頭排列");
  assert.equal(m.get("F8_RSI_OK:W")?.text, "RSI14 60,位於 50–70");
  assert.equal(m.get("F5_UP:W")?.text, "連2週量增價漲(本週)");
  assert.equal(m.get("F4_NEW_HIGH:W")?.text, "收盤創20週新高(本週)");
  assert.equal(m.get("X_UP_STREAK:W")?.text, "連 3 週收漲,累計 +20.0%");
  assert.equal(m.get("X_MA_CROSS_UP:M")?.text, "收盤站回20月線 106.0(本月)");
  assert.equal(m.get("X_MACD_STATE_POS:M")?.text, "MACD 位於零軸之上,柱狀體連 2 個月為正");
  assert.equal(m.get("X_KD_OVER80:M")?.text, "K值 85,高於 80");
  assert.equal(m.get("F4_NEW_HIGH:W")?.rank, 3);
  assert.equal(m.get("X_MA_CROSS_UP:M")?.rank, 3);
  // 週/月不產 R_*、日K 不重複產 F2/F4/F5/F8(那些由 priceLevelFacts 產)
  const all = techFacts(techBullSeries(), tech(null));
  assert.ok(!all.some((f) => f.code.startsWith("R_")));
  assert.ok(!all.some((f) => f.tf === "D" && /^F[2458]_/.test(f.code)));
});

test("空方日K:跌破 20 日線、MACD 翻負、KD 高檔死叉、量增收跌、連跌、跳空下跌、長黑(皆為事件型 ⚠)", () => {
  const fs = techFacts(techBearSeries(), tech(2));
  const m = byKey(fs);
  assert.equal(m.get("X_MA_CROSS_DOWN:D")?.text, "收盤今日跌破20日線 90.0");
  assert.equal(m.get("X_MACD_CROSS_DOWN:D")?.text, "MACD柱狀體今日翻負");
  assert.equal(m.get("X_KD_DEATH_HIGH:D")?.text, "KD於50以上死亡交叉(K 60)");
  assert.equal(m.get("X_VOL_SURGE_DOWN:D")?.text, "成交量為20日均量 2.0 倍,收跌 −9.3%");
  assert.equal(m.get("X_DOWN_STREAK:D")?.text, "連 5 日收跌,累計 −12.0%");
  assert.equal(m.get("X_CHG1_DOWN:D")?.text, "今日下跌 −9.3%");
  assert.equal(m.get("X_CHG5_DOWN:D")?.text, "近 5 日下跌 −12.0%");
  assert.equal(m.get("X_GAP_DOWN_TODAY:D")?.text, "今日跳空下跌 −9.3%,缺口 94.0–96.0 未回補");
  assert.equal(m.get("X_BIG_BLACK:D")?.text, "今日收長黑 K,實體 −5.9%");
  for (const c of ["X_MA_CROSS_DOWN", "X_MACD_CROSS_DOWN", "X_KD_DEATH_HIGH", "X_GAP_DOWN_TODAY", "X_BIG_BLACK"]) assert.equal(m.get(`${c}:D`)?.risk, true, c);
  assert.equal(m.get("X_DOWN_STREAK:D")?.risk, undefined);
  assert.equal(m.get("X_ALIGN_BEAR:W")?.text, "5/10/20週線空頭排列");
  assert.equal(m.get("F8_RSI_LOW:W")?.text, "RSI14 40,低於 50");
  assert.equal(m.get("F5_DOWN:W")?.text, "連2週量增價跌(本週)");
  assert.equal(m.get("F4_NEW_LOW:W")?.text, "收盤創20週新低(本週)");
  assert.equal(m.get("X_MACD_STATE_NEG:W")?.text, "MACD 位於零軸之下,柱狀體連 2 週為負");
  assert.ok(m.get("X_MA20_SLOPE_DOWN:D") && m.get("X_MA60_SLOPE_DOWN:D"));
  // 每個週期每個指標最多一列:同一 tf 不會同時有 MACD 交叉與狀態、KD 死叉與 >80
  for (const tf of ["D", "W", "M"]) {
    const codes = fs.filter((f) => f.tf === tf).map((f) => f.code);
    assert.ok(!(codes.includes("X_MACD_CROSS_DOWN") && codes.includes("X_MACD_STATE_NEG")), tf);
    assert.ok(!(codes.includes("X_KD_DEATH_HIGH") && codes.includes("X_KD_OVER80")), tf);
    assert.equal(new Set(codes).size, codes.length, `${tf} 有重複 code`);
  }
});

test("量縮背景、平盤沒有事實", () => {
  const m = byKey(techFacts(techQuietSeries(), tech(null)));
  assert.equal(m.get("X_VOL_DRY:D")?.text, "成交量為20日均量 0.3 倍");
  assert.equal(m.get("X_VOL_DRY:D")?.side, "context");
  assert.equal(m.size, 1);
});
