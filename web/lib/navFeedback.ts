/**
 * 站內換頁的即時回饋(轉圈圈 + 頂部進度條)。
 *
 * client 導覽時舊頁面會停在畫面上,直到新頁面的 JS/RSC 到齊;手機上這段空窗沒有任何回饋。
 * 這裡直接改 DOM attribute(不經 React state),點擊當下的下一個 frame 就畫得出來,
 * 不必等 transition 裡的 render。樣式在 globals.css 的 `[data-nav-pending]` 區塊。
 *
 * - `<html data-nav-pending="card|chip">`:頂部進度條一律顯示;沒有卡片可標記時(搜尋、表格列)
 *   另顯示畫面上方的轉圈圈小膠囊。
 * - 卡片(class `nav-card`)本身加 `data-nav-pending` → 卡片上蓋一層轉圈圈。
 * 新路由 commit 後由 NavFeedback 清掉;保險起見 20 秒後也自動清。
 */
let timer: ReturnType<typeof setTimeout> | null = null;

/** `href` 給了且就是目前這頁(路由不會變、回饋收不掉)時不顯示。 */
export function markNavPending(from?: Element | null, href?: string) {
  if (typeof document === "undefined") return;
  if (href != null) {
    const url = new URL(href, location.href);
    if (url.pathname === location.pathname && url.search === location.search) return;
  }
  clearNavPending();
  const card = from?.closest?.(".nav-card") ?? null;
  card?.setAttribute("data-nav-pending", "");
  document.documentElement.setAttribute("data-nav-pending", card ? "card" : "chip");
  timer = setTimeout(clearNavPending, 20_000);
}

export function clearNavPending() {
  if (typeof document === "undefined") return;
  if (timer) clearTimeout(timer);
  timer = null;
  document.documentElement.removeAttribute("data-nav-pending");
  for (const el of document.querySelectorAll("[data-nav-pending]")) el.removeAttribute("data-nav-pending");
}

/** 這次點擊會不會換到另一頁(同頁 / 只換 hash / 外站 / 新分頁 都不算)。 */
export function isPageChangingClick(e: MouseEvent, a: HTMLAnchorElement): boolean {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return false;
  if ((a.target && a.target !== "_self") || a.hasAttribute("download")) return false;
  let url: URL;
  try {
    url = new URL(a.href, location.href);
  } catch {
    return false;
  }
  if (url.origin !== location.origin) return false;
  return url.pathname !== location.pathname || url.search !== location.search;
}
