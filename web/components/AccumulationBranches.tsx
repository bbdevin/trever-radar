"use client";

import { useMemo, useState } from "react";

import {
  DEFAULT_VISIBLE,
  DEFAULT_WINDOW,
  RETAIN_MIN,
  HOLD_MIN,
  LONG_WINDOW_DAYS,
  MIN_DAYS,
  SHARE_FLOOR_DAYS,
  MIN_LOTS,
  MIN_SHARE,
  RECENT_DAYS,
  RECENT_REVERSAL,
  TOP_N_PER_DAY,
  WINDOWS,
  computeWindow,
  definitionText,
  fmtMonthDay,
  fmtShare,
  visibleRows,
  type AccRow,
  type Side,
  type WindowKey,
} from "@/lib/accumulation";
import { branchTags as tagsFor } from "@/lib/branchTags";
import { useBranchTrack } from "@/lib/branchTrackList";
import { fmtLots } from "@/lib/format";
import type { BranchPctileCounts, BranchTags, Candle, StockJson } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";
import { BranchTagLegend, BranchTagList, BranchTagNote, makeTagContext } from "@/components/BranchTag";
import SectionHeader from "@/components/SectionHeader";
import StatTile, { toneOf } from "@/components/StatTile";

/**
 * 個股頁「囤貨／出貨分點」:近 1 週／1 月／3 月持續淨買(或淨賣)的分點。
 *
 * 使用者常是為了替套牢的股票找信心才來看這張卡,所以同期出貨名單永遠只差一下點擊,
 * 標頭同時列出兩邊數量,避免只看到單邊。紅綠只表方向(紅＝淨買側、綠＝淨賣側,全站慣例):
 * 分頁、列左側色條與留倉／出清小條都同時有「囤貨／出貨」文字與帶正負號的張數,
 * 顏色不是唯一訊號,也不是漲跌判決(2026-10-03 使用者嫌黑白難掃讀後改版)。
 */
export default function AccumulationBranches({
  branchHistory,
  candles,
  onOpenBranch,
  branchTags,
  branchPctile,
}: {
  branchHistory: StockJson["branch_history"];
  candles: Candle[];
  onOpenBranch: (name: string) => void;
  /** 分點標籤(地緣/隔日沖/追蹤);舊 JSON 沒有時不標。 */
  branchTags?: BranchTags;
  branchPctile?: BranchPctileCounts;
}) {
  const [windowKey, setWindowKey] = useState<WindowKey>(DEFAULT_WINDOW);
  const [side, setSide] = useState<Side>("acc");
  const [expanded, setExpanded] = useState(false);
  const [tagOpen, setTagOpen] = useState<{ name: string; key: string } | null>(null);
  const { muted, added } = useBranchTrack();
  const tagCtx = useMemo(
    () => makeTagContext(branchTags, branchPctile, { muted, added }),
    [branchTags, branchPctile, muted, added],
  );

  const results = useMemo(
    () => Object.fromEntries(WINDOWS.map((w) => [w.key, computeWindow(branchHistory, candles, w.days)])),
    [branchHistory, candles],
  );

  if (!branchHistory?.length) return null;

  const win = WINDOWS.find((w) => w.key === windowKey)!;
  const result = results[windowKey];
  const rows: AccRow[] = result.available ? (side === "acc" ? result.acc : result.dist) : [];

  const chooseWindow = (key: WindowKey) => {
    setWindowKey(key);
    setExpanded(false);
  };
  const chooseSide = (s: Side) => {
    setSide(s);
    setExpanded(false);
  };

  return (
    <section
      aria-labelledby="acc-branches-heading"
      data-testid="accumulation-branches"
      className="mt-3.5 grid min-w-0 max-w-full gap-2.5 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3 shadow-[var(--shadow-card)]"
    >
      <SectionHeader
        family="chips"
        id="acc-branches-heading"
        title="囤貨／出貨分點"
        meta={
          result.available ? (
            <span className="num">
              {result.start} ～ {result.end}
              <span className="whitespace-nowrap">（{result.days} 個交易日）</span>
            </span>
          ) : undefined
        }
        right={
          result.available ? (
            <span className="num text-[12px] font-semibold text-foreground" data-testid="accumulation-counts">
              囤貨 {result.accCount} 個 · 出貨 {result.distCount} 個
            </span>
          ) : undefined
        }
      />

      {result.available && (
        <div className="grid grid-cols-3 gap-2">
          <StatTile label="囤貨合計" value={`${fmtLots(result.accTotal)} 張`} tone="up" />
          <StatTile label="出貨合計" value={`${fmtLots(result.distTotal)} 張`} tone="down" />
          <StatTile
            label="名單淨額"
            value={`${fmtLots(result.accTotal + result.distTotal)} 張`}
            tone={toneOf(result.accTotal + result.distTotal)}
          />
        </div>
      )}

      <div role="tablist" aria-label="期間" className="grid grid-cols-5 gap-0.5 rounded-full border border-border bg-card p-[3px]">
        {WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            role="tab"
            aria-selected={windowKey === w.key}
            onClick={() => chooseWindow(w.key)}
            className={cn(pillTabClass(windowKey === w.key), "min-h-11 justify-center px-1 touch-manipulation")}
          >
            {w.label}
          </button>
        ))}
      </div>

      <p className="text-[11.5px] leading-snug text-foreground">
        {side === "acc" ? "囤貨＝期間持續淨買、多半留倉的分點" : "出貨＝期間持續淨賣、沒有回補的分點"}；點分點看每日進出。
      </p>

      {!result.available ? (
        <p
          role="status"
          className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground"
        >
          {result.message}，這個期間不列名單，以免用殘缺資料誤導。可改看較短的期間。
        </p>
      ) : (
        <>
          <div role="tablist" aria-label="囤貨或出貨" className="grid grid-cols-2 gap-1 rounded-[var(--r-md)] bg-secondary p-1">
            {(
              [
                { key: "acc" as const, label: "囤貨", count: result.accCount },
                { key: "dist" as const, label: "出貨", count: result.distCount },
              ]
            ).map((s) => (
              <button
                key={s.key}
                type="button"
                role="tab"
                aria-selected={side === s.key}
                data-testid={`accumulation-side-${s.key}`}
                onClick={() => chooseSide(s.key)}
                className={cn(
                  "min-h-11 rounded-[var(--r-sm)] px-2 py-1.5 text-[13px] font-semibold transition-colors",
                  side === s.key
                    ? s.key === "acc"
                      ? "bg-up/15 text-up"
                      : "bg-down/15 text-down"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {s.label} <span className="num">{s.count}</span> 個
              </button>
            ))}
          </div>

          {rows.length === 0 ? (
            <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
              {win.days > LONG_WINDOW_DAYS
                ? side === "acc"
                  ? "這段期間沒有分點把倉位留到現在——大戶多是來回操作。"
                  : "這段期間沒有分點持續出清到現在。"
                : `這 ${result.days} 個交易日沒有分點符合${side === "acc" ? "囤貨" : "出貨"}條件。`}
            </p>
          ) : (
            <div className="grid gap-2">
              {(tagCtx.tags || tagCtx.pctile) && <BranchTagLegend ctx={tagCtx} />}
              <ol className="grid gap-1.5">
                {visibleRows(rows, expanded).map((row, index) => {
                  const tags = tagsFor(row.name, side === "acc" ? "buy" : "sell", tagCtx);
                  const open = tagOpen?.name === row.name ? tagOpen.key : null;
                  return (
                  <li key={row.name}>
                    <button
                      type="button"
                      data-testid="accumulation-row"
                      onClick={() => onOpenBranch(row.name)}
                      className={cn(
                        "grid min-h-11 w-full min-w-0 grid-cols-[20px_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5 rounded-[var(--r-sm)] border border-border border-l-[3px] bg-background py-2 pr-2.5 pl-2 text-left transition-colors hover:border-[color:var(--border-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary",
                        side === "acc" ? "border-l-up/70 hover:border-l-up/70" : "border-l-down/70 hover:border-l-down/70",
                      )}
                    >
                      <span
                        aria-hidden
                        className="num grid h-5 w-5 place-items-center rounded-full bg-secondary text-[10.5px] font-semibold text-muted-foreground"
                      >
                        {index + 1}
                      </span>
                      <span className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5">
                        <span className="min-w-0 max-w-full truncate text-[13px] font-semibold leading-5 text-foreground" title={row.name}>{row.name}</span>
                        <BranchTagList
                          tags={tags}
                          open={open}
                          onToggle={(key) =>
                            setTagOpen((cur) => (cur?.name === row.name && cur.key === key ? null : { name: row.name, key }))
                          }
                        />
                      </span>
                      <span className={cn("num shrink-0 text-[13px] font-bold leading-5", row.net > 0 ? "text-up" : row.net < 0 ? "text-down" : "text-foreground")}>
                        {fmtLots(row.net)}張
                      </span>
                      {/* 細節與小條在名稱下方自成一列(橫跨到數字欄下方,不與數字同列) */}
                      <span className="num col-span-2 col-start-2 text-[11px] text-muted-foreground">
                        {row.holdPct != null
                          ? side === "acc"
                            ? `最高持倉 ${row.peakNet.toLocaleString("zh-TW")} 張 · 現在 ${row.net.toLocaleString("zh-TW")} 張 · 保有 ${Math.round(row.holdPct)}%`
                            : `最大空出 ${(-row.troughNet).toLocaleString("zh-TW")} 張 · 現在 ${(-row.net).toLocaleString("zh-TW")} 張 · 保有 ${Math.round(row.holdPct)}%`
                          : side === "acc"
                            ? `買 ${row.buyLots.toLocaleString("zh-TW")} 張、賣回 ${row.sellLots.toLocaleString("zh-TW")} 張 · 留倉 ${Math.round(row.retainPct)}%`
                            : `賣 ${row.sellLots.toLocaleString("zh-TW")} 張、買回 ${row.buyLots.toLocaleString("zh-TW")} 張 · 出清 ${Math.round(row.retainPct)}%`}
                        <br />
                        買 {row.buyDays} 天／賣 {row.sellDays} 天 · 佔量 {fmtShare(row.volumeSharePct)} ·{" "}
                        <span className="whitespace-nowrap">
                          最近{side === "acc" ? "買超" : "賣超"} {fmtMonthDay(row.lastDate)}
                        </span>
                      </span>
                      {/* 留倉／出清率小條:數字已在上一行文字裡,條只是掃讀輔助 */}
                      <span aria-hidden className="col-span-2 col-start-2 mt-1 block h-1 w-full overflow-hidden rounded-full bg-secondary">
                        <span
                          className={cn("block h-full w-full origin-left rounded-full", side === "acc" ? "bg-up/60" : "bg-down/60")}
                          style={{ transform: `scaleX(${Math.min(100, Math.max(0, row.holdPct ?? row.retainPct)) / 100})` }}
                        />
                      </span>
                    </button>
                    <BranchTagNote tags={tags} open={open} className="px-2.5 pt-1" />
                  </li>
                  );
                })}
              </ol>
              {!expanded && rows.length > DEFAULT_VISIBLE && (
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="min-h-11 rounded-[var(--r-md)] border border-border bg-background px-3 text-[13px] font-semibold text-foreground hover:bg-secondary"
                >
                  顯示全部（{rows.length}）
                </button>
              )}
            </div>
          )}
        </>
      )}

      <details className="rounded-[var(--r-md)] border border-border bg-secondary/60 px-3 text-[11.5px] leading-relaxed text-muted-foreground">
        <summary className="cursor-pointer select-none py-2.5 text-[12px] font-semibold text-foreground">
          怎麼看<span className="font-normal text-muted-foreground">（囤貨不代表會漲；同期出貨也一起看）</span>
        </summary>
        <div className="grid gap-1.5 pb-2.5">
          <p className="text-foreground">{definitionText(win.days, side)}</p>
          <p>只計入每天淨買賣前 {TOP_N_PER_DAY} 大的分點，小量吃貨的會漏掉，數字是下限。</p>
          <p>
            期間以這檔股票的交易日計算：{WINDOWS.map((w) => `${w.label}＝${w.days} 天`).join("、")}，
            截至最新一天的分點資料。期間內任一天缺分點資料，整個期間就不列名單。
          </p>
          <p>
            囤貨要同時符合四件事：期間淨買至少 {MIN_LOTS} 張，且至少佔期間總成交量的 {Number((MIN_SHARE * 100).toFixed(2))}%（期間超過 {SHARE_FLOOR_DAYS} 天時，以 {SHARE_FLOOR_DAYS} 天的平均量計）；買超天數至少 {WINDOWS.map((w) => MIN_DAYS[w.days]).join("／")} 天（依期間）；留倉率 ≥{Math.round(RETAIN_MIN * 100)}%——留倉率＝期間淨買 ÷ 買超日淨買合計，看的是張數不是天數，散戶在同一分點小賣幾天不會讓大買的主力出局；最近 {RECENT_DAYS} 個交易日的淨賣
            不超過期間淨買的 {Math.round(RECENT_REVERSAL * 100)}%。出貨是完全相反的條件。買賣天數只是參考，不是門檻。
            單一分點一天的大單不算囤貨，常是鉅額交易或轉倉。
          </p>
          <p>
            期間超過 {LONG_WINDOW_DAYS} 天（{WINDOWS.filter((w) => w.days > LONG_WINDOW_DAYS).map((w) => w.label).join("、")}）改用持倉保有率：現在的淨持倉 ÷ 期間內曾達到的最高持倉，≥{Math.round(HOLD_MIN * 100)}% 才算，
            建倉後沒有跑掉四成以上；出貨則看賣出後有沒有被買回。這取代上面的留倉率，因為長期間的大戶常來回操作。
          </p>
          <p>
            某天沒進前 {TOP_N_PER_DAY} 大的分點，當天記為 0，不算買也不算賣。佔量＝期間淨張數 ÷ 期間總成交量。
            依期間淨張數大小排序，點分點可看它在這檔股票的每日進出。
          </p>
          <p>這是過去的進出紀錄，不是預測；同一分點可能是許多客戶合在一起的結果。</p>
        </div>
      </details>
    </section>
  );
}
