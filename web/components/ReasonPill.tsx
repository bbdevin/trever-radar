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
export function reasonFamily(code?: string | null): ReasonFamily {
  const c = (code ?? "").toUpperCase();
  if (!c) return "neutral";
  if (c.startsWith("R")) return "risk";
  if (c.startsWith("W")) return "warrant";
  if (c.startsWith("B") || c.startsWith("I")) return "chips";
  const s = /^S(\d+)/.exec(c);
  if (s) return Number(s[1]) >= 11 ? "chips" : "tech";
  if (/^T\d/.test(c)) return "tech";
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
  className,
}: {
  code?: string | null;
  text: string;
  /** 呼叫端已知此項為風險(純文字風險列無 code)→ 強制風險家族 */
  risk?: boolean;
  className?: string;
}) {
  const family = risk ? "risk" : reasonFamily(code);
  const f = FAMILY[family];
  return (
    <span
      className={cn(
        "inline-flex min-w-0 items-center gap-1 rounded-full px-2 py-[3px] text-[11.5px] font-medium leading-[1.35]",
        f.pill,
        className,
      )}
    >
      {family === "risk" ? (
        <AlertTriangle aria-hidden className="h-3 w-3 shrink-0" />
      ) : (
        <span aria-hidden className={cn("h-1.5 w-1.5 shrink-0 rounded-full", f.dot)} />
      )}
      <span className="min-w-0">{text}</span>
    </span>
  );
}
