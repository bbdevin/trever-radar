"use client";

import { forwardRef, useMemo, useState, useEffect } from "react";
import { Clock } from "lucide-react";
import type { ReasonItem, StockJson } from "@/lib/types";
import { fmtLots } from "@/lib/format";
import { cn, pillTabClass } from "@/lib/utils";
import BuySellSplit from "@/components/BuySellSplit";
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

/** YYYY-MM-DD → M/D（掃讀用；完整日期放 title） */
function fmtMD(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!m) return isoDate;
  return `${Number(m[2])}/${Number(m[3])}`;
}

/** YYYY-MM-DD → YYYY/MM/DD */
function fmtYMD(isoDate: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!m) return isoDate;
  return `${m[1]}/${m[2]}/${m[3]}`;
}

/**
 * 籌碼日報：時間範圍(1-240日+自訂)+ N 日淨流/家數摘要 + 買超/賣超分頁列表。
 * IA-5：買超|賣超在所有斷點都是分頁，不再雙欄並排。點列開下鑽(onOpenBranch)。
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
    /** 點分點列 → 下鑽該分點進出明細+對應 K 線 */
    onOpenBranch?: (name: string) => void;
    /** 手機版浮動回饋 chip 點擊後捲動回的目標元素 id(通常為 KChart 容器)*/
    chartAnchorId?: string;
    /** 當頁最新報價交易日(通常 candles 末日);與籌碼日比對判斷是否暫用舊資料 */
    quoteDate?: string | null;
    /** 可選:與 radar.freshness.branch.stale 對齊;未傳則僅用 quoteDate 比對 */
    branchStale?: boolean;
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
    chartAnchorId,
    quoteDate,
    branchStale,
    onOpenBranch,
  },
  ref
) {
  const [days, setDays] = useState<number | "custom">(5);
  const [customDays, setCustomDays] = useState<string>("5");
  const [expandedBranch, setExpandedBranch] = useState<string | null>(null);
  const [sideTab, setSideTab] = useState<"buy" | "sell">("buy");

  const activeDaysRaw = days === "custom" ? parseInt(customDays) || 1 : days;
  /** 此股實際可用交易日數(每檔回補深度不同) */
  const availableDays = branchHistory?.length ?? 0;
  /** 聚合用天數:不超過此股真實深度 */
  const activeDays = availableDays > 0 ? Math.min(activeDaysRaw, availableDays) : activeDaysRaw;

  // 籌碼最新交易日(history 新→舊);無 history 不腦補「今日」
  const branchAsOf = branchHistory?.length ? branchHistory[0].t : null;
  /** 此股 branch_history 實際涵蓋區間(回補深度會影響最早日;每股不同) */
  const branchDepth = useMemo(() => {
    if (!branchHistory?.length) return null;
    return {
      newest: branchHistory[0].t,
      oldest: branchHistory[branchHistory.length - 1].t,
      days: branchHistory.length,
    };
  }, [branchHistory]);

  // 換股或回補加深後:若目前選的天數超過此股深度,自動降到可用最大值
  useEffect(() => {
    if (!branchDepth) return;
    if (days !== "custom" && typeof days === "number" && days > branchDepth.days) {
      const fit =
        [...BRANCH_RANGES].reverse().find((r) => r.days <= branchDepth.days)?.days ?? branchDepth.days;
      setDays(fit);
    } else if (days === "custom") {
      const n = parseInt(customDays) || 1;
      if (n > branchDepth.days) setCustomDays(String(branchDepth.days));
    }
  }, [branchDepth, days, customDays]);

  const rangeMeta = useMemo(() => {
    if (!branchHistory?.length) return null;
    const sliced = branchHistory.slice(0, activeDays);
    if (!sliced.length) return null;
    return {
      end: sliced[0].t,
      start: sliced[sliced.length - 1].t,
      available: sliced.length,
    };
  }, [branchHistory, activeDays]);

  // 過期:籌碼日 ≠ 報價日,或父層明確 stale(定死並用 OR,避免只靠一邊漏判)
  const isStale =
    !!branchAsOf &&
    ((branchStale === true) || (!!quoteDate && branchAsOf !== quoteDate));

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
  // 買賣方 Top13 一律全列顯示(不再手機先收成 8 列再「展開」)
  const buyRows = agg.top13Buy;
  const sellRows = agg.top13Sell;

  const asOfChip =
    branchAsOf != null ? (
      <span
        className={cn(
          "inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-[11.5px] font-semibold",
          isStale
            ? "border-warn/30 bg-warn/10 text-warn"
            : "border-border bg-secondary text-foreground",
        )}
        title={
          isStale
            ? `分點籌碼交易日 ${branchAsOf}，與報價日 ${quoteDate ?? "—"} 不同，勿當成最新日籌碼`
            : `分點籌碼交易日 ${branchAsOf}`
        }
        aria-label={
          isStale
            ? `籌碼暫用 ${fmtMD(branchAsOf)}，非最新報價日`
            : `籌碼日 ${fmtMD(branchAsOf)}`
        }
      >
        <Clock size={12} strokeWidth={1.8} aria-hidden />
        {isStale ? (
          <>
            <span className="font-medium">暫用</span>
            <span className="num font-bold">{fmtMD(branchAsOf)}</span>
            <span className="font-medium opacity-90">· 非今日</span>
          </>
        ) : (
          <>
            <span className="text-muted-foreground font-medium">籌碼日</span>
            <span className="num font-bold">{fmtMD(branchAsOf)}</span>
          </>
        )}
      </span>
    ) : null;

  const depthChip =
    branchDepth != null ? (
      <span
        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 text-[11.5px] font-medium text-foreground"
        title={`此檔分點進出歷史：${branchDepth.oldest} ～ ${branchDepth.newest}，共 ${branchDepth.days} 個交易日。每檔回補進度不同，最早日以本檔為準。`}
        aria-label={`此檔分點資料涵蓋 ${fmtYMD(branchDepth.oldest)} 至 ${fmtYMD(branchDepth.newest)}，共 ${branchDepth.days} 交易日`}
      >
        <span className="text-muted-foreground">此檔</span>
        <span className="num font-bold">
          {fmtYMD(branchDepth.oldest)}–{fmtYMD(branchDepth.newest)}
        </span>
        <span className="text-muted-foreground">（{branchDepth.days} 日）</span>
      </span>
    ) : null;

  const rangeHint =
    rangeMeta && activeDaysRaw > 1
      ? `已選 ${activeDaysRaw} 日${
          activeDays < activeDaysRaw ? `→實際 ${activeDays} 日` : ""
        } · ${fmtMD(rangeMeta.start)}–${fmtMD(rangeMeta.end)}（${rangeMeta.available} 交易日）· `
      : branchDepth
        ? `此檔分點 ${fmtMD(branchDepth.oldest)}–${fmtMD(branchDepth.newest)}（${branchDepth.days} 日）· `
        : branches.length
          ? "僅最新一日分點 · "
          : "";

  const shallowRange =
    branchDepth != null && activeDaysRaw > branchDepth.days;

  return (
    <section
      ref={ref}
      id={id}
      className="mt-3.5 grid min-w-0 max-w-full gap-3 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]"
    >
      {heading && (
        <div className="flex flex-col gap-0.5">
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
            <h2 className="text-[15px] font-bold text-foreground">{heading}</h2>
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              {depthChip}
              {asOfChip}
            </div>
          </div>
          <span className="text-[11px] leading-relaxed text-muted-foreground">
            {rangeHint}盤後 T+1、每日前 15 大買賣超裁剪版，僅供籌碼觀察。
          </span>
        </div>
      )}
      {!heading && (depthChip || asOfChip) && (
        <div className="flex flex-wrap justify-end gap-1.5">
          {depthChip}
          {asOfChip}
        </div>
      )}

      {/* 分點分卡 + 摘要統計：手機 2+2 對稱四格；有分點分時多一格 → 手機 3 格第一列 + 獨佔淨流 */}
      <div className={cn(
        "grid gap-2.5",
        score != null
          ? "grid-cols-2 md:grid-cols-[1.1fr_repeat(3,1fr)]"
          : "grid-cols-3 md:grid-cols-3",
      )}>
        {score != null && (
          <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
            <span className="text-[11px] text-muted-foreground">分點分</span>
            <span className="num text-[30px] leading-none font-extrabold text-warn">{score ?? "—"}</span>
          </div>
        )}
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">{activeDays}日買超</span>
          <span className="num text-base font-bold text-foreground">{agg.buyers.length} 點</span>
        </div>
        <div className="flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5">
          <span className="text-[11px] text-muted-foreground">{activeDays}日賣超</span>
          <span className="num text-base font-bold text-foreground">{agg.sellers.length} 點</span>
        </div>
        <div className={cn(
          "flex flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2.5",
          score != null ? "col-span-2 md:col-span-1" : "",
        )}>
          <span className="text-[11px] text-muted-foreground">{activeDays}日淨流</span>
          <span className={cn("num text-base font-bold", netTotal > 0 ? "text-up" : netTotal < 0 ? "text-down" : "text-foreground")}>
            {fmtLots(netTotal)} 張
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

      {/* 時間範圍：超過此股回補深度的選項 disabled */}
      <div className="mb-3.5">
        {shallowRange && branchDepth && (
          <p className="mb-2 text-[11px] font-medium text-warn" role="status">
            此檔分點僅回補到 {branchDepth.oldest}（{branchDepth.days} 交易日），已改以實際深度計算。
          </p>
        )}
        <div
          role="tablist"
          className="flex flex-wrap gap-1 rounded-[var(--r-md)] border border-border bg-card p-1.5"
        >
          {BRANCH_RANGES.map((r) => {
            const beyond = branchDepth != null && r.days > branchDepth.days;
            const selected = days === r.days;
            return (
              <button
                key={r.days}
                type="button"
                role="tab"
                aria-selected={selected}
                disabled={beyond}
                title={
                  beyond && branchDepth
                    ? `此檔僅有 ${branchDepth.days} 日分點（最早 ${branchDepth.oldest}），無法選 ${r.label}`
                    : undefined
                }
                className={cn(
                  pillTabClass(selected),
                  beyond && "cursor-not-allowed opacity-40",
                )}
                onClick={() => {
                  if (!beyond) setDays(r.days);
                }}
              >
                {r.label}
              </button>
            );
          })}
          <div className={cn("inline-flex items-center gap-1.5 rounded-full pr-1", days === "custom" && "bg-primary/10")}>
            <button
              type="button"
              role="tab"
              aria-selected={days === "custom"}
              className={pillTabClass(days === "custom")}
              onClick={() => setDays("custom")}
            >
              自訂
            </button>
            {days === "custom" && (
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={branchDepth?.days ?? 480}
                value={customDays}
                onChange={(e) => setCustomDays(e.target.value)}
                className="num w-[50px] rounded-md border border-[color:var(--line)] bg-card px-1.5 py-0.5 text-xs text-foreground outline-none focus:border-primary"
                placeholder="天數"
                aria-label={`自訂聚合天數（此檔上限 ${branchDepth?.days ?? "—"}）`}
              />
            )}
          </div>
        </div>
      </div>

      {selectable && !onOpenBranch && (
        <div className="hidden md:block text-[11px] text-muted-foreground" aria-live="polite">
          勾選分點後,於上方 K 線圖疊加「分點進出」柱狀圖(最多 {MAX_SELECTED_BRANCHES} 個
          {atLimit ? ",已達上限,取消其他勾選後才能再加" : `,已勾選 ${selectedCount} 個`})。
        </div>
      )}
      {onOpenBranch && (
        <p className="text-[11px] text-muted-foreground">點分點可看該券商在此股的進出明細與對應 K 線。</p>
      )}

      <BuySellSplit
        value={sideTab}
        onChange={setSideTab}
        buyLabel={`買方 Top${agg.top13Buy.length || 13}`}
        sellLabel={`賣方 Top${agg.top13Sell.length || 13}`}
      />

      <div className="flex flex-col gap-2.5 rounded-[var(--r-md)] border border-border bg-secondary p-3">
        <h3 className={cn("mb-1 border-b border-[color:var(--line)] pb-2 text-center text-[14.5px] font-bold", sideTab === "buy" ? "text-up" : "text-down")}>
          {sideTab === "buy" ? "前 13 大買超分點" : "前 13 大賣超分點"}
        </h3>
        <div className="flex flex-col gap-1.5">
          {(sideTab === "buy" ? buyRows : sellRows).map((b) => (
            <BranchRow
              key={b.name}
              b={b}
              expanded={!onOpenBranch && expandedBranch === b.name}
              onToggle={() => setExpandedBranch(expandedBranch === b.name ? null : b.name)}
              onOpen={onOpenBranch ? () => onOpenBranch(b.name) : undefined}
              selected={selected?.has(b.name) ?? false}
              onSelect={selectable && !onOpenBranch ? onToggleSelect : undefined}
              selectDisabled={atLimit}
            />
          ))}
          {sideTab === "buy" && agg.top13Buy.length === 0 && (
            <div className="py-[46px] text-center text-sm text-muted-foreground">無買超紀錄</div>
          )}
          {sideTab === "sell" && agg.top13Sell.length === 0 && (
            <div className="py-[46px] text-center text-sm text-muted-foreground">無賣超紀錄</div>
          )}
        </div>
      </div>

      {!heading && (
        <div className="text-xs leading-relaxed text-muted-foreground">
          分點資料來自免費公開頁的前15大買賣超裁剪版,不是全市場全量分點;T+1 盤後資料,僅供籌碼觀察。
        </div>
      )}

      {/* 手機版:勾選分點後右下浮動回饋 chip;N>0 常駐(點擊捲回上方 KChart),N=0 隱藏;桌機不顯示(圖就在上方) */}
      {selectable && selectedCount > 0 && (
        <button
          type="button"
          onClick={() => {
            if (chartAnchorId) document.getElementById(chartAnchorId)?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          className="fixed z-30 flex min-h-11 items-center gap-2 rounded-full border border-[color:var(--border-strong)] bg-card px-3.5 py-2 text-[12.5px] font-semibold text-foreground shadow-[0_4px_16px_rgba(0,0,0,0.4)] md:hidden"
          style={{
            bottom: "calc(5rem + env(safe-area-inset-bottom, 0px))",
            right: "max(1rem, env(safe-area-inset-right, 0px))",
          }}
          aria-label={`已疊圖 ${selectedCount} 檔,點擊回到上方圖表`}
        >
          <span className="h-2 w-2 rounded-full bg-primary" />
          已疊圖 {selectedCount} 檔 ↑
        </button>
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
  onOpen,
  selected,
  onSelect,
  selectDisabled,
}: {
  b: { name: string; net: number; history?: { t: string; net: number }[] };
  expanded: boolean;
  onToggle: () => void;
  onOpen?: () => void;
  selected?: boolean;
  onSelect?: (name: string) => void;
  selectDisabled?: boolean;
}) {
  const history = b.history ?? [];
  const maxNet = history.length ? Math.max(...history.map((h) => Math.abs(h.net)), 1) : 1;
  const checkboxOff = !!selectDisabled && !selected; // 已勾到上限時,未勾選的暫時不可再加
  return (
    <div
      className={cn(
        "rounded-[var(--r-sm)] border border-border bg-card transition-[box-shadow,border-color] hover:border-[color:var(--border-strong)] hover:shadow-[0_2px_6px_rgba(0,0,0,0.2)]",
        !expanded && "overflow-hidden",
      )}
    >
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
          aria-expanded={onOpen ? undefined : expanded}
          className="flex min-h-11 w-full min-w-0 cursor-pointer items-baseline justify-between px-2.5 py-2 text-left text-[12.5px] select-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"
          onClick={onOpen ?? onToggle}
        >
          <span className="truncate font-semibold text-[color:var(--ink-2)]" title={b.name}>{b.name}</span>
          <span className={cn("num font-bold", b.net > 0 ? "text-up" : b.net < 0 ? "text-down" : "text-foreground")}>{fmtLots(b.net)}張</span>
        </button>
      </div>
      {expanded && (
        <div className="border-t border-[color:var(--line)] px-2.5 pt-2 pb-2.5">
          {history.length === 0 ? (
            <p className="py-2 text-center text-[11px] text-muted-foreground">此區間無日別明細（僅有當日彙總）</p>
          ) : (
            <div
              className="overflow-x-auto scrollbar-hide [-webkit-overflow-scrolling:touch]"
              role="region"
              aria-label={`${b.name} 近 ${history.length} 日淨買賣明細`}
            >
              <div className="flex min-w-max items-end gap-px py-0.5" style={{ height: 56 }}>
                {history.map((h) => {
                  const barH = h.net !== 0 ? Math.max(3, Math.round((Math.abs(h.net) / maxNet) * 26)) : 0;
                  return (
                    <div
                      key={h.t}
                      className="flex w-[5px] shrink-0 flex-col justify-center"
                      title={`${h.t} 淨${h.net > 0 ? "買" : h.net < 0 ? "賣" : "—"}: ${Math.abs(h.net)}張`}
                    >
                      {h.net > 0 ? (
                        <div className="flex h-[26px] flex-col justify-end">
                          <div className="w-full rounded-sm bg-up opacity-90" style={{ height: barH }} />
                        </div>
                      ) : h.net < 0 ? (
                        <div className="flex h-[26px] flex-col justify-start">
                          <div className="w-full rounded-sm bg-down opacity-90" style={{ height: barH }} />
                        </div>
                      ) : (
                        <div className="mx-auto h-0.5 w-full rounded-full bg-[color:var(--line)]" />
                      )}
                    </div>
                  );
                })}
              </div>
              <p className="mt-1 text-center text-[10px] text-muted-foreground md:hidden">← 左右滑動查看更多交易日 →</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
