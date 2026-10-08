"use client";

import { AlertCircle, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { contractLabelTitle, spotFollowLabel, type SpotFollow } from "@/lib/futures";

/**
 * 期貨舉旗卡片(當日與近 N 日共用)的外框與狀態標籤。
 *
 * 使用者 2026-10-03:「現貨尚未跟上」與「現貨已同步爆量」要一眼分得出來。
 *   - 現貨尚未跟上(檢定成立的那一種)= 原本的 accent-2 外框、左色條、實心標籤;
 *   - 現貨已同步爆量 = 同樣醒目,用 `--up` 紅色外框、左色條、實心紅標籤;
 *   - 不知道 = 不貼標籤、一般外框。
 * 這是**量的訊號狀態**的分類色,不是漲跌色:外框紅不代表漲。真正的漲跌色只在
 * 價格本身——首頁名單的「股價」一行(§7.21)與近 N 日紀錄的價格句,依數字紅漲綠跌、
 * 0 中性。標籤文字保留,顏色不是唯一的訊號。
 */
export function flagCardClass(spot: SpotFollow): string {
  return cn(
    "block min-w-0 rounded-[var(--r-lg)] border border-l-4 bg-card px-3 py-2.5 shadow-[var(--shadow-card)] transition-colors hover:bg-secondary/40",
    spot === "lagging"
      ? "border-[color:var(--accent-2)]/45 border-l-[color:var(--accent-2)]"
      : spot === "followed"
        ? "border-up/45 border-l-up"
        : "border-border border-l-border",
  );
}

/** `when="flag"`:近 N 日紀錄用舉旗當時的措辭(「舉旗時現貨…」),顏色不變。 */
export function SpotChip({ spot, when = "now" }: { spot: SpotFollow; when?: "now" | "flag" }) {
  const label = spotFollowLabel(spot, when);
  if (!label) return null;
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10.5px] font-bold text-white",
        spot === "lagging" ? "bg-[color:var(--accent-2)]" : "bg-up",
      )}
    >
      {spot === "followed" && <AlertCircle size={11} aria-hidden="true" />}
      {label}
    </span>
  );
}

/** 契約的白話名稱;代碼只放在 title(滑鼠移上去才看得到),畫面上不顯示。 */
export function ContractTag({ label, code }: { label: string; code: string }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground"
      title={contractLabelTitle(label, code)}
    >
      <Layers size={11} aria-hidden="true" />
      {label}
    </span>
  );
}
