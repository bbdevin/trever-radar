// 執行: node --test web/lib/scoreList.test.ts
//
// 綜合榜空的時候有兩種意思,句子不可以互換(見 scoreList.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import { scoreListEmptyText } from "./scoreList.ts";

const META = {
  min_final: 65,
  scored: 506,
  missing_branch: 506,
  missing_inst: 506,
  withheld: true,
  max_final: 78,
};

test("扣留時講「尚未到齊」,不講「沒有任何一檔達標」", () => {
  const text = scoreListEmptyText(META)!;
  assert.match(text, /尚未到齊/);
  assert.match(text, /506 檔中,缺分點 506 檔、缺法人 506 檔/);
  assert.doesNotMatch(text, /沒有任何一檔/);
  // 扣留時的最高分算在缺資料的列上,不可以拿出來講。
  assert.doesNotMatch(text, /78/);
});

test("資料齊全而沒人達標時,講門檻與當日最高分", () => {
  const text = scoreListEmptyText({ ...META, withheld: false, missing_branch: 0, missing_inst: 0, max_final: 61 })!;
  assert.match(text, /資料已到齊/);
  assert.match(text, /達 65 分/);
  assert.match(text, /最高 61 分/);
  assert.doesNotMatch(text, /尚未到齊/);
});

test("門檻從 payload 讀,不寫死", () => {
  const text = scoreListEmptyText({ ...META, withheld: false, min_final: 70 })!;
  assert.match(text, /達 70 分/);
});

test("資料齊全但最高分缺席時不編造最高分", () => {
  const text = scoreListEmptyText({ ...META, withheld: false, max_final: null })!;
  assert.doesNotMatch(text, /最高/);
});

test("一列評分都沒有時(export 判為扣留)講「尚未產生」,不講「沒有任何一檔」", () => {
  const text = scoreListEmptyText({
    ...META, withheld: true, scored: 0, missing_branch: 0, missing_inst: 0, max_final: null,
  })!;
  assert.match(text, /尚未產生/);
  assert.doesNotMatch(text, /沒有任何一檔/);
  assert.doesNotMatch(text, /0 檔/);
});

test("舊 payload 沒有 meta → null,由呼叫端沿用原句,不猜", () => {
  assert.equal(scoreListEmptyText(undefined), null);
  assert.equal(scoreListEmptyText(null), null);
});
