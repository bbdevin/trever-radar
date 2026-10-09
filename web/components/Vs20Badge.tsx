import { cn } from "@/lib/utils";
import { vs20Deviation } from "@/lib/instiGroupFlow";

/**
 * 量能徽章:今日成交金額相對近 20 日平均的偏離 %(+96 = 1.96×)。
 * 文字自帶 +/-,顏色不作唯一訊號。原本住在 MoneyFlow(2026-10-09 首頁資金流向面板
 * 併入法人族群分頁後移到這裡;題材分組列與法人族群列共用)。
 */
export function Vs20Badge({ vs20 }: { vs20: number | null }) {
  const d = vs20Deviation(vs20);
  return (
    <span
      className={cn(
        "num shrink-0 rounded-full border px-1.5 py-px text-[10.5px] font-bold",
        d == null || d === 0
          ? "border-border text-muted-foreground"
          : d > 0
            ? "border-[color:color-mix(in_srgb,var(--up)_45%,transparent)] text-up"
            : "border-[color:color-mix(in_srgb,var(--down)_45%,transparent)] text-down",
      )}
      title={vs20 != null ? `今日成交金額為近20日平均的 ${vs20.toFixed(2)} 倍` : "近20日均量資料不足"}
    >
      量能{d == null ? "—" : `${d > 0 ? "+" : ""}${d}%`}
    </span>
  );
}
