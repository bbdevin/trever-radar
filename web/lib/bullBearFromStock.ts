/**
 * 個股 JSON → 多空摘要(docs/46)的唯一組裝點。
 *
 * 個股頁「多空」分頁與首頁「多方榜」建置器(web/scripts/build-bull-board.mjs,Node 直接跑 TS)
 * 必須是**同一次呼叫**(docs/48 §1):兩邊各自組 buildBullBear 的參數,遲早會有一邊漏改。
 * 只用相對路徑 import(node 認不得 "@/" 別名),也不 import 任何 React 元件。
 */
import { buildBullBear, type BullBearSummary } from "./bullBear.ts";
import { pocketBadgeVisible } from "./branchTrackResolve.ts";
import { deriveAllFacts } from "./facts/index.ts";
import { legacyReasonText } from "./format.ts";
import { pocketDisplayText } from "./pocketText.ts";
import type { StockJson } from "./types.ts";

const TRACKED_CODES = new Set(["T1_TRACKED_BUY", "K1_KEY_BUY"]);

/** 最後一根 K 棒的日期(多空摘要的資料日);沒有 K 棒時是空字串。 */
export function lastCandleDate(data: Pick<StockJson, "candles">): string {
  const cs = data.candles ?? [];
  return cs[cs.length - 1]?.t ?? "";
}

/**
 * 使用者關掉的追蹤分點(muted),口袋標籤照 PocketBadges 一樣不列;建置器傳空集合
 * (全站共用名單的覆寫只在瀏覽器端,docs/48 §1)。
 */
export function summaryFromStockJson(data: StockJson, muted: ReadonlySet<string> = new Set()): BullBearSummary {
  const lastT = lastCandleDate(data);
  return buildBullBear({
    rawReasons: data.raw_reasons,
    reasons: data.reasons ?? [],
    rawRisks: data.raw_risks,
    risks: data.risks ?? [],
    technical: data.technical ?? null,
    pocketTags: data.pocket_tags?.filter((t) => !TRACKED_CODES.has(t.code) || pocketBadgeVisible(t.branches, muted)),
    // docs/46 v2:技術/籌碼/壓力三段的前端事實(含 price_levels 的 F 句)
    derivedFacts: deriveAllFacts(data, lastT, muted),
    asOf: lastT,
    reasonText: (code, text) => legacyReasonText(code, text),
    pocketText: pocketDisplayText,
  });
}
