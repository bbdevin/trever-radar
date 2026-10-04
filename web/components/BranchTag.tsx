"use client";

import { AlertTriangle, Building2, MapPin, Star, type LucideIcon } from "lucide-react";

import { compactSide, normalizeBranchPctile, seatKind } from "@/lib/branchPctile";
import {
  MAX_VISIBLE_PHONE,
  MAX_VISIBLE_WIDE,
  tagDefinitions,
  tagLegendFootnote,
  type Tag,
  type TagContext,
  type TagTone,
} from "@/lib/branchTags";
import type { BranchPctileCounts, BranchTags } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * 籌碼日報的分點標籤(地緣／股代／隔日沖／追蹤／買低賣高／總公司外資)。
 * 顏色只是輔助:每個標籤都有文字,地緣／股代／隔日沖／追蹤另有圖示,點開有帶數字的說明。
 */

/**
 * payload → 標籤用的 context。舊 JSON 缺鍵時對應的標籤自然不出現。
 * list = useBranchTrack() 的 muted/added(管理員的全站取消／加入追蹤);讀不到是兩個空集合。
 */
export function makeTagContext(
  tags: BranchTags | null | undefined,
  pctile: BranchPctileCounts | null | undefined,
  list?: { muted: ReadonlySet<string>; added: ReadonlySet<string> },
  window?: { from: string; to: string } | null,
): TagContext {
  return {
    tags,
    pctile: normalizeBranchPctile(pctile),
    seatKind,
    compactSide,
    listMuted: list?.muted,
    listAdded: list?.added,
    window,
  };
}

const TONE: Record<TagTone, string> = {
  geo: "border-primary/35 bg-primary/12 text-primary",
  // 股代:與總公司席位同色(標的就是總公司席位;docs/19 不引入新色),靠圖示與文字區分
  agent: "border-[color:var(--warn)]/45 bg-[color:var(--warn)]/12 text-[color:var(--warn)]",
  daytrade: "border-destructive/35 bg-destructive/12 text-destructive",
  tracked: "border-primary/35 bg-primary/12 text-primary",
  neutral: "border-border bg-secondary text-foreground",
  seat: "border-[color:var(--warn)]/45 bg-[color:var(--warn)]/12 text-[color:var(--warn)]",
};

const ICON: Partial<Record<TagTone, LucideIcon>> = {
  geo: MapPin,
  agent: Building2,
  daytrade: AlertTriangle,
  tracked: Star,
};

/** 「+N」的開啟鍵;其餘開啟鍵就是標籤代號。 */
const MORE = "MORE";

const PILL = "inline-flex shrink-0 cursor-pointer items-center gap-0.5 whitespace-nowrap rounded-full border px-1.5 py-px text-[10.5px] font-semibold";

/**
 * 列本身是一顆按鈕(點了開下鑽或展開),所以標籤用 role="button" 的 span,
 * 點擊與 Enter/空白鍵都 stopPropagation,只開自己的說明、不觸發整列。
 */
function TagPill({
  label,
  note,
  className,
  icon: Icon,
  open,
  onToggle,
}: {
  label: string;
  note: string;
  className: string;
  icon?: LucideIcon;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <span
      role="button"
      tabIndex={0}
      aria-expanded={open}
      aria-label={note}
      title={note}
      className={cn(PILL, className, open && "ring-1 ring-current")}
      onClick={(e) => {
        e.stopPropagation();
        e.preventDefault();
        onToggle();
      }}
      onKeyDown={(e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.stopPropagation();
        e.preventDefault();
        onToggle();
      }}
    >
      {Icon && <Icon size={10} strokeWidth={2.2} aria-hidden />}
      {label}
    </span>
  );
}

export default function BranchTag({
  tag,
  open,
  onToggle,
  className,
}: {
  tag: Tag;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <TagPill
      label={tag.label}
      note={tag.note}
      icon={ICON[tag.tone]}
      className={cn(TONE[tag.tone], className)}
      open={open}
      onToggle={onToggle}
    />
  );
}

/**
 * 一列的標籤:手機最多 MAX_VISIBLE_PHONE 個、md 以上 MAX_VISIBLE_WIDE 個,
 * 其餘收進「+N」,點開才看得到。open = 目前開著的標籤代號或 "MORE"。
 */
export function BranchTagList({
  tags,
  open,
  onToggle,
}: {
  tags: Tag[];
  open: string | null;
  onToggle: (key: string) => void;
}) {
  if (!tags.length) return null;
  const hiddenPhone = tags.length - MAX_VISIBLE_PHONE;
  const hiddenWide = tags.length - MAX_VISIBLE_WIDE;
  const moreNote = (from: number) => `另有：${tags.slice(from).map((t) => t.label).join("、")}`;
  return (
    <>
      {tags.map((tag, i) => (
        <BranchTag
          key={tag.code}
          tag={tag}
          open={open === tag.code}
          onToggle={() => onToggle(tag.code)}
          className={cn(i >= MAX_VISIBLE_PHONE && "max-md:hidden", i >= MAX_VISIBLE_WIDE && "md:hidden")}
        />
      ))}
      {hiddenPhone > 0 && (
        <TagPill
          label={`+${hiddenPhone}`}
          note={moreNote(MAX_VISIBLE_PHONE)}
          className={cn(TONE.neutral, "md:hidden")}
          open={open === MORE}
          onToggle={() => onToggle(MORE)}
        />
      )}
      {hiddenWide > 0 && (
        <TagPill
          label={`+${hiddenWide}`}
          note={moreNote(MAX_VISIBLE_WIDE)}
          className={cn(TONE.neutral, "max-md:hidden")}
          open={open === MORE}
          onToggle={() => onToggle(MORE)}
        />
      )}
    </>
  );
}

/** 列下方的說明:點哪個標籤就是那個的數字;點「+N」列出收起來的那幾個。 */
export function BranchTagNote({
  tags,
  open,
  className,
}: {
  tags: Tag[];
  open: string | null;
  className?: string;
}) {
  if (!open) return null;
  const lines = open === MORE
    ? tags.map((tag, i) => ({ tag, i })).filter(({ i }) => i >= MAX_VISIBLE_PHONE)
    : tags.map((tag, i) => ({ tag, i })).filter(({ tag }) => tag.code === open);
  if (!lines.length) return null;
  return (
    <div className={cn("grid gap-0.5 text-[11.5px] leading-snug text-muted-foreground", className)} aria-live="polite">
      {lines.map(({ tag, i }) => (
        <p key={tag.code} className={cn(open === MORE && i < MAX_VISIBLE_WIDE && "md:hidden")}>
          {tag.note}
        </p>
      ))}
    </div>
  );
}

/** 名單上方的「標籤怎麼看」:全部定義＋資料日＋涵蓋範圍;數字都從 payload 讀。 */
export function BranchTagLegend({ ctx }: { ctx: TagContext }) {
  const defs = tagDefinitions(ctx);
  return (
    <details className="rounded-[var(--r-sm)] border border-border bg-card px-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
      <summary className="cursor-pointer select-none py-1.5 text-[12px] font-semibold text-foreground">標籤怎麼看</summary>
      <dl className="grid gap-1">
        {defs.map((d) => (
          <div key={d.label}>
            <dt className="inline font-semibold text-foreground">{d.label}</dt>
            <dd className="inline">：{d.text}</dd>
          </div>
        ))}
      </dl>
      <p className="pt-1 pb-2">{tagLegendFootnote(ctx)}</p>
    </details>
  );
}
