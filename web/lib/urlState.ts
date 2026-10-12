// 把頁內狀態(分頁、檢視、篩選)放進網址 query,用 replaceState 不增加歷史;返回鍵回到這頁時
// 狀態還在(verifier 2026-10-12:/branch 的 tab／仍持有(估)／篩選原本按返回就丟)。
// 執行測試: node --test web/lib/urlState.test.ts

/** 合併 query:value null = 移除;其他鍵保留;鍵依原順序、新鍵排最後。回傳含 "?" 的字串("" = 沒有參數)。 */
export function mergeSearch(search: string, patch: Record<string, string | null | undefined>): string {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === "") params.delete(k);
    else params.set(k, v);
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

/** 瀏覽器端:改網址 query(保留 hash),不新增歷史。SSR／沒有 history 時安靜略過。 */
export function replaceQuery(patch: Record<string, string | null | undefined>): void {
  if (typeof window === "undefined" || !window.history?.replaceState) return;
  try {
    const next = `${window.location.pathname}${mergeSearch(window.location.search, patch)}${window.location.hash}`;
    const cur = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (next !== cur) window.history.replaceState(window.history.state, "", next);
  } catch {
    // 某些內嵌瀏覽器禁止 replaceState:狀態留在記憶體就好。
  }
}

/** 瀏覽器端目前的 query(SSR 回空)。 */
export function currentParams(): URLSearchParams {
  return new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
}
