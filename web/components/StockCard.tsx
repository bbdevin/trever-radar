import Sparkline from "@/components/Sparkline";
import WatchlistButton from "@/components/WatchlistButton";
import type { RadarStock } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtLots, fmtPct, fmtX } from "@/lib/format";
import { cn } from "@/lib/utils";

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };
const CHG_BADGE: Record<string, string> = {
  up: "text-up bg-up/15",
  down: "text-down bg-down/15",
  flat: "text-foreground bg-secondary",
};

// V1.2 狀態色條:僅用 globals.css 既有 token,色條非唯一訊號(旁有綜合分/風險文字對應)
// risk_penalty 範圍 0~-40,單一顯著風險扣 8~15 分,故 <=-8 視為「風險扣分明顯」
type CardStatus = "risk" | "watch" | "neutral";
const STATUS_BAR: Record<CardStatus, string> = {
  risk: "bg-destructive",
  watch: "bg-warn",
  neutral: "bg-[color:var(--line)]",
};

function cardStatus(s: RadarStock): CardStatus {
  if (s.scores) {
    if (s.risks.length > 0 && (s.scores.risk_penalty ?? 0) <= -8) return "risk";
    if (s.scores.final >= 65) return "watch";
  }
  return "neutral";
}

export default function StockCard({ s, index = 99 }: { s: RadarStock; index?: number }) {
  const cls = chgClass(s.chg_pct);
  const status = cardStatus(s);
  return (
    <a
      href={`/stock?id=${s.id}`}
      style={index < 6 ? { animationDelay: `${0.02 + index * 0.03}s` } : undefined}
      className="group relative flex cursor-pointer flex-col gap-2.5 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)] transition-[transform,border-color,box-shadow] duration-150 animate-[fadeUp_0.35s_ease_backwards] hover:-translate-y-0.5 hover:border-[color:var(--border-strong)] hover:shadow-[var(--shadow-lift)] active:scale-[0.985]"
    >
      <span aria-hidden className={cn("pointer-events-none absolute inset-y-1.5 left-0 w-[3px] rounded-full", STATUS_BAR[status])} />
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[15.5px] font-bold text-foreground">{s.name}</span>
          <span className="text-xs text-muted-foreground">
            {s.id} · {MARKET_LABEL[s.market] ?? s.market}
            {s.industry ? ` · ${s.industry}` : ""}
          </span>
          {!!s.themes?.length && (
            <div className="mt-1 flex flex-wrap gap-1">
              {s.themes.slice(0, 3).map((t) => (
                <span key={t} className="whitespace-nowrap rounded-full bg-muted px-1.5 py-px text-[10px] font-semibold text-warn">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="ml-auto shrink-0 text-right">
          <div className={cn("num text-[21px] font-extrabold tracking-[-0.3px]", CHG_TEXT[cls])}>
            {s.close.toLocaleString("zh-TW")}
          </div>
          <span className={cn("num mt-0.5 inline-block rounded-full px-2 py-px text-[12.5px] font-bold", CHG_BADGE[cls])}>
            {fmtPct(s.chg_pct)}
          </span>
        </div>
        <WatchlistButton stockId={s.id} />
      </div>

      {s.description && (
        <div className="line-clamp-2 overflow-hidden rounded-lg bg-secondary px-2.5 py-2 text-xs leading-[1.4] text-muted-foreground">
          {s.description}
        </div>
      )}

      <div className="flex items-center gap-2">
        <div className="h-[34px] flex-1 [&_svg]:h-[34px] [&_svg]:w-full">
          <Sparkline data={s.spark} id={s.id} />
        </div>
        <span className="whitespace-nowrap text-[10.5px] text-muted-foreground">
          近{Math.min(s.spark?.length ?? 0, 30)}日
        </span>
      </div>

      {/* V1.1 次要細項:4 欄堆疊 → 收斂成一行小字,降層級不刪資料 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11.5px] text-muted-foreground">
        <span>金額 <span className="num font-semibold text-[color:var(--ink-2)]">{fmtE8(s.turnover)}</span></span>
        <span>量比 <span className="num font-semibold text-[color:var(--ink-2)]">{s.volume_ratio != null ? `${s.volume_ratio.toFixed(1)}×` : "—"}</span></span>
        <span>外資 <span className="num font-semibold text-[color:var(--ink-2)]">{fmtLots(s.foreign_net_lots)}</span></span>
        <span>投信 <span className="num font-semibold text-[color:var(--ink-2)]">{fmtLots(s.trust_net_lots)}</span></span>
      </div>

      <div className="border-t border-dashed border-[color:var(--line)] pt-2 text-[11.5px] text-muted-foreground">
        {s.scores ? (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2.5">
              <span className={cn("num text-xl font-extrabold text-[color:var(--ink-2)]", s.scores.final >= 65 && "text-warn")}>
                {s.scores.final}
              </span>
              <span className="ml-1 text-[10.5px] text-muted-foreground">綜合評分</span>
            </div>
            {(s.scores.watch_price != null || s.scores.stop_price != null) && (
              <div className="num flex gap-2.5 text-[11.5px]">
                {s.scores.watch_price != null && (
                  <span className="text-[color:var(--accent-2)]">觀察 {s.scores.watch_price.toFixed(2)}</span>
                )}
                {s.scores.stop_price != null && <span className="text-up">失效 {s.scores.stop_price.toFixed(2)}</span>}
              </div>
            )}
            {s.reasons.slice(0, 2).map((t) => (
              <div className="text-xs leading-[1.45] text-[color:var(--ink-2)]" key={t}>
                {t}
              </div>
            ))}
            {s.risks.slice(0, 1).map((t) => (
              <div className="text-xs text-up" key={t}>
                {t}
              </div>
            ))}
          </div>
        ) : s.warrant ? (
          <div className="grid grid-cols-[1.35fr_0.55fr_0.8fr_0.55fr] items-center gap-1.5 text-muted-foreground">
            <span>
              認購 <b className="font-bold text-[color:var(--ink-2)]">{fmtE8(s.warrant.call_turnover)}</b>
            </span>
            <span className="truncate">{fmtX(s.warrant.call_turnover_ratio)}</span>
            <span className="truncate">{s.warrant.call_count} 檔</span>
          </div>
        ) : (
          "未達評分門檻(20日均額 <3,000萬)"
        )}
      </div>
    </a>
  );
}
