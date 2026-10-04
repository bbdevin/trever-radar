// 執行: node --test --experimental-strip-types web/lib/facts/holdersFacts.test.ts
//
// 大戶比(docs/46 v2 §2.6):400/1000 張週變化、連續週數、近 N 週最高、散戶人數、董監、質押;一律帶集保資料日。
import assert from "node:assert/strict";
import { test } from "node:test";

import { DIRECTORS_PLEDGED, holdersBear, holdersBull } from "./fixtures.ts";
import { holdersFacts } from "./holdersFacts.ts";

test("多方:400 張連 3 週增且為近 14 週最高、1000 張反向減另列、散戶人數減、董監增", () => {
  const hh = holdersBull();
  const fs = holdersFacts(hh, { display_from: "", display_to: "", db_earliest: null, insider_as_of_ym: "2026-08" }, DIRECTORS_PLEDGED);
  const m = new Map(fs.map((f) => [f.code, f]));
  assert.equal(m.get("H_MAJOR400_UP")?.text, "400張以上大戶持股 77.00%,週增 +0.40 個百分點,連 3 週增加,為近 14 週最高");
  assert.equal(m.get("H_MAJOR400_UP")?.rank, 3);
  assert.equal(m.get("H_MAJOR1000_DOWN")?.text, "1000張以上大戶持股 70.00%,週減 −0.40 個百分點,為近 14 週最低");
  assert.equal(m.get("H_RETAIL_DOWN")?.text, "未滿400張股東 100,000→97,000 人(−3.0%),持股 23.00%→23.00%");
  assert.equal(m.get("H_MAJOR_COUNT")?.text, "1000張以上股東 41→45 人(+4)");
  assert.equal(m.get("H_INSIDER_UP")?.text, "董監持股 47.24%,較前次申報 +0.24 個百分點(08 月資料)");
  assert.equal(m.get("H_PLEDGE_HIGH")?.text, "董監質押比 40%(08 月資料)");
  const dd = `${hh[0].t.slice(5, 7)}/${hh[0].t.slice(8, 10)}`;
  assert.ok(fs.every((f) => f.dataDate === dd && !f.mirrors && f.source === "holders"));
  // 百分點片段有顏色
  assert.deepEqual(m.get("H_MAJOR400_UP")?.segments?.find((s) => s.kind), { t: "+0.40 個百分點", kind: "up" });
});

test("空方:400 張減 ≥0.5 → rank 5;1000 張反向增另列;散戶增;董監減", () => {
  const fs = holdersFacts(holdersBear(), undefined, null);
  const m = new Map(fs.map((f) => [f.code, f]));
  assert.equal(m.get("H_MAJOR400_DOWN")?.text, "400張以上大戶持股 76.00%,週減 −0.60 個百分點");
  assert.equal(m.get("H_MAJOR400_DOWN")?.rank, 5);
  assert.equal(m.get("H_MAJOR1000_UP")?.text, "1000張以上大戶持股 71.20%,週增 +0.60 個百分點");
  assert.equal(m.get("H_RETAIL_UP")?.side, "bear");
  assert.equal(m.get("H_INSIDER_DOWN")?.text, "董監持股 46.90%,較前次申報 −0.30 個百分點");
});

test("1000 張與 400 張同向且 <0.5 個百分點 → 不另列;資料不足或舊 JSON → []", () => {
  const hh = holdersBull().map((p, i) => ({ ...p, thresholds: { ...p.thresholds, "1000": { holders: 45, shares_pct: i === 0 ? 70.4 : 70 } } }));
  assert.ok(!holdersFacts(hh, undefined, null).some((f) => f.code.startsWith("H_MAJOR1000")));
  assert.deepEqual(holdersFacts(undefined, undefined, undefined), []);
  assert.deepEqual(holdersFacts(holdersBull().slice(0, 1), undefined, null), []);
});
