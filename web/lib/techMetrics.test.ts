// 執行: node --test --experimental-strip-types web/lib/techMetrics.test.ts
//
// 多空分頁技術分析段頂的指標列(docs/46 §6.7):色調規則與價格距離。
import assert from "node:assert/strict";
import { test } from "node:test";

import { rsiTone, techMetrics, volTone } from "./techMetrics.ts";
import type { TechnicalSummary } from "./types.ts";

const t = (over: Partial<TechnicalSummary> = {}): TechnicalSummary => ({
  score: 45, ma20: 100, ma60: 90, rsi14: 62.34, volume_ratio: 1.8, reasons: [], risks: [], ...over,
});

test("RSI 色調:<50 綠、50–70 紅、70–80 中性、>80 琥珀、缺值中性", () => {
  assert.deepEqual([null, 30, 49.9, 50, 70, 75, 80, 80.1].map(rsiTone), ["neutral", "down", "down", "up", "up", "neutral", "neutral", "warn"]);
});

test("量比色調:≥1.5 依收盤漲跌上紅/綠,未達或平盤中性", () => {
  assert.equal(volTone(1.5, 0.02), "up");
  assert.equal(volTone(2.3, -0.01), "down");
  assert.equal(volTone(1.49, 0.05), "neutral");
  assert.equal(volTone(3, 0), "neutral");
  assert.equal(volTone(3, null), "neutral");
  assert.equal(volTone(null, 0.05), "neutral");
});

test("指標列:順序、文字與價格距離(價格精度隨收盤、+紅 −綠)", () => {
  const m = techMetrics(t(), { watch: 1100, stop: 950 }, 1000, 0.03);
  assert.deepEqual(m.map((x) => [x.key, x.label, x.value, x.tone]), [
    ["score", "技術分", "45", "brand"],
    ["rsi", "RSI14", "62.3", "up"],
    ["vol", "量比", "1.8×", "up"],
    ["watch", "觀察價", "1,100", "neutral"],
    ["stop", "失效價", "950", "neutral"],
  ]);
  assert.deepEqual(m[3].dist, { text: "+10.0%", dir: "up" });
  assert.deepEqual(m[4].dist, { text: "−5.0%", dir: "down" });
  assert.ok(m[3].price && m[4].price && !m[0].price);
  // 低價股兩位小數
  assert.equal(techMetrics(t(), { watch: 23.456 }, 22, null)[3].value, "23.46");
});

test("缺值:沒有觀察/失效價就不列那格;RSI/量比缺值顯示 —;無收盤不算距離", () => {
  const m = techMetrics(t({ rsi14: null, volume_ratio: null }), { watch: null, stop: undefined }, 100, 0.01);
  assert.deepEqual(m.map((x) => x.value), ["45", "—", "—"]);
  const noClose = techMetrics(t(), { stop: 95.5 }, null, null);
  assert.equal(noClose[3].value, "95.50");
  assert.equal(noClose[3].dist, undefined);
});
