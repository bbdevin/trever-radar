import { AlertTriangle } from "lucide-react";

import ChangeText, { CHANGE_CLASS } from "@/components/ChangeText";
import { TF_CHIP, type Seg, type Source, type Tf } from "@/lib/bullBear";

/** 來源/群組小膠囊的家族色(docs/19 §4 的同一組 token + /12 淡底;零新色票)。 */
export const ACCENT2_PILL = "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]";
export const PRIMARY_PILL = "bg-primary/12 text-primary";
const WARN_PILL = "bg-warn/12 text-warn";
const INK_PILL = "bg-[color:var(--ink-2)]/12 text-[color:var(--ink-2)]";
export const SOURCE_TONE: Record<Source, string> = {
  chips: ACCENT2_PILL,
  inst: ACCENT2_PILL,
  margin: ACCENT2_PILL,
  holders: ACCENT2_PILL,
  futures: ACCENT2_PILL,
  tech: PRIMARY_PILL,
  price: PRIMARY_PILL,
  levels: PRIMARY_PILL,
  strategy: PRIMARY_PILL,
  warrant: WARN_PILL,
  theme: WARN_PILL,
  company: INK_PILL,
  other: INK_PILL,
};

/**
 * 一條多空事實的內文(個股頁「多空」分頁與首頁「多方榜」卡片共用):事件型空方的警示圖示 →
 * 週/月 K 小膠囊 → 逐段上色的句子(後端原文交給 ChangeText 的 ±% 規則)→ 滯後資料日。
 * 只輸出行內元素,外層 li/div 由呼叫端決定。
 */
export default function FactLine({
  text,
  segments,
  tf,
  riskIcon,
  date,
}: {
  text: string;
  segments?: Seg[];
  tf?: Tf;
  riskIcon?: boolean;
  date?: string;
}) {
  return (
    <>
      {riskIcon && <AlertTriangle aria-hidden className="mr-1 inline h-3 w-3 -translate-y-px text-down" />}
      {tf && tf !== "D" && (
        <span className="mr-1 inline-flex -translate-y-px items-center rounded-[4px] border border-[color:var(--line)] px-1 text-[10.5px] font-semibold leading-[1.35] text-[color:var(--ink-2)]">
          {TF_CHIP[tf]}
        </span>
      )}
      {segments ? (
        segments.map((s, i) => (
          <span key={i} className={s.kind ? CHANGE_CLASS[s.kind] : undefined}>
            {s.t}
          </span>
        ))
      ) : (
        <ChangeText text={text} prices={false} />
      )}
      {date && <span className="num ml-1.5 whitespace-nowrap text-[11px] text-muted-foreground">{date}</span>}
    </>
  );
}
