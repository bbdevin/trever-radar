/**
 * 橫滑列(分頁 pill、chip 列)邊緣提示的純計算:哪一側還有內容、選中項要捲到哪。
 * 元件在 components/ScrollHint.tsx;這裡不碰 DOM,方便用 node --test 蓋住。
 */

/** 小於這個像素差視為已到邊(次像素捲動、縮放後的捨入誤差)。 */
const EDGE_EPSILON = 2;

export type ScrollEdges = { left: boolean; right: boolean };

export function scrollEdges(scrollLeft: number, clientWidth: number, scrollWidth: number): ScrollEdges {
  if (scrollWidth - clientWidth <= EDGE_EPSILON) return { left: false, right: false };
  return {
    left: scrollLeft > EDGE_EPSILON,
    right: scrollLeft + clientWidth < scrollWidth - EDGE_EPSILON,
  };
}

/**
 * 選中項 [itemLeft, itemLeft+itemWidth](相對捲動內容的座標)要完整露出,且不被邊緣提示
 * (寬 margin)蓋住時的 scrollLeft;已經看得到就回傳 null(不動,避免使用者剛點的列跳動)。
 */
export function scrollTargetForItem(
  itemLeft: number,
  itemWidth: number,
  scrollLeft: number,
  clientWidth: number,
  scrollWidth: number,
  margin: number,
): number | null {
  const max = Math.max(0, scrollWidth - clientWidth);
  const itemRight = itemLeft + itemWidth;
  let target: number | null = null;
  if (itemLeft - margin < scrollLeft) target = itemLeft - margin;
  else if (itemRight + margin > scrollLeft + clientWidth) target = itemRight + margin - clientWidth;
  if (target == null) return null;
  const clamped = Math.min(max, Math.max(0, target));
  return Math.abs(clamped - scrollLeft) < 1 ? null : clamped;
}
