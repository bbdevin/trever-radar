// 執行: node --test --experimental-strip-types web/lib/changelog.test.ts
//
// 版本更新紀錄的資料形狀與用字(見 changelog.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import { CHANGELOG, CURRENT_VERSION, KIND_LABEL, versionParts } from "./changelog.ts";

test("目前版本就是第一筆", () => {
  assert.ok(CHANGELOG.length > 0);
  assert.equal(CURRENT_VERSION, CHANGELOG[0].version);
});

test("版號格式為 主版.次版,且嚴格由新到舊", () => {
  for (const r of CHANGELOG) assert.match(r.version, /^\d+\.\d+$/, r.version);
  const seen = new Set<string>();
  for (const r of CHANGELOG) {
    assert.ok(!seen.has(r.version), `重複版號 ${r.version}`);
    seen.add(r.version);
  }
  for (let i = 1; i < CHANGELOG.length; i++) {
    const [a1, b1] = versionParts(CHANGELOG[i - 1].version);
    const [a2, b2] = versionParts(CHANGELOG[i].version);
    assert.ok(a1 > a2 || (a1 === a2 && b1 > b2), `${CHANGELOG[i - 1].version} 應大於 ${CHANGELOG[i].version}`);
  }
  // 次版是數字比較,不是字串比較
  assert.deepEqual(versionParts("2.10"), [2, 10]);
});

test("日期為 YYYY-MM-DD,由新到舊,同一天只有一版", () => {
  for (const r of CHANGELOG) {
    assert.match(r.date, /^\d{4}-\d{2}-\d{2}$/, r.date);
    assert.ok(!Number.isNaN(Date.parse(r.date)), r.date);
  }
  for (let i = 1; i < CHANGELOG.length; i++) {
    assert.ok(CHANGELOG[i - 1].date > CHANGELOG[i].date, `${CHANGELOG[i - 1].date} 應晚於 ${CHANGELOG[i].date}`);
  }
});

test("每一版都有內容,種類只有新增/改善/修正", () => {
  for (const r of CHANGELOG) {
    assert.ok(r.items.length > 0, r.version);
    for (const it of r.items) {
      assert.ok(it.kind in KIND_LABEL, `${r.version} ${it.kind}`);
      assert.ok(it.text.trim().length > 0, r.version);
    }
    if (r.title != null) assert.ok(r.title.trim().length > 0, r.version);
  }
});

test("更新紀錄不得出現被禁的詞", () => {
  // 用字碼組字,避免本測試檔自己被 test_label_honesty 掃到。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const bannedWords = [
    word(0x52dd, 0x7387), // 勝率
    word(0x7372, 0x5229), // 獲利
    word(0x5831, 0x916c), // 報酬
    word(0x95dc, 0x9375, 0x5206, 0x9ede), // 關鍵分點
    word(0x5927, 0x6f32), // 大漲
    word(0x5674), // 噴
    word(0x6975, 0x54c1), // 極品
    word(0x6a5f, 0x7387), // 機率
    word(0x76ee, 0x6a19, 0x50f9), // 目標價
    word(0x8cb7, 0x9032), // 買進
    word(0x8ce3, 0x51fa), // 賣出
    word(0x770b, 0x591a), // 看多
    word(0x770b, 0x7a7a), // 看空
    word(0x505a, 0x591a), // 做多
    word(0x505a, 0x7a7a), // 做空
    word(0x4fdd, 0x8b49), // 保證
  ];
  const banned = new RegExp(bannedWords.join("|"));
  const texts: string[] = [];
  for (const r of CHANGELOG) {
    if (r.title) texts.push(r.title);
    for (const it of r.items) texts.push(it.text);
  }
  assert.ok(texts.length > 50);
  for (const text of texts) assert.ok(!banned.test(text), text);
  assert.ok(banned.test(`${word(0x52dd, 0x7387)} 60%`), "regex 本身有效");
});
