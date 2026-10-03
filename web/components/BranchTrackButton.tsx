"use client";

import { toast } from "sonner";
import { IconStar } from "@/components/Icons";
import { useBranchTrack } from "@/lib/branchTrackList";
import { cn } from "@/lib/utils";

const TOOLTIP = "管理員設定的全站追蹤名單";

/**
 * ★ 加入/取消全站追蹤(管理員專用,見 lib/branchTrackList.tsx)。非管理員、或名單
 * 資料表還讀不到時整顆不出現——其他人只看結果(追蹤標籤、我的追蹤篩選)。
 *
 * 照 WatchlistButton 的做法用 span[role=button]:/branch 的排行卡整張是 <button>,
 * 巢狀 <button> 不合法;點擊與按鍵都 stopPropagation,不會順便打開卡片。
 *
 * variant="icon":30px 圓鈕(下鑽頁標題、明細選單旁)。
 * variant="pill":帶「追蹤」字樣的小膠囊(排行卡標題,取代原本的靜態追蹤標)。
 */
export default function BranchTrackButton({
  name,
  serverTracked,
  variant = "icon",
  size = 16,
}: {
  name: string;
  /** 系統名單(VPS 匯出)是否包含這個分點。 */
  serverTracked: boolean;
  variant?: "icon" | "pill";
  size?: number;
}) {
  const { canEdit, isTracked, toggle } = useBranchTrack();
  if (!canEdit) return null;
  const active = isTracked(name, serverTracked);
  const label = active ? "取消追蹤" : "追蹤分點";

  const activate = () => {
    void toggle(name, serverTracked).then(({ error }) => {
      if (error) {
        toast.error("追蹤名單沒有存到，請再試一次", { duration: 2500 });
      } else if (active) {
        toast.info(`已取消全站追蹤 ${name}`, { duration: 2000 });
      } else {
        toast.success(`已加入全站追蹤 ${name}`, { duration: 2000 });
      }
    });
  };

  return (
    <span
      role="button"
      tabIndex={0}
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center border border-border bg-card text-muted-foreground transition-colors hover:border-[color:var(--border-strong)] hover:text-[color:var(--ink-2)]",
        variant === "icon"
          ? "size-[30px] rounded-full p-0"
          : "min-h-[30px] gap-1 rounded-full px-2.5 text-[11.5px] font-bold",
        active && "border-warn text-warn [&_svg]:fill-current",
      )}
      aria-label={label}
      aria-pressed={active}
      title={TOOLTIP}
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
      {variant === "pill" && "追蹤"}
    </span>
  );
}
