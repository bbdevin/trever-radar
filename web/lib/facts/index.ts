/**
 * 多空事實彙整(docs/46 v2 §3):從個股 JSON 現成的鍵算出前端事實,交給 buildBullBear 去重排序。
 * 舊 JSON 缺鍵 → 對應產生器回 [],不丟例外。純函式。
 *
 * STOCK_KEYS_USED ∪ STOCK_KEYS_NOT_FACTS 必須涵蓋 json_export 個股 payload 的所有頂層鍵——
 * pipeline/tests/test_bull_bear_codes.py 會比對,新增鍵卻沒決定要不要產事實 → 擋 CI。
 */
import type { DerivedFact } from "../bullBear.ts";
import type { StockJson } from "../types.ts";
import { priceLevelFacts } from "../priceLevels.ts";
import { branchFacts } from "./branchFacts.ts";
import { holdersFacts } from "./holdersFacts.ts";
import { instFacts } from "./instFacts.ts";
import { levelFacts, nearLevelFacts } from "./levelFacts.ts";
import { marginFacts } from "./marginFacts.ts";
import { marginFlowFacts } from "./marginFlowFacts.ts";
import { futuresFacts, themeFacts, warrantFacts } from "./otherFacts.ts";
import { allSeries } from "./series.ts";
import { techFacts } from "./techFacts.ts";

export { FACT_CATALOGUE } from "./catalogue.ts";

/** 會產生多空事實的個股 payload 鍵 */
export const STOCK_KEYS_USED = [
  "candles", "technical", "price_levels", "reasons", "raw_reasons", "risks", "raw_risks", "pocket_tags",
  "branch_history", "branch_tags", "branch_pnl_est", "branch_pctile_counts", "insti_history", "margin_history",
  "holders_history", "holders_meta", "directors_latest", "warrant", "warrant_history",
  "futures", "recent_theme_heat", "buyback",
] as const;

/** 刻意不產事實的鍵(識別資料、分數、已由其他鍵涵蓋或屬籌碼日報明細) */
export const STOCK_KEYS_NOT_FACTS = [
  "id", "name", "market", "industry", "company_profile", "company_groups", "company_themes",
  "scores", "strategy_signals", "pocket_score",
  // 今日分點清單:多空用 branch_history[0](同一天、已按名稱可加總)
  "branches",
  "active_warrants", "margin_meta",
] as const;

export function deriveAllFacts(data: StockJson, lastT: string, muted: ReadonlySet<string> = new Set()): DerivedFact[] {
  const series = allSeries(data.candles);
  const candles = data.candles ?? [];
  // 融資×分點集中度先算:結果會調整 C_MARGIN_HOT 的 rank、決定是否列 5 日融資增價跌(docs/46 §7)
  const flow = marginFlowFacts(data, candles, series.adjusted, lastT);
  const price = priceLevelFacts(data.price_levels, lastT, data.technical?.rsi14);
  const levels = levelFacts(data.price_levels, series, lastT);
  return [
    ...price,
    ...techFacts(series, data.technical ?? null),
    // 壓力段 ≤3% 的價位在技術段也成句(同一份壓力段事實,不另算門檻)
    ...nearLevelFacts([...price, ...levels]),
    ...levels,
    ...instFacts(data.insti_history, candles, lastT),
    ...flow.facts,
    ...marginFacts(data.margin_history, series.adjusted, lastT, flow),
    ...branchFacts(data, candles, lastT, muted),
    ...holdersFacts(data.holders_history, data.holders_meta, data.directors_latest),
    ...warrantFacts(data.warrant, data.warrant_history, lastT),
    ...futuresFacts(data.futures, data.id),
    ...themeFacts(data.recent_theme_heat, data.buyback, lastT),
  ];
}
