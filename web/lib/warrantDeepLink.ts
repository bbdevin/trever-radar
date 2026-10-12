// 個股權證分頁深連結(docs/51 §3.4):`/stock?id=2330&tab=warrant&branch=群益金鼎-板橋`。
// 沿用個股頁既有的 `?tab=` 慣例(margin/holders/basic/tech/futures),再多一個 `branch`
// 由 WarrantBranchPanel 讀:開權證分頁、選中那家券商、捲到切換列、底下就是它的持有估算。
// 執行測試: node --test web/lib/warrantDeepLink.test.ts

export const WARRANT_BRANCH_PARAM = "branch";

/** 權證分頁網址;branch 省略 = 只開分頁。 */
export function warrantTabHref(stockId: string, branch?: string | null): string {
  const base = `/stock?id=${encodeURIComponent(stockId)}&tab=warrant`;
  return branch ? `${base}&${WARRANT_BRANCH_PARAM}=${encodeURIComponent(branch)}` : base;
}

/** 從 search params 取券商名(空白、空字串 → null)。 */
export function branchFromParams(params: { get(name: string): string | null } | null | undefined): string | null {
  const raw = params?.get(WARRANT_BRANCH_PARAM);
  const name = raw?.trim();
  return name ? name : null;
}

/**
 * 找一個含有這家券商的區間:目前區間有就不換;沒有就依 order 找第一個有的;都沒有 → null
 * (呼叫端顯示「不在資料裡」的小提示,排行照常)。
 */
export function timeframeContaining<T extends string>(
  byTf: Record<string, { branch_name: string }[]> | null,
  branch: string,
  current: T,
  order: readonly T[],
): T | null {
  if (!byTf) return null;
  const has = (tf: T) => (byTf[tf] ?? []).some((r) => r.branch_name === branch);
  if (has(current)) return current;
  return order.find(has) ?? null;
}
