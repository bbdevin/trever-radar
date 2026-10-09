// 執行: node --test --experimental-strip-types web/lib/chartTime.test.ts
// 時區無關:各換 TZ 再跑一次結果須相同,例如
//   TZ=UTC / TZ=Asia/Taipei / TZ=America/Los_Angeles node --test --experimental-strip-types web/lib/chartTime.test.ts
//
// K 線與首頁走勢圖的十字線/時間軸標籤(lib/chartTime)。
import assert from "node:assert/strict";
import { test } from "node:test";

import { chartTimeParts, crosshairTimeLabel, tickMarkLabel } from "./chartTime.ts";
import { chartTimeOf, twWallKey } from "./resample.ts";
import { axisTickLabel } from "./marketBrief.ts";

// 2026-10-06 11:55 台北 = 03:55Z;圖表拿到的是 chartTimeOf("2026-10-06T11:55")(牆上時間當 UTC)
const EPOCH_1155 = Date.parse("2026-10-06T03:55:00Z") / 1000;
const T_1155 = chartTimeOf(twWallKey(EPOCH_1155)) as number;
const T_0900 = chartTimeOf("2026-10-06T09:00") as number;
// 跨年:台北 2027-01-01 09:00 = 2027-01-01T01:00Z,UTC-8 的瀏覽器本地會是 2026-12-31
const T_NEWYEAR = chartTimeOf("2027-01-01T09:00") as number;

test(`日K以上:十字線 MM/DD,週/月K帶年 (TZ=${process.env.TZ ?? "(system)"})`, () => {
  assert.equal(crosshairTimeLabel("2026-10-07"), "10/07");
  assert.equal(crosshairTimeLabel("2026-10-07", true), "2026/10/07");
  assert.equal(crosshairTimeLabel({ year: 2026, month: 3, day: 5 }), "03/05");
  assert.equal(crosshairTimeLabel("odd"), "odd");
});

test("分K:十字線「MM/DD HH:MM」台北時間,與瀏覽器時區無關", () => {
  assert.equal(twWallKey(EPOCH_1155), "2026-10-06T11:55");
  assert.equal(crosshairTimeLabel(T_1155), "10/06 11:55");
  // withYear 只影響日期字串;分K一律 MM/DD HH:MM
  assert.equal(crosshairTimeLabel(T_1155, true), "10/06 11:55");
  assert.equal(crosshairTimeLabel(T_0900), "10/06 09:00");
  assert.equal(crosshairTimeLabel(T_NEWYEAR), "01/01 09:00");
  assert.deepEqual(chartTimeParts(T_NEWYEAR), { y: 2027, m: 1, d: 1, hh: 9, mm: 0 });
});

test("時間軸刻度:年 → 2026年、月 → 9月、日 → 10/07", () => {
  assert.equal(tickMarkLabel("2026-10-07", 0), "2026年");
  assert.equal(tickMarkLabel("2026-09-01", 1), "9月");
  assert.equal(tickMarkLabel("2026-10-07", 2), "10/07");
  // 日線不會出現時刻刻度;萬一出現也退回 MM/DD,不印 00:00
  assert.equal(tickMarkLabel("2026-10-07", 3), "10/07");
  assert.equal(tickMarkLabel("odd", 2), "odd");
});

test("分K刻度:一天之內 HH:MM,換日 MM/DD,換月/年照日線寫法", () => {
  assert.equal(tickMarkLabel(T_1155, 3), "11:55");
  assert.equal(tickMarkLabel(T_1155, 4), "11:55");
  assert.equal(tickMarkLabel(T_0900, 2), "10/06");
  assert.equal(tickMarkLabel(T_NEWYEAR, 1), "1月");
  assert.equal(tickMarkLabel(T_NEWYEAR, 0), "2027年");
});

test("首頁走勢圖的 axisTickLabel 與 K 線共用同一套", () => {
  for (const [t, k] of [["2026-10-07", 0], ["2026-09-01", 1], ["2026-10-07", 2], ["odd", 2]] as const) {
    assert.equal(axisTickLabel(t, k), tickMarkLabel(t, k));
  }
});
