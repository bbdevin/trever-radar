// 執行: node --test web/lib/freshness.test.ts
//
// 這組測試存在的理由:一個驗證者去追了一條沒人指給它的路徑,發現把 futures
// 加進 FRESH_LABEL 時漏掉了徽章的過濾器,於是期貨一旦真的落後,畫面會印出
// 「個股期貨今日尚未公布」——一句與 docs/38 §7.12 自己的規則正面衝突的話。
// 那個缺陷當時是休眠的(常態落後一天不算 stale),測試不到就會一直休眠到某天醒來。
import assert from "node:assert/strict";
import { test } from "node:test";

import { staleAutoFills, staleFreshnessLines } from "./freshness.ts";

const D = (date: string, stale: boolean) => ({ date, stale });

test("期貨的句子不講「今日」——它結構上永遠沒有今天的資料", () => {
  const lines = staleFreshnessLines({ futures: D("2026-09-16", true) } as never);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].key, "futures");
  assert.ok(!lines[0].text.includes("今日"),
    `期貨句子不得出現「今日」:${lines[0].text}`);
  assert.ok(lines[0].text.includes("2026-09-16"), "要講出它實際停在哪一天");
  assert.ok(lines[0].text.includes("落後於前一交易日"),
    "要講清楚 stale 的意思是落後於前一交易日,不是「今天還沒到」");
});

test("其他資料集維持原本的「今日尚未公布」措辭", () => {
  const lines = staleFreshnessLines({ margin: D("2026-09-18", true) } as never);
  assert.equal(lines[0].text, "融資券今日尚未公布，暫用 2026-09-18");
});

test("quotes 一律不進徽章", () => {
  const lines = staleFreshnessLines({
    quotes: D("2026-09-18", true), branch: D("2026-09-18", true),
  } as never);
  assert.deepEqual(lines.map((l) => l.key), ["branch"]);
});

test("不 stale 或沒有日期的都不進", () => {
  const lines = staleFreshnessLines({
    futures: D("2026-09-18", false),
    branch: { date: null, stale: true },
  } as never);
  assert.deepEqual(lines, []);
});

test("只有期貨落後時,不講「分批自動更新」——那是它做不到的承諾", () => {
  const lines = staleFreshnessLines({ futures: D("2026-09-16", true) } as never);
  assert.equal(staleAutoFills(lines), false);
});

test("有別的資料集時仍然講那句", () => {
  const lines = staleFreshnessLines({
    futures: D("2026-09-16", true), margin: D("2026-09-18", true),
  } as never);
  assert.equal(staleAutoFills(lines), true);
});

test("沒有 freshness 欄位時回空陣列,不炸", () => {
  assert.deepEqual(staleFreshnessLines(undefined), []);
});
