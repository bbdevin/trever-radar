// 執行: node --test --experimental-strip-types web/lib/facts/levelFacts.test.ts
//
// 壓力段(docs/46 v2 §2.2):每列價位 + 距離、同價同日合併、≤3% 接近、週/月均線、缺口、區間位置、資料內最高/低。
import assert from "node:assert/strict";
import { test } from "node:test";

import { chartLevels, isNear, priceLevelFacts, priceLevelsView } from "../priceLevels.ts";
import { LAST, levelSeries, okLevels } from "./fixtures.ts";
import { levelFacts, nearLevelFacts } from "./levelFacts.ts";

test("上方壓力:240 日最高(60/120 同價同日合併)、密集區、現價之上成交、缺口、資料內最高", () => {
  const fs = levelFacts(okLevels(), levelSeries(), LAST);
  const bear = fs.filter((f) => f.side === "bear").map((f) => `${f.code}|${f.text}`);
  assert.ok(bear.includes("L_HIGH_ABOVE|240日最高 1,594(03/12)在上方 +46.9%"), bear.join("\n"));
  assert.equal(fs.filter((f) => f.code === "L_HIGH_ABOVE").length, 1, "60/120/240 同價同日只列一次;今日的 20 日高不列");
  assert.ok(bear.includes("L_DENSE_ABOVE|成交最密集區 1,100–1,111 在上方 +1.4%(佔近120日成交 6.0%),接近"));
  assert.ok(bear.includes("L_SUPPLY_ABOVE|近120日成交 38% 在現價之上"));
  assert.ok(bear.includes("L_GAP_ABOVE|未回補缺口 1,095–1,240(" + "08/07" + ")在上方 +0.9%") || bear.some((b) => b.startsWith("L_GAP_ABOVE|未回補缺口 1,095–1,240(")), bear.join("\n"));
  assert.ok(bear.some((b) => b.startsWith("L_ALLTIME_HIGH|近 0.8 年資料最高 2,050(")));
  assert.ok(bear.includes("F1_MA_ABOVE|20 週線在上方,最接近 20週線 1,120(+3.2%)"));
  assert.ok(bear.includes("F1_MA_ABOVE|5/20/60 月線在上方,最接近 20月線 1,085(0.0%)"));
  // 接近(≤3%)的 rank 5
  assert.equal(fs.find((f) => f.code === "L_DENSE_ABOVE")?.rank, 5);
  assert.equal(fs.find((f) => f.code === "L_HIGH_ABOVE")?.rank, 2);
});

test("下方支撐:N 日最低、密集區、缺口、週/月均線;距離為 −", () => {
  const fs = levelFacts(okLevels(), levelSeries(), LAST);
  const bull = fs.filter((f) => f.side === "bull").map((f) => `${f.code}|${f.text}`);
  assert.ok(bull.includes("L_LOW_BELOW|20日最低 1,060(09/25)在下方 −2.3%,接近"));
  assert.ok(bull.includes("L_LOW_BELOW|240日最低 330(11/21)在下方 −69.6%"));
  assert.ok(bull.includes("L_DENSE_BELOW|成交最密集區 944–955 在下方 −12.0%(佔近120日成交 4.0%)"));
  assert.ok(bull.includes("L_SUPPLY_BELOW|近120日成交 62% 在現價之下"));
  assert.equal(fs.filter((f) => f.code === "L_GAP_BELOW").length, 2);
  assert.ok(bull.some((b) => b.startsWith("L_ALLTIME_LOW|近 0.8 年資料最低 43(")));
  assert.ok(bull.includes("F1_MA_BELOW|站上 5/10/60 週線,最接近 5週線 1,070(−1.4%)"));
  assert.ok(bull.includes("F1_MA_BELOW|站上 10 月線,最接近 10月線 980(−9.7%)"));
  // 每一列都有距離(排序用),壓力段 section
  for (const f of fs.filter((x) => x.code.startsWith("L_") && !x.code.startsWith("L_SUPPLY") && !x.code.startsWith("L_RANGE"))) assert.ok(f.dist != null, f.code);
  assert.ok(fs.every((f) => f.section === "levels"));
});

test("60 日區間上緣/下緣;價格位置落後資料日 → 帶日期", () => {
  const top = levelFacts(okLevels({ highs: { "60": { p: 1090, t: "2026-09-30" } } }), levelSeries(), LAST);
  const t = top.find((f) => f.code === "L_RANGE_POS_TOP");
  assert.equal(t?.text, "收盤位於近60日高低區間上緣(區間 98%)");
  assert.deepEqual(t?.mirrors, ["T3_BOX_TOP"]);
  const bot = levelFacts(okLevels({ lows: { "60": { p: 1080, t: "2026-09-30" } } }), levelSeries(), LAST);
  assert.equal(bot.find((f) => f.code === "L_RANGE_POS_BOTTOM")?.text, "收盤位於近60日高低區間下緣(區間 1%)");
  const stale = levelFacts(okLevels(), levelSeries(), "2026-10-02");
  assert.ok(stale.filter((f) => f.tf !== "W" && f.tf !== "M").every((f) => f.date === "10/01" && !f.mirrors));
});

test("舊 JSON:沒有 price_levels 只剩週/月均線;密集區佔量 <0.5% 不列", () => {
  const fs = levelFacts(undefined, levelSeries(), LAST);
  assert.ok(fs.every((f) => f.code.startsWith("F1_") && (f.tf === "W" || f.tf === "M")));
  const thin = levelFacts(okLevels({ dense_above: { lo: 1100, hi: 1111, share: 0.002 } }), levelSeries(), LAST);
  assert.ok(!thin.some((f) => f.code === "L_DENSE_ABOVE"));
});

test("密集區佔量門檻:價格階梯、K 線虛線與事實句同一個 denseZone(佔 <0.5% 三處都不列)", () => {
  const pl = okLevels({ dense_above: { lo: 1100, hi: 1111, share: 0.002 }, dense_below: { lo: 944, hi: 955, share: 0.001 } });
  const v = priceLevelsView(pl);
  assert.equal(v.state, "ok");
  if (v.state !== "ok") return;
  assert.ok(![...v.above, ...v.below].some((r) => r.kind === "zone"));
  assert.ok(!chartLevels(pl).some((l) => l.label === "密集區"));
  assert.ok(!levelFacts(pl, levelSeries(), LAST).some((f) => f.code.startsWith("L_DENSE")));
  // 達門檻的照列
  const ok = priceLevelsView(okLevels());
  assert.ok(ok.state === "ok" && ok.above.some((r) => r.kind === "zone") && ok.below.some((r) => r.kind === "zone"));
});

test("isNear:依畫面一位小數判斷(畫面 +3.0% 算接近,+3.1% 不算)", () => {
  assert.ok(isNear(3.04));
  assert.ok(isNear(-3.04));
  assert.ok(!isNear(3.05));
  assert.ok(isNear(0));
});

test("nearLevelFacts:壓力段 ≤3% 的價位在技術段日K 併成一句,由近到遠點名 2 個、其餘「等 N 處」;rank 3", () => {
  const facts = [...priceLevelFacts(okLevels(), LAST, 60), ...levelFacts(okLevels(), levelSeries(), LAST)];
  const near = nearLevelFacts(facts);
  const bear = near.find((f) => f.code === "X_LEVEL_ABOVE_NEAR")!;
  const bull = near.find((f) => f.code === "X_LEVEL_BELOW_NEAR")!;
  // 上方 ≤3%:20月線 0.0%、缺口 +0.9%、120日線 +1.4%、密集區 +1.4%(20週線 +3.2% 不算)
  assert.equal(bear.text, "上方 3% 內有壓力價位:20月線 1,085(0.0%)、未回補缺口 1,095–1,240(+0.9%)等 4 處");
  assert.equal(bull.text, "下方 3% 內有支撐價位:未回補缺口 1,060–1,075(−0.9%)、5週線 1,070(−1.4%)等 4 處");
  for (const f of near) {
    assert.equal(f.section, "tech");
    assert.equal(f.tf, "D");
    assert.equal(f.rank, 3);
    assert.equal(f.dist, undefined);
    assert.equal(f.segments!.map((s) => s.t).join(""), f.text);
  }
  assert.ok(bear.segments!.some((s) => s.kind === "price" && s.t === "1,085"));
  // 每一個壓力段 ≤3% 的價位事實都有短標(否則技術段會漏)
  for (const f of facts.filter((x) => x.section === "levels" && x.dist != null && isNear(x.dist))) assert.ok(f.level?.length, f.code);
  // 價格位置落後 → 技術段這句也帶日期
  const stale = nearLevelFacts([...priceLevelFacts(okLevels(), "2026-10-02", 60), ...levelFacts(okLevels(), levelSeries(), "2026-10-02")]);
  assert.ok(stale.every((f) => f.date === "10/01"));
  // 沒有 ≤3% 的價位 → 不產
  assert.deepEqual(nearLevelFacts(facts.filter((f) => !isNear(f.dist ?? Infinity))), []);
});
