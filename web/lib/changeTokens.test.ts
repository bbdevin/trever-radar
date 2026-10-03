// 執行: node --test web/lib/changeTokens.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { changeTokens } from "./changeTokens.ts";

const kinds = (s: string) => changeTokens(s).filter((t) => t.kind !== "text").map((t) => [t.kind, t.text]);

test("期貨舉旗後那一行:價格粗體、漲跌紅綠、0.0% 中性", () => {
  const s = "現貨收盤 123.5 → 130.0（+5.3%，6 個交易日後）；期間最高 +9.3%／最低 −2.8%（未扣除權息）";
  assert.deepEqual(kinds(s), [
    ["price", "123.5"], ["price", "130.0"], ["up", "+5.3%"], ["up", "+9.3%"], ["down", "−2.8%"],
  ]);
  assert.deepEqual(kinds("最低 0.0%"), [["flat", "0.0%"]]);
  assert.deepEqual(kinds("最低 -1.2%"), [["down", "-1.2%"]]);
});

test("以動詞表方向的漲跌與高於/低於計數", () => {
  assert.deepEqual(kinds("第二個交易日漲 ≥3% 81 次、跌 ≥3% 112 次"), [["up", "漲 ≥3%"], ["down", "跌 ≥3%"]]);
  assert.deepEqual(kinds("目前高於舉旗日收盤 2 檔、低於 3 檔、持平 0 檔"), [
    ["up", "高於舉旗日收盤 2 檔"], ["down", "低於 3 檔"],
  ]);
});

test("整數計數與日期不被當成價格;文字完整還原", () => {
  const s = "回測 551 次，2026-10-02，6 個交易日後";
  assert.deepEqual(kinds(s), []);
  const t = "現貨收盤 1,085.00 → 1,120.5（+3.2%）";
  assert.equal(changeTokens(t).map((x) => x.text).join(""), t);
  assert.deepEqual(kinds(t), [["price", "1,085.00"], ["price", "1,120.5"], ["up", "+3.2%"]]);
});
