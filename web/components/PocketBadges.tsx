"use client";

import { Flame, MapPin, Shield, Star } from "lucide-react";
import ReasonPill from "@/components/ReasonPill";
import { useBranchTrack } from "@/lib/branchTrackList";
import { pocketBadgeVisible } from "@/lib/branchTrackResolve";
import { pocketDisplayText } from "@/lib/pocketText";
import type { PocketTag } from "@/lib/types";

/** 「追蹤分點同買」徽章的兩個代號(新/舊,見下方 META)。 */
const TRACKED_CODES = new Set(["T1_TRACKED_BUY", "K1_KEY_BUY"]);

const META: Record<string, { label: string; icon: typeof Star }> = {
  G1_GEO_BUY: { label: "地緣買", icon: MapPin },
  G2_GEO_SELL: { label: "地緣賣", icon: MapPin },
  // T1_TRACKED_BUY is the current code (docs/27 rename); K1_KEY_BUY is the
  // legacy code a payload exported before the rename still carries (JSON only
  // refreshes at the next VPS export). Both map to the corrected label so old
  // payloads render correctly too. Drop K1_KEY_BUY once no shipped payload
  // predates the rename. Note: "關鍵分點" itself is a reserved name for a
  // different, per-stock low-buy-high-sell concept — see docs/27 — and is not
  // used here.
  T1_TRACKED_BUY: { label: "追蹤分點", icon: Star },
  K1_KEY_BUY: { label: "追蹤分點", icon: Star },
  H1_HOT_THEME: { label: "題材熱門", icon: Flame },
  KB1_BUYBACK_WINDOW: { label: "庫藏股", icon: Shield },
};

/** 舊 payload「關鍵分點同買」→「追蹤分點同買」的顯示期轉場;多空摘要與多方榜建置器共用,見 lib/pocketText.ts。 */
const displayText = pocketDisplayText;

/** docs/27 G4:口袋 reason badges。卡片最多 4 個 +N;個股頁傳 compact=false 顯示人話全文。 */
export default function PocketBadges({
  tags: rawTags,
  compact = true,
  max = 4,
}: {
  tags?: PocketTag[];
  compact?: boolean;
  max?: number;
}) {
  // 管理員把這個徽章背後的分點全部從全站追蹤名單取消 → 先在畫面上藏起來,
  // 直到 VPS 下一輪把名單併回系統名單、重算口袋名單。入選與排序這裡不重算。
  const { muted } = useBranchTrack();
  const tags = rawTags?.filter((t) => !TRACKED_CODES.has(t.code) || pocketBadgeVisible(t.branches, muted));
  if (!tags?.length) return null;
  const shown = compact ? tags.slice(0, max) : tags;
  const extra = compact ? tags.length - shown.length : 0;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((t) => {
        const meta = META[t.code];
        const Icon = meta?.icon;
        const full = displayText(t);
        return (
          <ReasonPill
            key={t.code}
            code={t.code}
            text={compact ? (meta?.label ?? full) : full}
            title={full}
            icon={Icon ? <Icon strokeWidth={1.8} /> : undefined}
          />
        );
      })}
      {extra > 0 && (
        <span
          title={tags.slice(max).map(displayText).join(" / ")}
          className="inline-flex items-center rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] font-medium text-muted-foreground"
        >
          +{extra}
        </span>
      )}
    </div>
  );
}
