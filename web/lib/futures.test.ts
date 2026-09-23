// 無 React test runner(package.json 無 vitest/jest)時的既有替代作法:
// 把判斷抽成純函式,直接用 Node 內建 test runner 測(比照 scripts/verify-*.mjs
// 用純 node 執行、不進 npm scripts 的慣例)。
// 執行: node --test web/lib/futures.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  anomalyEmptyStateText,
  anomalyFacts,
  anomalyLagText,
  contractsWithDaily,
  contractsWithoutDaily,
  dailyFacts,
  flaggedContracts,
  futuresAnomalyMarketState,
  futuresOpenInterestDirectionState,
  futuresState,
  noDailyRowText,
  openInterestDirectionText,
} from "./futures.ts";

test("futures 鍵不存在 -> unknown(尚未 import,不可讀成沒有)", () => {
  assert.deepEqual(futuresState(undefined), { kind: "unknown" });
  assert.deepEqual(futuresState(null), { kind: "unknown" });
});

test("contracts 是空陣列 -> none,帶 list_as_of 日期(正面主張,不是缺資料)", () => {
  const state = futuresState({ version: 1, list_as_of: "2026-09-11", contracts: [] });
  assert.deepEqual(state, { kind: "none", asOf: "2026-09-11" });
});

test("contracts 非空 -> has,原樣帶出契約清單", () => {
  const contracts = [
    { code: "CDF", is_futures: true, is_option: false, is_weekly_option: false },
    { code: "CDO", is_futures: false, is_option: true, is_weekly_option: false },
  ];
  const state = futuresState({ version: 1, list_as_of: "2026-09-11", contracts });
  assert.deepEqual(state, { kind: "has", asOf: "2026-09-11", contracts });
});

test("unknown 與 none 不可塌成同一種表示(這個功能唯一要守住的事)", () => {
  const unknown = futuresState(undefined);
  const none = futuresState({ version: 1, list_as_of: "2026-09-11", contracts: [] });
  assert.notDeepEqual(unknown, none);
});

// ---- docs/38 §7:成交量異常的呈現 ----

const ANOMALY_MYF = { today: 320, window_max: 140, window_median: 45, window_days: 60, oi_change: 210 };
const ANOMALY_OMF = { today: 1200, window_max: 900, window_median: 300, window_days: 60 }; // 無 oi_change
const REASONS = [{ code: "F1_FUTURES_VOLUME_60D_HIGH", text: "創 60 個比較日新高" }];
const RISKS = [{ code: "R_FUTURES_VOLUME_NO_DIRECTION", text: "量創高不代表方向" }];

const entry = (stock_id: string, code: string, anomaly: typeof ANOMALY_MYF | typeof ANOMALY_OMF) => ({
  stock_id,
  code,
  anomaly,
  reasons: REASONS,
  risks: RISKS,
});

// 期貨行情日(2026-09-17)刻意**不等於**頁面的資料日(2026-09-18):production
// 的常態就是差一個交易日,而這個功能上線後從來沒有顯示過,正是因為兩者被當成
// 同一天(docs/38 §7.12)。
const META = { as_of: "2026-09-17", window_days: 60 };

test("§7.5 市場層級鍵的三態:缺鍵 / 空陣列 / 非空,三者互不相同", () => {
  const notComputed = futuresAnomalyMarketState(undefined, "2026-09-18", undefined, META);
  const computedEmpty = futuresAnomalyMarketState([], "2026-09-18", undefined, META);
  const listed = futuresAnomalyMarketState([entry("1565", "MYF", ANOMALY_MYF)], "2026-09-18");

  assert.deepEqual(notComputed, { kind: "not-computed" });
  assert.deepEqual(computedEmpty, {
    kind: "computed-empty",
    dataDate: "2026-09-18",
    asOf: "2026-09-17",
    windowDays: 60,
  });
  assert.equal(listed.kind, "listed");
  assert.notDeepEqual(notComputed, computedEmpty);
});

test("§7.12 期貨行情日只能來自 payload,不得用頁面的資料日頂替", () => {
  const listed = futuresAnomalyMarketState(
    [entry("1565", "MYF", ANOMALY_MYF)], "2026-09-18", undefined, META,
  );
  if (listed.kind !== "listed") throw new Error("expected listed");
  assert.equal(listed.asOf, "2026-09-17");
  assert.equal(listed.dataDate, "2026-09-18");
  // meta 沒給日期(舊 payload)→ null,**不是** dataDate。
  const noMeta = futuresAnomalyMarketState([], "2026-09-18", undefined, { window_days: 60 });
  if (noMeta.kind !== "computed-empty") throw new Error("expected computed-empty");
  assert.equal(noMeta.asOf, null);
});

test("§7.12 兩個日期不同才講落差,而且不說「一天」(前端沒有交易日曆)", () => {
  const text = anomalyLagText("2026-09-17", "2026-09-18");
  assert.equal(text, "期貨行情日 2026-09-17;本頁其他資料為 2026-09-18。");
  assert.ok(!text!.includes("一天"), text!);
  assert.ok(!text!.includes("落後"), text!);
  // 同一天就沒有這句話;日期未知時也沒有——沒有日期就沒有落差可講。
  assert.equal(anomalyLagText("2026-09-18", "2026-09-18"), null);
  assert.equal(anomalyLagText(null, "2026-09-18"), null);
});

// ---- docs/38 §7.11:空名單那一態自己講得出比較窗口 ----

test("§7.11 空陣列 + meta -> windowDays 從 payload 讀出來,前端不寫死 60", () => {
  const state = futuresAnomalyMarketState([], "2026-09-18", undefined, { window_days: 20 });
  if (state.kind !== "computed-empty") throw new Error("expected computed-empty");
  // 60 寫死的話,餵 20 也會得到 60——這裡就是那把鎖。
  assert.equal(state.windowDays, 20);
});

test("§7.10 meta 缺席時是 null:少講一段,不得退回一個寫死的 60", () => {
  for (const meta of [undefined, null]) {
    const state = futuresAnomalyMarketState([], "2026-09-18", undefined, meta);
    if (state.kind !== "computed-empty") throw new Error("expected computed-empty");
    assert.equal(state.windowDays, null);
  }
});

test("§7.11 空名單那句話會講出比較窗口,而且數字來自 payload", () => {
  assert.equal(
    anomalyEmptyStateText({ asOf: "2026-09-17", windowDays: 60 }),
    "期貨 2026-09-17 已完成計算:沒有契約的一般時段成交量創 60 個比較日新高。",
  );
  // 換一個窗口長度,句子要跟著變——寫死 60 的話這一行就是紅的。
  assert.equal(
    anomalyEmptyStateText({ asOf: "2026-09-17", windowDays: 20 }),
    "期貨 2026-09-17 已完成計算:沒有契約的一般時段成交量創 20 個比較日新高。",
  );
});

test("§7.12 這句話講的是期貨行情日,而且不出現「今日 / 今天」", () => {
  const text = anomalyEmptyStateText({ asOf: "2026-09-17", windowDays: 60 });
  assert.ok(text.startsWith("期貨 2026-09-17 已完成計算"), text);
  assert.ok(!text.includes("今日"), text);
  assert.ok(!text.includes("今天"), text);
  // 日期讀不到(舊 payload)時少講日期,不得拿別的日子頂上。
  const undated = anomalyEmptyStateText({ asOf: null, windowDays: 60 });
  assert.equal(undated, "已完成計算:沒有契約的一般時段成交量創 60 個比較日新高。");
  assert.ok(!undated.includes("2026"), undated);
});

test("§7.10 窗口未知時整段子句拿掉,句子裡不得出現任何數字當比較基準", () => {
  const text = anomalyEmptyStateText({ asOf: "2026-09-17", windowDays: null });
  assert.equal(text, "期貨 2026-09-17 已完成計算:沒有契約的一般時段成交量創新高。");
  assert.ok(!text.includes("60"), text);
  assert.ok(!text.includes("比較日"), text);
  // 但它仍然是一個帶日期的正面主張(§7.5 第二態),日期不可以掉。
  assert.ok(text.startsWith("期貨 2026-09-17 已完成計算"), text);
});

test("§7.5 meta 不得把「沒有算過」講成「算過了、今天沒有」", () => {
  // meta 給了而名單缺鍵(payload 不該出現的組合,但前端不可以因此改口)。
  const state = futuresAnomalyMarketState(undefined, "2026-09-18", undefined, META);
  assert.deepEqual(state, { kind: "not-computed" });
  assert.deepEqual(Object.keys(state), ["kind"]);
});

test("§7.5 缺鍵不得帶日期:沒有算過就沒有任何主張可以繫在哪一天上", () => {
  const notComputed = futuresAnomalyMarketState(null, "2026-09-18");
  assert.deepEqual(Object.keys(notComputed), ["kind"]);
});

test("§7.1/§7.4 oi_change 有值時是一列,缺鍵時整列不顯示(不是 0、不是破折號)", () => {
  const withOi = anomalyFacts(ANOMALY_MYF);
  const withoutOi = anomalyFacts(ANOMALY_OMF);

  assert.deepEqual(withOi.map((f) => f.key), ["today", "window_max", "window_median", "oi_change"]);
  assert.deepEqual(withoutOi.map((f) => f.key), ["today", "window_max", "window_median"]);
  assert.equal(withOi.find((f) => f.key === "oi_change")?.value, "+210");
  // 缺鍵那一列不存在,而且沒有人用 "0"/"—"/"未公布" 之類的字把它頂起來。
  for (const f of withoutOi) {
    assert.ok(!["0", "—", "-", "未公布"].includes(f.value), `不得用 ${f.value} 頂替缺值`);
  }
});

test("§7.1 oi_change = 0 是一個真的觀測,要顯示 0(與缺鍵不同)", () => {
  const facts = anomalyFacts({ ...ANOMALY_MYF, oi_change: 0 });
  assert.equal(facts.find((f) => f.key === "oi_change")?.value, "0");
});

test("§7.10 window_days 從區塊讀,不寫死 60", () => {
  const facts = anomalyFacts({ today: 9, window_max: 8, window_median: 2, window_days: 20 });
  const labels = facts.map((f) => f.label).join(" ");
  assert.ok(labels.includes("前 20 個比較日"), labels);
  assert.ok(!labels.includes("60"), labels);
});

test("§7.12 事實列的標籤不得出現「今日 / 今天」——那一天不是使用者的今天", () => {
  for (const f of anomalyFacts(ANOMALY_MYF)) {
    assert.ok(!f.label.includes("今日"), f.label);
    assert.ok(!f.label.includes("今天"), f.label);
  }
  assert.equal(anomalyFacts(ANOMALY_MYF)[0].label, "一般時段成交");
});

test("§5 不算比率、不給名次:每個顯示值都是區塊裡原本那個整數", () => {
  const facts = anomalyFacts(ANOMALY_MYF);
  const allowed = new Set([320, 140, 45, 210]);
  for (const f of facts) {
    const n = Number(f.value.replace(/[,+]/g, ""));
    assert.ok(allowed.has(n), `${f.key} 的值 ${f.value} 不是 payload 裡的整數`);
  }
  // 3.2x / 711% / 第 1 名 這類東西不可能從這裡長出來。
  assert.equal(facts.length, 4);
});

test("§5 名單列不得帶 rank / position / score / ratio 之類的鍵", () => {
  const state = futuresAnomalyMarketState(
    [entry("1565", "MYF", ANOMALY_MYF), entry("2330", "CDF", ANOMALY_OMF)],
    "2026-09-18",
  );
  assert.equal(state.kind, "listed");
  if (state.kind !== "listed") return;
  for (const row of state.rows) {
    assert.deepEqual(Object.keys(row).sort(), ["code", "facts", "name", "reasons", "risks", "stockId"]);
  }
});

test("§7.5 順序原封不動照 payload,前端不重排", () => {
  const a = entry("2330", "CDF", ANOMALY_OMF); // today − window_max = 300
  const b = entry("1565", "MYF", ANOMALY_MYF); // today − window_max = 180
  const state = futuresAnomalyMarketState([a, b], "2026-09-18");
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.deepEqual(state.rows.map((r) => r.code), ["CDF", "MYF"]);
  // 反過來餵也照樣原封不動——證明這裡真的沒有排序。
  const flipped = futuresAnomalyMarketState([b, a], "2026-09-18");
  if (flipped.kind !== "listed") throw new Error("expected listed");
  assert.deepEqual(flipped.rows.map((r) => r.code), ["MYF", "CDF"]);
});

test("§0/§7.10 同一檔股票的兩個契約都要活到名單上,不得依股票去重", () => {
  const state = futuresAnomalyMarketState(
    [entry("1565", "MYF", ANOMALY_MYF), entry("1565", "OMF", ANOMALY_OMF)],
    "2026-09-18",
    new Map([["1565", "精剛"]]),
  );
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.equal(state.rows.length, 2);
  assert.deepEqual(state.rows.map((r) => r.code), ["MYF", "OMF"]);
  assert.deepEqual(state.rows.map((r) => r.stockId), ["1565", "1565"]);
  assert.deepEqual(state.rows.map((r) => r.name), ["精剛", "精剛"]);
});

test("股名解析不到時是 null(顯示 id 本身,不編一個標籤)", () => {
  const state = futuresAnomalyMarketState([entry("9999", "ZZF", ANOMALY_MYF)], "2026-09-18", new Map());
  if (state.kind !== "listed") throw new Error("expected listed");
  assert.equal(state.rows[0].name, null);
});

// ---- docs/38 §7.14:每日事實(每一個契約-日,不只舉旗的那些) ----

const DAILY_FULL = {
  date: "2026-09-17",
  volume: 640,
  open_interest: 1000,
  session_volume: { 一般: 600, 盤後: 40 },
  oi_change: 210,
};

test("§7.14 五列:合計成交、兩個時段、未平倉、未平倉較前日", () => {
  assert.deepEqual(dailyFacts(DAILY_FULL), [
    { key: "volume", label: "一般+盤後合計成交", value: "640", unit: "口" },
    { key: "session:一般", label: "一般時段成交", value: "600", unit: "口" },
    { key: "session:盤後", label: "盤後時段成交", value: "40", unit: "口" },
    { key: "open_interest", label: "未平倉", value: "1,000", unit: "口" },
    { key: "oi_change", label: "未平倉較前日", value: "+210", unit: "口" },
  ]);
});

test("§7.6 合計成交與異常區塊的「一般時段成交」是兩個數字,光看標籤就分得出來", () => {
  // 同一頁上並排的兩列:daily 是 640(一般 600 + 盤後 40),anomaly 是 600(只有一般)。
  const daily = dailyFacts(DAILY_FULL);
  const anomaly = anomalyFacts({ today: 600, window_max: 140, window_median: 45, window_days: 60 });
  const total = daily.find((f) => f.key === "volume")!;
  const regularOnly = anomaly.find((f) => f.key === "today")!;
  assert.notEqual(total.value, regularOnly.value);
  assert.notEqual(total.label, regularOnly.label);
  // 合計那一列的標籤必須自己講出它加了哪些時段——「成交量」三個字擋不住誤讀。
  assert.ok(total.label.includes("一般") && total.label.includes("盤後"), total.label);
  // 而 anomaly 那一列的標籤只講一般時段,不含「盤後」「合計」。
  assert.ok(!regularOnly.label.includes("盤後"), regularOnly.label);
  assert.ok(!regularOnly.label.includes("合計"), regularOnly.label);
  // 同一個數字不得在兩塊之間被當成同一列:一般時段那一列的值才等於 anomaly.today。
  assert.equal(daily.find((f) => f.key === "session:一般")!.value, regularOnly.value);
});

test("§7.1 oi_change 缺鍵 -> 整列不顯示(不是 0、不是破折號、不是「未公布」)", () => {
  const { oi_change: _omitted, ...withoutOi } = DAILY_FULL;
  const keys = dailyFacts(withoutOi).map((f) => f.key);
  assert.ok(!keys.includes("oi_change"), keys.join(","));
  for (const f of dailyFacts(withoutOi)) {
    assert.ok(!f.label.includes("較前日"), f.label);
    assert.ok(!["—", "-", "未公布", "無變化"].includes(f.value), f.value);
  }
});

test("§7.1 oi_change = 0 是一個真的觀測,顯示 0——與缺鍵只差在那一列在不在", () => {
  const zero = dailyFacts({ ...DAILY_FULL, oi_change: 0 });
  assert.equal(zero.find((f) => f.key === "oi_change")?.value, "0");
  const { oi_change: _omitted, ...withoutOi } = DAILY_FULL;
  assert.equal(zero.length, dailyFacts(withoutOi).length + 1);
});

test("§7.14 未平倉是存量:它那兩列不帶任何時段字樣", () => {
  for (const f of dailyFacts(DAILY_FULL)) {
    if (!f.key.startsWith("open_interest") && f.key !== "oi_change") continue;
    assert.ok(!f.label.includes("一般"), f.label);
    assert.ok(!f.label.includes("盤後"), f.label);
    assert.ok(!f.label.includes("時段"), f.label);
  }
});

test("缺席的時段不補 0:只列出真的有列的那些(補 0 = 謊報沒人交易)", () => {
  const facts = dailyFacts({ ...DAILY_FULL, volume: 600, session_volume: { 一般: 600 } });
  assert.deepEqual(facts.map((f) => f.key),
    ["volume", "session:一般", "open_interest", "oi_change"]);
});

test("時段順序固定:一般在盤後之前,不隨 payload 的鍵序飄", () => {
  const flipped = dailyFacts({ ...DAILY_FULL, session_volume: { 盤後: 40, 一般: 600 } });
  assert.deepEqual(
    flipped.filter((f) => f.key.startsWith("session:")).map((f) => f.key),
    ["session:一般", "session:盤後"],
  );
});

test("volume / open_interest 是 null 時整列不顯示,不是 0", () => {
  const facts = dailyFacts({
    date: "2026-09-17", volume: null, open_interest: null, session_volume: {},
  });
  assert.deepEqual(facts, []);
});

test("§1 不算比率、不算差值:每個顯示值都是 payload 裡原本那個整數", () => {
  const allowed = new Set([640, 600, 40, 1000, 210]);
  for (const f of dailyFacts(DAILY_FULL)) {
    const n = Number(f.value.replace(/[,+]/g, ""));
    assert.ok(allowed.has(n), `${f.key} 的值 ${f.value} 不是 payload 裡的整數`);
  }
});

test("§7.12 每日事實的標籤不得出現「今日 / 今天」——那一天不是使用者的今天", () => {
  for (const f of dailyFacts(DAILY_FULL)) {
    assert.ok(!f.label.includes("今日"), f.label);
    assert.ok(!f.label.includes("今天"), f.label);
  }
});

test("§7.14 有 daily 就入列,與有沒有舉旗無關;沒有 daily 的不入列也不算「正常」", () => {
  const contracts = [
    { code: "MYF", is_futures: true, is_option: false, is_weekly_option: false, daily: DAILY_FULL },
    // 沒有 anomaly,但有 daily —— 這正是這個功能要補的那 ~248 檔。
    { code: "OMF", is_futures: true, is_option: false, is_weekly_option: false, daily: { ...DAILY_FULL, volume: 12 } },
    { code: "MYO", is_futures: false, is_option: true, is_weekly_option: false, anomaly: ANOMALY_MYF },
  ];
  assert.deepEqual(contractsWithDaily(contracts).map((c) => c.code), ["MYF", "OMF"]);
  // 舉旗但沒有 daily 的契約不在這一塊裡(它在異常區塊裡),而且沒有被標成任何狀態。
  assert.equal(contractsWithDaily([contracts[2]]).length, 0);
  assert.equal(flaggedContracts(contracts).length, 1);
});

test("個股頁:只有帶 anomaly 的契約進清單,兩個契約都舉旗時兩個都在", () => {
  const contracts = [
    { code: "MYF", is_futures: true, is_option: false, is_weekly_option: false, anomaly: ANOMALY_MYF },
    { code: "OMF", is_futures: true, is_option: false, is_weekly_option: false, anomaly: ANOMALY_OMF },
    { code: "MYO", is_futures: false, is_option: true, is_weekly_option: false },
  ];
  assert.deepEqual(flaggedContracts(contracts).map((c) => c.code), ["MYF", "OMF"]);
  // 沒有 anomaly 的那個被排除,但**沒有**被標成「正常」——它根本不進這個清單(§7.7)。
  assert.equal(flaggedContracts([contracts[2]]).length, 0);
});

// ---- docs/38 §7.15(一):沒有 daily 的契約,把缺席講成缺席 ----

test("§7.15 沒有 daily 的契約被挑出來(它們在此之前在畫面上完全不存在)", () => {
  const contracts = [
    { code: "MYF", is_futures: true, is_option: false, is_weekly_option: false, daily: DAILY_FULL },
    { code: "OMF", is_futures: true, is_option: false, is_weekly_option: false },
    { code: "MYO", is_futures: false, is_option: true, is_weekly_option: false, anomaly: ANOMALY_MYF },
  ];
  assert.deepEqual(contractsWithoutDaily(contracts).map((c) => c.code), ["OMF", "MYO"]);
  // 兩個函式是互補的:每一個契約恰好落在其中一邊,沒有契約消失。
  assert.equal(
    contractsWithDaily(contracts).length + contractsWithoutDaily(contracts).length,
    contracts.length,
  );
});

test("§7.15 那句話只陳述缺席:代碼、日期、沒有列,沒有第四件事", () => {
  assert.equal(noDailyRowText("OMF", "2026-09-17"), "OMF 在 2026-09-17 沒有列。");
});

test("§7.7/R1 那句話不得指名成因,也不得說成「正常」", () => {
  const text = noDailyRowText("OMF", "2026-09-17");
  // 未掛牌 / 未公布 / 匯入失敗三者不可分辨,挑一個講就是替資料做一個它支持不了的選擇。
  for (const forbidden of ["未公布", "未上市", "未掛牌", "匯入", "失敗", "尚未"]) {
    assert.ok(!text.includes(forbidden), `${forbidden} in ${text}`);
  }
  // §7.7 明文:不得把缺席標成「正常」;「無交易」同樣是一個沒人做過的主張。
  for (const forbidden of ["正常", "無交易", "沒有交易"]) {
    assert.ok(!text.includes(forbidden), `${forbidden} in ${text}`);
  }
  // 也沒有任何一個數字冒充那個缺席的數量(0 口 / 0 張):日期以外一個數字都沒有。
  assert.equal(text.replace("2026-09-17", ""), "OMF 在  沒有列。");
});

test("§7.12 那句話的日期是期貨行情日,而且句子裡沒有「今日 / 今天」", () => {
  const text = noDailyRowText("OMF", "2026-09-17");
  assert.ok(text.includes("2026-09-17"));
  assert.ok(!text.includes("今日") && !text.includes("今天"), text);
});

// ---- docs/38 §7.15(二):市場層級的未平倉方向計數 ----

const DIRECTION = {
  as_of: "2026-09-17",
  increased: 118,
  decreased: 96,
  unchanged: 14,
  undetermined: 92,
};

test("§7.15 三態:缺鍵 = 沒有算過(不是「今天一個契約都沒動」)", () => {
  assert.deepEqual(futuresOpenInterestDirectionState(undefined), { kind: "not-computed" });
  assert.deepEqual(futuresOpenInterestDirectionState(null), { kind: "not-computed" });
});

test("§7.15 三態:四個計數全是 0 仍然是「數過了」,與缺鍵分得出來", () => {
  const zeros = { as_of: "2026-09-17", increased: 0, decreased: 0, unchanged: 0, undetermined: 0 };
  const counted = futuresOpenInterestDirectionState(zeros);
  assert.deepEqual(counted, { kind: "counted", counts: zeros });
  assert.notDeepEqual(counted, futuresOpenInterestDirectionState(undefined));
});

test("§7.15 那一句話複述四個計數與它們比的是哪一天,一個字不多", () => {
  assert.equal(
    openInterestDirectionText(DIRECTION),
    "期貨 2026-09-17 未平倉較前一個期貨交易日:增加 118 個契約、減少 96 個、持平 14 個、無法判定 92 個。",
  );
});

test("§7.15 每個顯示的數字都是 payload 裡原本那個整數:不算比率、不算淨額、不給總數", () => {
  const text = openInterestDirectionText(DIRECTION);
  const numbers = (text.match(/\d+/g) ?? []).filter((n) => !text.includes(`${n}-`));
  const allowed = new Set(["2026", "09", "17", "118", "96", "14", "92"]);
  for (const n of numbers) assert.ok(allowed.has(n), `${n} 不是 payload 裡的數字:${text}`);
  // 總數(118+96+14+92 = 320)、差額(118−96 = 22)、百分比都不得出現。
  for (const derived of ["320", "22", "%", "成", "倍"]) {
    assert.ok(!text.includes(derived), `${derived} in ${text}`);
  }
});

test("§7.15 描述性:沒有判語、沒有門檻、沒有名次——那需要一份 battery", () => {
  const text = openInterestDirectionText(DIRECTION);
  for (const verdict of ["偏多", "偏空", "多方", "空方", "異常", "不尋常", "訊號",
                         "建議", "第一", "最多", "排名", "門檻"]) {
    assert.ok(!text.includes(verdict), `${verdict} in ${text}`);
  }
  // 契約代碼一個都不出現:§5 不做跨契約排序,連「誰」都不講。
  assert.ok(!text.includes("MYF") && !text.includes("OMF"), text);
});

test("§7.15 「無法判定」即使是 0 也照樣講出來(它與另外三項一樣是一個計數)", () => {
  const text = openInterestDirectionText({ ...DIRECTION, undetermined: 0 });
  assert.ok(text.includes("無法判定 0 個"), text);
});

test("§7.15 判不出來的那些不得被說成「持平」——不知道不是沒有變動", () => {
  const text = openInterestDirectionText({ ...DIRECTION, unchanged: 0, undetermined: 92 });
  assert.ok(text.includes("持平 0 個"), text);
  assert.ok(text.includes("無法判定 92 個"), text);
});

test("§7.15 日期照 payload 走,不編一個出來", () => {
  assert.ok(openInterestDirectionText({ ...DIRECTION, as_of: "2026-06-19" })
    .startsWith("期貨 2026-06-19 "));
});
