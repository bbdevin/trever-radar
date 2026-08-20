import { Flame, MapPin, Shield, Star } from "lucide-react";
import ReasonPill from "@/components/ReasonPill";
import type { PocketTag } from "@/lib/types";

const META: Record<string, { label: string; icon: typeof Star }> = {
  G1_GEO_BUY: { label: "地緣買", icon: MapPin },
  G2_GEO_SELL: { label: "地緣賣", icon: MapPin },
  K1_KEY_BUY: { label: "關鍵分點", icon: Star },
  H1_HOT_THEME: { label: "題材熱門", icon: Flame },
  KB1_BUYBACK_WINDOW: { label: "庫藏股", icon: Shield },
  KB2_BUYBACK_BRANCH: { label: "疑似庫藏分點", icon: Shield },
};

/** docs/27 G4:口袋 reason badges。卡片最多 4 個 +N;個股頁傳 compact=false 顯示人話全文。 */
export default function PocketBadges({
  tags,
  compact = true,
  max = 4,
}: {
  tags?: PocketTag[];
  compact?: boolean;
  max?: number;
}) {
  if (!tags?.length) return null;
  const shown = compact ? tags.slice(0, max) : tags;
  const extra = compact ? tags.length - shown.length : 0;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((t) => {
        const meta = META[t.code];
        const Icon = meta?.icon;
        return (
          <ReasonPill
            key={t.code}
            code={t.code}
            text={compact ? (meta?.label ?? t.text) : t.text}
            title={t.text}
            icon={Icon ? <Icon strokeWidth={1.8} /> : undefined}
          />
        );
      })}
      {extra > 0 && (
        <span
          title={tags.slice(max).map((t) => t.text).join(" / ")}
          className="inline-flex items-center rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] font-medium text-muted-foreground"
        >
          +{extra}
        </span>
      )}
    </div>
  );
}
