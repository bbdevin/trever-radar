"use client";

import { IconStar } from "@/components/Icons";
import { useWatchlist } from "@/lib/watchlist";
import { signInWithGoogle, useSession } from "@/lib/useSession";

/**
 * ★ 加入/移除自選股。未登入時點擊觸發 Google 登入,不彈跳提示打斷操作。
 * 用 span[role=button] 而非 <button>——這顆常被放在 StockCard 的 <a> 卡片裡面,
 * 巢狀 <button> 在 <a> 內是不合法 HTML,span+role 才不會有巢狀互動元件的問題。
 */
export default function WatchlistButton({ stockId, size = 18 }: { stockId: string; size?: number }) {
  const { session } = useSession();
  const { ids, toggle } = useWatchlist();
  const active = ids.has(stockId);

  const activate = () => {
    if (!session) {
      signInWithGoogle();
      return;
    }
    void toggle(stockId);
  };

  return (
    <span
      role="button"
      tabIndex={0}
      className={active ? "watchlist-btn active" : "watchlist-btn"}
      title={session ? (active ? "移除自選" : "加入自選") : "登入後可加入自選股"}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        activate();
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          activate();
        }
      }}
    >
      <IconStar size={size} />
    </span>
  );
}
