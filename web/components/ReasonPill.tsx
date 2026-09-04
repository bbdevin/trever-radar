import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * WP-H2 語意色彩層次:理由/風險 pill 的家族色分類 + 呈現。
 * 只用 globals.css 既有 token(--accent-2/--primary/--warn/--destructive/--ink-2),零新色票。
 * 色非唯一訊號:每家族帶圓點前綴,風險家族帶 AlertTriangle icon。
 */
export type ReasonFamily = "chips" | "tech" | "warrant" | "risk" | "neutral";

/**
 * 依 reason code 前綴判家族(見 docs/19 §4 對照表):
 *   R* → 風險 / W* → 權證 / B*、I*、S11-S13 → 籌碼 / T\d、S1-S10 → 技術 / 其他(T_THEME 等)→ 中性。
 * 無 code(純文字理由)一律歸中性,呼叫端若已知語意(如風險列)可用 risk 參數強制覆寫。
 */
/** S11 起是籌碼事件策略,S1–S10 是技術面(docs/19 §4 對照表)。
 *
 * 抽成函式是因為第二份手抄清單已經出過事:`app/stock/page.tsx` 曾寫
 * `["S11","S12","S13"].includes(c)`,但 `c` 是完整 code(如
 * `"S13_SHORT_SQUEEZE"`),那個比較永遠不成立——個股頁的分點理由區從來
 * 沒顯示過那三個籌碼理由,而它上一行的註解正說它們應該在。用同一個
 * 判準就不會有第二份清單可漂。
 */
export function isChipStrategyCode(code?: string | null): boolean {
  const m = /^S(\d+)/.exec((code ?? "").toUpperCase());
  return m ? Number(m[1]) >= 11 : false;
}

export function reasonFamily(code?: string | null): ReasonFamily {
  const c = (code ?? "").toUpperCase();
  if (!c) return "neutral";
  if (c.startsWith("R")) return "risk";
  if (c.startsWith("W")) return "warrant";
  if (c.startsWith("B") || c.startsWith("I")) return "chips";
  const s = /^S(\d+)/.exec(c);
  if (s) return isChipStrategyCode(c) ? "chips" : "tech";
  if (/^T\d/.test(c)) return "tech";
  if (c.startsWith("G1_") || c.startsWith("G2_") || c.startsWith("K1_") || c.startsWith("T1_")) return "chips";
  if (c.startsWith("H1_") || c.startsWith("KB")) return "warrant";
  return "neutral";
}

// 淡底(/12,已於既有 bg-[color:var(--ink-2)]/10 慣例驗證 TW v4 可用)+ 家族色文字 + 同色圓點。
// primary/warn/destructive 為 @theme 註冊色可直接 text-*/bg-*;accent-2/ink-2 未註冊,用 arbitrary value。
const FAMILY: Record<ReasonFamily, { pill: string; dot: string }> = {
  chips: { pill: "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]", dot: "bg-[color:var(--accent-2)]" },
  tech: { pill: "bg-primary/12 text-primary", dot: "bg-primary" },
  warrant: { pill: "bg-warn/12 text-warn", dot: "bg-warn" },
  risk: { pill: "bg-destructive/12 text-destructive", dot: "" },
  neutral: { pill: "border border-[color:var(--line)] text-[color:var(--ink-2)]", dot: "bg-[color:var(--ink-2)]" },
};

export default function ReasonPill({
  code,
  text,
  risk = false,
  icon,
  title,
  className,
}: {
  code?: string | null;
  text: string;
  /** 呼叫端已知此項為風險(純文字風險列無 code)→ 強制風險家族 */
  risk?: boolean;
  /** 取代圓點(口袋 badge 用星/火/圖釘;色仍走家族 token) */
  icon?: ReactNode;
  title?: string;
  className?: string;
}) {
  const family = risk ? "risk" : reasonFamily(code);
  const f = FAMILY[family];
  return (
    <span
      title={title}
      className={cn(
        "inline-flex min-w-0 items-center gap-1 rounded-full px-2 py-[3px] text-[11.5px] font-medium leading-[1.35]",
        f.pill,
        className,
      )}
    >
      {family === "risk" ? (
        <AlertTriangle aria-hidden className="h-3 w-3 shrink-0" />
      ) : icon ? (
        <span aria-hidden className="inline-flex h-3 w-3 shrink-0 items-center justify-center [&_svg]:h-3 [&_svg]:w-3">
          {icon}
        </span>
      ) : (
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", f.dot)} />
      )}
      <span className="min-w-0">{text}</span>
    </span>
  );
}
