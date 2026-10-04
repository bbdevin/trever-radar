// 執行: node --test web/lib/freshness.test.ts
//
// 這組測試存在的理由:一個驗證者去追了一條沒人指給它的路徑,發現把 futures
// 加進 FRESH_LABEL 時漏掉了徽章的過濾器,於是期貨一旦真的落後,畫面會印出
// 「個股期貨今日尚未公布」——一句與 docs/38 §7.12 自己的規則正面衝突的話。
// 那個缺陷當時是休眠的(常態落後一天不算 stale),測試不到就會一直休眠到某天醒來。
import assert from "node:assert/strict";
import { test } from "node:test";

import { FRESH_LABEL, UPDATE_SCHEDULE, scheduleFor, staleAutoFills, staleFreshnessLines } from "./freshness.ts";

const D = (date: string, stale: boolean) => ({ date, stale });

// 2026-10-02 更正:期貨並非「結構上永遠沒有今天的資料」——t 日資料 t 日收盤後就完整,落後是
// OpenAPI 更新慢(docs/38 §7.8 事後修正(三))。2026-10-02 起當日匯入已接上(16:10／17:40／22:00),
// stale 只代表落後超過一個交易日,句子仍不講「今日」。
test("期貨的句子不講「今日」——stale 是連前一交易日都沒跟上", () => {
  const lines = staleFreshnessLines({ futures: D("2026-09-16", true) } as never);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].key, "futures");
  assert.ok(!lines[0].text.includes("今日"),
    `期貨句子不得出現「今日」:${lines[0].text}`);
  assert.ok(lines[0].text.includes("2026-09-16"), "要講出它實際停在哪一天");
  assert.ok(lines[0].text.includes("落後超過一個交易日"),
    "要講清楚 stale 的意思是連前一個交易日都沒跟上,不是「今天還沒到」");
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

test("每一筆待更新都帶出它的排程時間(使用者 2026-10-02 要求)", () => {
  const lines = staleFreshnessLines({
    insti: D("2026-10-01", true), branch: D("2026-10-01", true),
    margin: D("2026-10-01", true), warrant: D("2026-10-01", true),
    futures: D("2026-09-29", true), themes: D("2026-09-21", true),
  } as never);
  const by = Object.fromEntries(lines.map((l) => [l.key, l.schedule]));
  // docs/47 排程優化:各輪是起點,腳本輪詢到公布為止。
  assert.equal(by.insti, "16:00 起輪詢(到齊即上線)");
  assert.equal(by.branch, "17:30 起偵測、齊全即抓");
  assert.equal(by.margin, "20:45 起輪詢");
  assert.equal(by.warrant, "16:00 起(隨法人輪)");
  assert.equal(by.themes, "每週一 11:00");
  // 期貨照實講:16:00 起抓當日,未到齊 17:30、22:30 重試。
  assert.ok(by.futures?.includes("當日"), by.futures);
});

test("手機精簡欄位:名稱、MM-DD、短排程;期貨不講「今日」也不承諾自動補", () => {
  const [margin] = staleFreshnessLines({ margin: D("2026-10-01", true) } as never);
  assert.equal(margin.label, "融資券");
  assert.equal(margin.shortDate, "10-01");
  assert.equal(margin.shortSchedule, "20:45 起輪詢");
  const [fut] = staleFreshnessLines({ futures: D("2026-09-30", true) } as never);
  assert.equal(fut.shortSchedule, "16:00 當日、17:30 補");
  for (const s of UPDATE_SCHEDULE) assert.ok(s.short.length <= 18, `${s.key} 短排程太長:${s.short}`);
});

test("時間表涵蓋徽章可能出現的每一種資料", () => {
  for (const key of Object.keys(FRESH_LABEL)) {
    assert.ok(scheduleFor(key), `${key} 沒有排程時間`);
  }
  assert.ok(UPDATE_SCHEDULE.some((s) => s.key === "quotes"));
});

test("沒有 freshness 欄位時回空陣列,不炸", () => {
  assert.deepEqual(staleFreshnessLines(undefined), []);
});

test("權證部分未到:不說「暫用(今天)」,講幾檔沒到", () => {
  const [w] = staleFreshnessLines({
    warrant: { date: "2026-10-02", stale: true, partial_stale: true, stale_stock_count: 2 },
  } as never);
  assert.equal(w.shortState, "部分未到(2 檔)");
  assert.ok(!w.text.includes("暫用"), w.text);
  const [m] = staleFreshnessLines({ margin: D("2026-10-01", true) } as never);
  assert.equal(m.shortState, "暫用 10-01");
  const [f] = staleFreshnessLines({ futures: D("2026-09-29", true) } as never);
  assert.equal(f.shortState, "停在 09-29");
});