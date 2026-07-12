"use client";

import { forwardRef, useMemo, useState, useEffect, useRef } from "react";
import type { ReasonItem, StockJson } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { cn, pillTabClass } from "@/lib/utils";
import ReasonPill from "@/components/ReasonPill";

const BRANCH_RANGES = [
  { label: "1日", days: 1 },
  { label: "3日", days: 3 },
  { label: "5日", days: 5 },
  { label: "10日", days: 10 },
  { label: "20日", days: 20 },
  { label: "60日", days: 60 },
  { label: "120日", days: 120 },
  { label: "240日", days: 240 },
  { label: "2年", days: 480 },
] as const;

/**
 * 分點進出共用區塊:時間範圍(1-240日+自訂)+ N 日淨流/家數摘要 + 前 13 大買/賣超列表。
 * 個股頁 K 線視圖下方的唯一分點區（WP-H4 升級版）：
 * - 傳入 score/reasons 時顯示分點分徽章與理由膠囊
 * - heading 控制頂部標題顯示
 * - id 供 #branch 錨點捲動
 * - 手機版(<768px)：買/賣超改 segmented tabs(預設買超)，單欄顯示；勾選後顯示浮動回饋 chip
 * 桌機版維持雙欄(逐位元不變)。
 */
/** 圖表疊加勾選上限:超過視覺與效能都失焦 */
export const MAX_SELECTED_BRANCHES = 10;

const BranchFlowSection = forwardRef<
  HTMLElement,
  {
    branches: StockJson["branches"];
    branchHistory: StockJson["branch_history"];
    score?: number | null;
    reasons?: ReasonItem[];
    heading?: string;
    id?: string;
    /** 已勾選分點名集合(K 線視圖用,狀態上提到個股頁);與 onToggleSelect 同時傳入才顯示 checkbox */
    selected?: Set<string>;
    onToggleSelect?: (name: string) => void;
  }
>(function BranchFlowSection(
  {
    branches,
    branchHistory,
    score,
    reasons,
    heading,
    id,
    selected,
    onToggleSelect,
  },
  ref
) {
  const [days, setDays] = useState<number | "custom">(5);
  const [customDays, setCustomDays] = useState<string>("5");
  const [expandedBranch, setExpandedBranch] = useState<string | null>(null);
  // 手機版：買/賣超 segmented tab（預設買超）
  const [mobileTab, setMobileTab] = useState<"buy" | "sell">("buy");
  // 勾選回饋 chip 顯示狀態（手機版：勾選後 3 秒顯示）
  const [showSelectFeedback, setShowSelectFeedback] = useState(false);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeDays = days === "custom" ? parseInt(customDays) || 1 : days;

  // 勾選分點時觸發手機回饋 chip
  const prevSelectedSize = useRef(selected?.size ?? 0);
  useEffect(() => {
    const cur = selected?.size ?? 0;
    if (cur !== prevSelectedSize.current) {
      prevSelectedSize.current = cur;
      if (cur > 0) {
        setShowSelectFeedback(true);
        if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
        feedbackTimerRef.current = setTimeout(() => setShowSelectFeedback(false), 3000);
      } else {
        setShowSelectFeedback(false);
      }
    }
    return () => {
      if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
    };
  }, [selected?.size]);

  const agg = useMemo(() => {
    if (!branchHistory?.length) {
      const buyers = branches.filter((b) => b.net > 0).sort((a, b) => b.net - a.net);
      const sellers = branches.filter((b) => b.net < 0).sort((a, b) => a.net - b.net);
      return {
        buyers, sellers,
        top13Buy: buyers.slice(0, 13).map((b) => ({ name: b.name, buy: b.buy, sell: b.sell, net: b.net, history: [] })),
        top13Sell: sellers.slice(0, 13).map((b) => ({ name: b.name, buy: b.buy, sell: b.sell, net: b.net, history: [] })),
      };
    }

    const sliced = branchHistory.slice(0, activeDays);
    const map: Record<string, { buy: number; sell: number; net: number }> = {};
    const allDates = sliced.map((s) => s.t).reverse();

    for (const day of sliced) {
      for (const b of day.branches) {
        if (!map[b.n]) map[b.n] = { buy: 0, sell: 0, net: 0 };
        map[b.n].buy += b.b;
        map[b.n].sell += b.s;
        map[b.n].net += b.net;
      }
    }

    const arr = Object.keys(map).map((name) => ({ name, ...map[name] }));
    const buyers = arr.filter((x) => x.net > 0).sort((a, b) => b.net - a.net);
    const sellers = arr.filter((x) => x.net < 0).sort((a, b) => a.net - b.net);

    const top13Buy = buyers.slice(0, 13).map((b) => {
      const history = allDates.map((dt) => {
        const dObj = sliced.find((s) => s.t === dt);
        const bObj = dObj?.branches.find((x) => x.n === b.name);
        return { t: dt, net: bObj ? bObj.net : 0 };
      });
      return { ...b, history };
    });

    const top13Sell = sellers.slice(0, 13).map((b) => {
      const history = allDates.map((dt) => {
        const dObj = sliced.find((s) => s.t === dt);
        const bObj = dObj?.branches.find((x) => x.n === b.name);
        return { t: dt, net: bObj ? bObj.net : 0 };
      });
      return { ...b, history };
    });

    return { buyers, sellers, top13Buy, top13Sell };
  }, [branchHistory, branches, activeDays]);

  // 無 branch_history 且無當日 branches:整節收合為教育性空狀態(一行,不佔版面)。
  // 分點 Tab 情境(score 已帶)仍渲染分點分卡,交由外層守衛處理完全無資料的情況。
  if (score == null && !branches.length && !branchHistory?.length) {
    return (
      <section
        ref={ref}
        id={id}
        className="mt-3.5 rounded-[var(--r-md)] border border-border bg-card px-4.5 py-3 text-xs text-muted-foreground"
      >
        尚無此股分點進出資料。免費資料僅抓評分池前 80 檔的前 15 大買賣超,會隨每日累積增加。
      </section>
    );
  }

  const netTotal = agg.buyers.reduce((sum, b) => sum + b.net, 0) + agg.sellers.reduce((sum, b) => sum + b.net, 0);
  const selectable = onToggleSelect != null && !!branchHistory?.length;
  const atLimit = (selected?.size ?? 0) >= MAX_SELECTED_BRANCHES;
  const selectedCount = selected?.size ?? 0;

  return (
    <section
      ref={ref}
      id={id}
      className="mt-3.5 grid gap-3 overflow-x-auto rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]"
    >
      {heading && (
        <div className="flex flex-col gap-0.5">
          <h2 className="text-[15px] font-bold text-foreground">{heading}</h2>
          <span className="text-[11px] text-muted-foreground">盤後 T+1、每日前 15 大買賣超裁剪版,資料自累積起,僅供籌碼觀察。</span>
        </div>
      )}

      {/* 分點分卡 + 摘要統計 */}
      <div className={cn("grid grid-cols-2 gap-2.5", score != null ? "md:grid-cols-[1.1fr_repeat(3,1fr)]" : "md:grid-cols-3")}>
        {score != null && (
          <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
            <span className="text-[11px] text-muted-foreground">分點分</span>
            <span className="num text-[30px] leading-none font-extrabold text-warn">{score ?? "—"}</span>
          </div>
        )}
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">{activeDays}日買超分點</span>
          <span className="num text-base font-bold text-foreground">{agg.buyers.length}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">{activeDays}日賣超分點</span>
          <span className="num text-base font-bold text-foreground">{agg.sellers.length}</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">{activeDays}日淨流</span>
          <span className={cn("num text-base font-bold", netTotal > 0 ? "text-up" : netTotal < 0 ? "text-down" : "text-foreground")}>
            {fmtLots(netTotal)}張
          </span>
        </div>
      </div>

      {/* 分點理由 pills（WP-H2 語意家族色，升級版分點區）*/}
      {reasons != null && (
        <div className="flex flex-wrap gap-1.5">
          {reasons.length > 0 ? (
            reasons.map((r) => <ReasonPill key={r.code} code={r.code} text={r.text} />)
          ) : (
            <span className="rounded-full border border-[color:var(--line)] px-2 py-[3px] text-[11.5px] text-[color:var(--ink-2)]">
              今日未觸發分點加分條件
            </span>
          )}
        </div>
      )}

      {/* 時間範圍選擇:手機版單行橫滑，自訂 inputmode=numeric */}
      <div className="mb-3.5">
        <div
          role="tablist"
          className="flex w-fit max-w-full flex-nowrap overflow-x-auto gap-0.5 rounded-full border border-border bg-card p-[3px] scrollbar-hide"
        >
          {BRANCH_RANGES.map((r) => (
            <button key={r.days} role="tab" aria-selected={days === r.days} className={cn(pillTabClass(days === r.days), "shrink-0")} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
          <div className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full pr-1", days === "custom" && "bg-muted shadow-[inset_0_0_0_1px_var(--border-strong)]")}>
            <button role="tab" aria-selected={days === "custom"} className={pillTabClass(false)} onClick={() => setDays("custom")}>
              自訂
            </button>
            {days === "custom" && (
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={480}
                value={customDays}
                onChange={(e) => setCustomDays(e.target.value)}
                className="num w-[50px] rounded-md border border-[color:var(--line)] bg-card px-1.5 py-0.5 text-xs text-foreground outline-none focus:border-primary"
                placeholder="天數"
                aria-label="自訂聚合天數"
              />
            )}
          </div>
        </div>
      </div>

      {/* 勾選提示（桌機版文字說明）*/}
      {selectable && (
        <div className="hidden md:block text-[11px] text-muted-foreground" aria-live="polite">
          勾選分點後,於上方 K 線圖疊加「分點進出」柱狀圖(最多 {MAX_SELECTED_BRANCHES} 個
          {atLimit ? ",已達上限,取消其他勾選後才能再加" : `,已勾選 ${selectedCount} 個`})。
        </div>
      )}

      {/* 手機版：買超/賣超 segmented tab selector */}
      <div className="md:hidden flex gap-1 rounded-lg border border-border bg-card p-0.5 w-fit">
        <button
          className={cn(
            "rounded-md px-4 py-1.5 text-xs font-semibold transition-colors",
            mobileTab === "buy"
              ? "bg-up/15 text-up shadow-[inset_0_0_0_1px_rgba(230,103,103,0.4)]"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setMobileTab("buy")}
          aria-pressed={mobileTab === "buy"}
        >
          買超 ({agg.top13Buy.length})
        </button>
        <button
          className={cn(
            "rounded-md px-4 py-1.5 text-xs font-semibold transition-colors",
            mobileTab === "sell"
              ? "bg-down/15 text-down shadow-[inset_0_0_0_1px_rgba(12,163,12,0.4)]"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => setMobileTab("sell")}
          aria-pressed={mobileTab === "sell"}
        >
          賣超 ({agg.top13Sell.length})
        </button>
      </div>

      {/* 手機版：單欄顯示（< 768px），桌機版：雙欄 */}
      <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
        {/* 買超欄：手機版只在 buy tab 時顯示 */}
        <div className={cn("flex flex-col gap-2.5 rounded-[var(--r-md)] border border-border bg-secondary p-3", mobileTab !== "buy" && "hidden md:flex")}>
          <h3 className="mb-1 border-b border-[color:var(--line)] pb-2 text-center text-[14.5px] font-bold text-up">前 13 大買超分點</h3>
          <div className="flex flex-col gap-1.5">
            {agg.top13Buy.map((b) => (
              <BranchRow
                key={b.name}
                b={b}
                expanded={expandedBranch === b.name}
                onToggle={() => setExpandedBranch(expandedBranch === b.name ? null : b.name)}
                selected={selected?.has(b.name) ?? false}
                onSelect={selectable ? onToggleSelect : undefined}
                selectDisabled={atLimit}
              />
            ))}
            {agg.top13Buy.length === 0 && <div className="py-[46px] text-center text-sm text-muted-foreground">無買超紀錄</div>}
          </div>
        </div>
        {/* 賣超欄：手機版只在 sell tab 時顯示 */}
        <div className={cn("flex flex-col gap-2.5 rounded-[var(--r-md)] border border-border bg-secondary p-3", mobileTab !== "sell" && "hidden md:flex")}>
          <h3 className="mb-1 border-b border-[color:var(--line)] pb-2 text-center text-[14.5px] font-bold text-down">前 13 大賣超分點</h3>
          <div className="flex flex-col gap-1.5">
            {agg.top13Sell.map((b) => (
              <BranchRow
                key={b.name}
                b={b}
                expanded={expandedBranch === b.name}
                onToggle={() => setExpandedBranch(expandedBranch === b.name ? null : b.name)}
                selected={selected?.has(b.name) ?? false}
                onSelect={selectable ? onToggleSelect : undefined}
                selectDisabled={atLimit}
              />
            ))}
            {agg.top13Sell.length === 0 && <div className="py-[46px] text-center text-sm text-muted-foreground">無賣超紀錄</div>}
          </div>
        </div>
      </div>

      {!heading && (
        <div className="text-xs leading-relaxed text-muted-foreground">
          分點資料來自免費公開頁的前15大買賣超裁剪版,不是全市場全量分點;T+1 盤後資料,僅供籌碼觀察。
        </div>
      )}

      {/* 手機版：勾選分點後的浮動回饋 chip（固定在畫面右下角，3秒後自動消失）*/}
      {selectable && showSelectFeedback && selectedCount > 0 && (
        <div
          className="fixed bottom-20 right-4 z-50 flex items-center gap-2 rounded-full border border-[color:var(--border-strong)] bg-card px-3.5 py-2 text-[12.5px] font-semibold text-foreground shadow-[0_4px_16px_rgba(0,0,0,0.4)] md:hidden"
          role="status"
          aria-live="polite"
        >
          <span className="h-2 w-2 rounded-full bg-primary" />
          已疊圖 {selectedCount} 檔 ↑
        </div>
      )}
    </section>
  );
});

BranchFlowSection.displayName = "BranchFlowSection";

export default BranchFlowSection;

function BranchRow({
  b,
  expanded,
  onToggle,
  selected,
  onSelect,
  selectDisabled,
}: {
  b: { name: string; net: number; history?: { t: string; net: number }[] };
  expanded: boolean;
  onToggle: () => void;
  selected?: boolean;
  onSelect?: (name: string) => void;
  selectDisabled?: boolean;
}) {
  const maxNet = b.history?.length ? Math.max(...b.history.map((h) => Math.abs(h.net))) || 1 : 1;
  const checkboxOff = !!selectDisabled && !selected; // 已勾到上限時,未勾選的暫時不可再加
  return (
    <div className="overflow-hidden rounded-[var(--r-sm)] border border-border bg-card transition-[box-shadow,border-color] hover:border-[color:var(--border-strong)] hover:shadow-[0_2px_6px_rgba(0,0,0,0.2)]">
      <div className="flex items-stretch">
        {onSelect && (
          <label
            className={cn(
              "flex min-h-11 w-10 shrink-0 cursor-pointer items-center justify-center border-r border-[color:var(--line)]",
              checkboxOff && "cursor-not-allowed opacity-40",
            )}
          >
            <input
              type="checkbox"
              className="h-4 w-4 accent-[var(--primary)]"
              checked={!!selected}
              disabled={checkboxOff}
              onChange={() => onSelect(b.name)}
              aria-label={`勾選 ${b.name},於上方圖表疊加分點進出`}
            />
          </label>
        )}
        <button
          type="button"
          aria-expanded={expanded}
          className="flex min-h-11 w-full min-w-0 cursor-pointer items-baseline justify-between px-2.5 py-2 text-left text-[12.5px] select-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"
          onClick={onToggle}
        >
          <span className="truncate font-semibold text-[color:var(--ink-2)]" title={b.name}>{b.name}</span>
          <span className={cn("num font-bold", b.net > 0 ? "text-up" : b.net < 0 ? "text-down" : "text-foreground")}>{fmtLots(b.net)}張</span>
        </button>
      </div>
      {expanded && b.history && (
        <div className="mt-1 flex items-center gap-0.5 border-t border-[color:var(--line)] px-2.5 pt-2 pb-2 [height:48px]">
          {b.history.map((h) => (
            <div className="flex h-full min-w-[2px] flex-1 flex-col" key={h.t} title={`${h.t} 淨${h.net > 0 ? "買" : "賣"}: ${Math.abs(h.net)}張`}>
              <div className="flex w-full flex-1 items-end pb-px">
                {h.net > 0 && <div className="w-full rounded-sm bg-up opacity-85" style={{ height: `${(h.net / maxNet) * 100}%` }} />}
              </div>
              <div className="flex w-full flex-1 items-start pt-px">
                {h.net < 0 && <div className="w-full rounded-sm bg-down opacity-85" style={{ height: `${(Math.abs(h.net) / maxNet) * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
