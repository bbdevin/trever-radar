import { Flame, MapPin, Shield, Star } from "lucide-react";
import ReasonPill from "@/components/ReasonPill";
import type { PocketTag } from "@/lib/types";

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

/** 舊 payload 的人話全文仍寫著改名前的「關鍵分點同買：」。
 *
 * META 的雙讀只修好 compact 模式的徽章字樣;個股頁是 compact=false、渲染的是
 * 伺服器產生的 t.text,tooltip 也是,所以在下一次 VPS export 之前(程式碼走
 * Pages 幾分鐘就上,JSON 要等當天的匯出輪)會出現徽章寫「追蹤分點」、展開卻寫
 * 「關鍵分點同買」的矛盾。這次改名的整個重點就是那三個字不該再指這個東西,
 * 讓它在畫面上多留幾小時等於沒改。
 *
 * 只改顯示,不碰資料:僅對 legacy code 生效,且只換開頭那一段前綴,分點名稱
 * 原樣保留。新 payload 走 T1 分支,這段完全不執行——和 META 裡的 K1 條目同時
 * 可以刪掉。
 */
const LEGACY_TEXT_PREFIX = "關鍵分點同買";
const CURRENT_TEXT_PREFIX = "追蹤分點同買";

function displayText(t: PocketTag): string {
  if (t.code === "K1_KEY_BUY" && t.text.startsWith(LEGACY_TEXT_PREFIX)) {
    return CURRENT_TEXT_PREFIX + t.text.slice(LEGACY_TEXT_PREFIX.length);
  }
  return t.text;
}

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
