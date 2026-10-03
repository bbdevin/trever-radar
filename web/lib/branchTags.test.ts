// 執行: node --test web/lib/branchTags.test.ts
//
// 籌碼日報分點標籤的純邏輯(見 branchTags.ts)。
import assert from "node:assert/strict";
import { test } from "node:test";

import { compactSide, normalizeBranchPctile, seatKind } from "./branchPctile.ts";
import {
  MAX_VISIBLE_PHONE,
  MAX_VISIBLE_WIDE,
  TAG_PRIORITY,
  TRACKED_OVERRIDE_NOTE,
  branchTags,
  tagDefinitions,
  tagLegendFootnote,
  type TagContext,
} from "./branchTags.ts";
import { effectiveTracked } from "./branchTrackResolve.ts";

function row(name: string, values: Record<string, number | null> = {}) {
  return {
    branch_name: name,
    buy_pctile_known: 11, buy_pctile_unknown: 0, low_buy_count: 7,
    sell_pctile_known: 7, sell_pctile_unknown: 0, high_sell_count: 2,
    buy_lots_known: 2350, low_buy_lots: 1318, sell_lots_known: 400, high_sell_lots: 80,
    ...values,
  };
}

function camp(rows: ReturnType<typeof row>[]) {
  return { available: true, branches: rows };
}

const PCTILE = {
  version: 2,
  ranking: "lots_shrunk_v2",
  min_known_episodes_per_side: 5,
  max_branches: 30,
  windows: { short: 20, long: 120 },
  low_buy_max_pctile: 0.4,
  high_sell_min_pctile: 0.6,
  short: camp([
    row("凱基-新竹"),
    // 賣側紀錄不足:賣超名單上不得出現「賣高」。
    row("元大-竹科", { sell_pctile_known: 2, high_sell_count: 1 }),
  ]),
  long: camp([row("富邦-台北", { low_buy_lots: 100, buy_lots_known: 1000 })]),
  lookup_fields: ["branch_name"],
  lookup: [],
};

const TAGS = {
  as_of: "2026-10-02",
  geo: { rule: "city" as const, names: ["凱基-新竹", "元大-竹科"] },
  daytrade: { min_obs: 8, rate: 0.6, payback: 0.7, rows: { "凱基-新竹": [12, 9] as [number, number] } },
  tracked: ["凱基-新竹", "富邦-台北"],
};

function ctx(tags: unknown = TAGS, pctile: unknown = PCTILE): TagContext {
  return {
    tags: tags as TagContext["tags"],
    pctile: normalizeBranchPctile(pctile),
    seatKind,
    compactSide,
  };
}

test("優先序:地緣 > 隔日沖 > 追蹤 > 買低/賣高 > 總公司外資", () => {
  const tags = branchTags("凱基-新竹", "buy", ctx());
  assert.deepEqual(tags.map((t) => t.code), ["GEO", "DT", "TRACKED", "LOW"]);
  assert.deepEqual(TAG_PRIORITY, ["GEO", "DT", "TRACKED", "LOW", "HIGH", "SEAT"]);
  assert.equal(MAX_VISIBLE_PHONE, 2);
  assert.equal(MAX_VISIBLE_WIDE, 3);
});

test("數字跟著說明走", () => {
  const tags = branchTags("凱基-新竹", "buy", ctx());
  const dt = tags.find((t) => t.code === "DT")!;
  assert.equal(dt.label, "隔日沖");
  assert.ok(dt.note.startsWith("隔日沖：9/12 次合格買超在次日前 15 大賣超中看得到回吐"));
  const low = tags.find((t) => t.code === "LOW")!;
  assert.equal(low.label, "買低 56%");
  assert.equal(low.note, "買低 56%：買進 1,318/2,350 張在近 20 日區間 ≤40%，是進出位置不是賺賠");
  assert.ok(tags.find((t) => t.code === "GEO")!.note.includes("同縣市"));
});

test("看哪一側:買超名單標買低、賣超名單標賣高,紀錄不足不標", () => {
  assert.ok(branchTags("凱基-新竹", "buy", ctx()).some((t) => t.code === "LOW"));
  assert.ok(!branchTags("凱基-新竹", "buy", ctx()).some((t) => t.code === "HIGH"));
  const sell = branchTags("凱基-新竹", "sell", ctx());
  assert.equal(sell.find((t) => t.code === "HIGH")?.label, "賣高 20%");
  assert.ok(!sell.some((t) => t.code === "LOW"));
  assert.ok(!branchTags("元大-竹科", "sell", ctx()).some((t) => t.code === "HIGH"));
  // 只在長線派清單裡 → 用長線派的窗口
  const longOnly = branchTags("富邦-台北", "buy", ctx()).find((t) => t.code === "LOW")!;
  assert.ok(longOnly.note.includes("近 120 日"));
});

test("舊 JSON(沒有 branch_tags、沒有分位計數)→ 一般分點什麼都不標", () => {
  const old = ctx(null, null);
  assert.deepEqual(branchTags("凱基-新竹", "buy", old), []);
  assert.deepEqual(branchTags("凱基-新竹", "sell", old), []);
  // 席位只看名稱,舊 JSON 也照標(既有行為)。
  assert.deepEqual(branchTags("凱基", "buy", old).map((t) => t.code), ["SEAT"]);
});

test("沒有判定就不標,絕不出現反面", () => {
  const tags = branchTags("永豐-板橋", "buy", ctx());
  assert.deepEqual(tags, []);
  const broken = ctx({ ...TAGS, daytrade: { min_obs: 8, rate: 0.6, rows: { "凱基-新竹": [0, 0] } } });
  assert.ok(!branchTags("凱基-新竹", "buy", broken).some((t) => t.code === "DT"));
  const noRule = ctx({ ...TAGS, geo: { rule: null, names: ["凱基-新竹"] } });
  assert.ok(!branchTags("凱基-新竹", "buy", noRule).some((t) => t.code === "GEO"));
  for (const t of branchTags("凱基-新竹", "buy", ctx())) {
    assert.ok(!/^非/.test(t.label), t.label);
  }
});

test("總公司/外資排最後", () => {
  const tags = branchTags("凱基", "buy", ctx({ ...TAGS, tracked: ["凱基"] }));
  assert.deepEqual(tags.map((t) => t.code), ["TRACKED", "SEAT"]);
});

test("定義與說明不得出現被禁的詞", () => {
  // 用字碼組字,避免本測試檔自己被 test_label_honesty 掃到。
  const word = (...codes: number[]) => String.fromCharCode(...codes);
  const banned = new RegExp([
    word(0x52dd, 0x7387),
    word(0x5831, 0x916c),
    word(0x7372, 0x5229),
    word(0x95dc, 0x9375, 0x5206, 0x9ede),
    word(0x4fdd, 0x8b49),
  ].join("|"));
  const texts: string[] = [];
  for (const name of ["凱基-新竹", "元大-竹科", "富邦-台北", "凱基", "美商高盛"]) {
    for (const side of ["buy", "sell"] as const) {
      for (const t of branchTags(name, side, ctx())) texts.push(t.label, t.note);
    }
  }
  for (const d of tagDefinitions(ctx())) texts.push(d.label, d.text);
  texts.push(tagLegendFootnote(ctx()));
  assert.ok(texts.length > 20);
  for (const text of texts) assert.ok(!banned.test(text), text);
  assert.ok(banned.test(`${word(0x52dd, 0x7387)} 60%`), "regex 本身有效");
});

test("全站名單覆寫:取消追蹤拿掉「追蹤」,管理員加入的補上,規則和 effectiveTracked 一致", () => {
  const withUser = (muted: string[], added: string[]): TagContext => ({
    ...ctx(),
    listMuted: new Set(muted),
    listAdded: new Set(added),
  });
  const has = (name: string, c: TagContext) => branchTags(name, "buy", c).some((t) => t.code === "TRACKED");
  // 系統名單裡的(手動種子或自動入選都一樣)被 mute → 不標
  assert.ok(has("凱基-新竹", ctx()));
  assert.ok(!has("凱基-新竹", withUser(["凱基-新竹"], [])));
  assert.ok(!has("富邦-台北", withUser(["富邦-台北"], [])));
  // 系統名單外、管理員加入 → 標,說明講清楚是管理員加的
  assert.ok(!has("永豐-板橋", ctx()));
  const added = branchTags("永豐-板橋", "buy", withUser([], ["永豐-板橋"])).find((t) => t.code === "TRACKED")!;
  assert.ok(added.note.includes("管理員加入"));
  // 舊 JSON 沒有 branch_tags,管理員加入的照樣標
  assert.ok(has("永豐-板橋", { ...ctx(null, null), listAdded: new Set(["永豐-板橋"]) }));
  // 和 branchTrackResolve.effectiveTracked 對照
  for (const name of ["凱基-新竹", "富邦-台北", "永豐-板橋"]) {
    for (const [m, a] of [[[], []], [[name], []], [[], [name]]] as [string[], string[]][]) {
      const server = TAGS.tracked.includes(name);
      assert.equal(has(name, withUser(m, a)), effectiveTracked(name, server, new Set(m), new Set(a)), `${name} ${m} ${a}`);
    }
  }
  // 圖例說明名單由誰維護
  const def = tagDefinitions(ctx()).find((d) => d.label === "追蹤")!;
  assert.ok(def.text.endsWith(TRACKED_OVERRIDE_NOTE));
  assert.equal(TRACKED_OVERRIDE_NOTE, "追蹤名單由管理員設定，全站一致。");
});

test("定義的數字從 payload 讀", () => {
  const defs = tagDefinitions(ctx({ ...TAGS, daytrade: { min_obs: 10, rate: 0.5, rows: {} } }));
  const dt = defs.find((d) => d.label === "隔日沖")!;
  assert.ok(dt.text.includes("至少 10 次"));
  assert.ok(dt.text.includes("≥50%"));
  assert.ok(tagLegendFootnote(ctx()).startsWith("標籤資料日 10/2"));
  // 沒有 branch_tags:不列地緣/隔日沖/追蹤的定義,也不印資料日。
  const old = tagDefinitions(ctx(null, null)).map((d) => d.label);
  assert.deepEqual(old, ["總公司／外資"]);
  assert.ok(!tagLegendFootnote(ctx(null, null)).includes("資料日"));
});
