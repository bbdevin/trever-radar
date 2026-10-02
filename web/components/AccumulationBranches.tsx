"use client";

import { useMemo, useState } from "react";

import {
  DEFAULT_VISIBLE,
  DEFAULT_WINDOW,
  RETAIN_MIN,
  MIN_DAYS,
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
import { fmtLots } from "@/lib/format";
import type { Candle, StockJson } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";

/**
 * 個股頁「囤貨／出貨分點」:近 1 週／1 月／3 月持續淨買(或淨賣)的分點。
 *
 * 使用者常是為了替套牢的股票找信心才來看這張卡,所以同期出貨名單永遠只差一下點擊,
 * 標頭同時列出兩邊數量,避免只看到單邊。名單本身不上紅綠(那是判決色),
 * 只有帶正負號的張數沿用全站 紅＝淨買、綠＝淨賣。
 */
export default function AccumulationBranches({
  branchHistory,
  candles,
  onOpenBranch,
}: {
  branchHistory: StockJson["branch_history"];
  candles: Candle[];
  onOpenBranch: (name: string) => void;
}) {
  const [windowKey, setWindowKey] = useState<WindowKey>(DEFAULT_WINDOW);
  const [side, setSide] = useState<Side>("acc");
  const [expanded, setExpanded] = useState(false);

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
      <div className="grid gap-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <h2 id="acc-branches-heading" className="text-[15px] font-bold text-foreground">囤貨／出貨分點</h2>
          {result.available && (
            <span className="num text-[12px] font-semibold text-foreground" data-testid="accumulation-counts">
              囤貨 {result.accCount} 個 · 出貨 {result.distCount} 個
            </span>
          )}
        </div>
        {result.available && (
          <p className="num text-[11.5px] leading-snug text-muted-foreground">
            {result.start} ～ {result.end}（{result.days} 個交易日）· 囤貨合計 {fmtLots(result.accTotal)} 張 · 出貨合計{" "}
            {fmtLots(result.distTotal)} 張 · 名單淨額 {fmtLots(result.accTotal + result.distTotal)} 張
          </p>
        )}
      </div>

      <div role="tablist" aria-label="期間" className="grid grid-cols-3 gap-1 rounded-full border border-border bg-card p-[3px]">
        {WINDOWS.map((w) => (
          <button
            key={w.key}
            type="button"
            role="tab"
            aria-selected={windowKey === w.key}
            onClick={() => chooseWindow(w.key)}
            className={cn(pillTabClass(windowKey === w.key), "min-h-11 justify-center touch-manipulation")}
          >
            {w.label}
          </button>
        ))}
      </div>

      <p className="text-[11.5px] leading-snug text-foreground">{definitionText(win.days, side)}</p>

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
                  side === s.key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {s.label} <span className="num">{s.count}</span> 個
              </button>
            ))}
          </div>

          {rows.length === 0 ? (
            <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
              這 {result.days} 個交易日沒有分點符合{side === "acc" ? "囤貨" : "出貨"}條件。
            </p>
          ) : (
            <div className="grid gap-2">
              <ol className="grid gap-1.5">
                {visibleRows(rows, expanded).map((row) => (
                  <li key={row.name}>
                    <button
                      type="button"
                      data-testid="accumulation-row"
                      onClick={() => onOpenBranch(row.name)}
                      className="grid min-h-11 w-full min-w-0 gap-0.5 rounded-[var(--r-sm)] border border-border bg-background px-2.5 py-2 text-left transition-colors hover:border-[color:var(--border-strong)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary"
                    >
                      <span className="flex min-w-0 items-baseline justify-between gap-2">
                        <span className="truncate text-[13px] font-semibold text-foreground" title={row.name}>{row.name}</span>
                        <span className={cn("num shrink-0 text-[13px] font-bold", row.net > 0 ? "text-up" : row.net < 0 ? "text-down" : "text-foreground")}>
                          {fmtLots(row.net)}張
                        </span>
                      </span>
                      <span className="num text-[11px] text-muted-foreground">
                        {side === "acc"
                          ? `買 ${row.buyLots.toLocaleString("zh-TW")} 張、賣回 ${row.sellLots.toLocaleString("zh-TW")} 張 · 留倉 ${Math.round(row.retainPct)}%`
                          : `賣 ${row.sellLots.toLocaleString("zh-TW")} 張、買回 ${row.buyLots.toLocaleString("zh-TW")} 張 · 出清 ${Math.round(row.retainPct)}%`}
                        <br />
                        買 {row.buyDays} 天／賣 {row.sellDays} 天 · 佔量 {fmtShare(row.volumeSharePct)} · 最近{side === "acc" ? "買超" : "賣超"}{" "}
                        {fmtMonthDay(row.lastDate)}
                      </span>
                    </button>
                  </li>
                ))}
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

      <div className="grid gap-0.5 text-[11px] leading-snug text-muted-foreground">
        <p>只計入每天淨買賣前 {TOP_N_PER_DAY} 大的分點，小量吃貨的會漏掉，數字是下限。</p>
        <p>囤貨不代表會漲；同期出貨也一起看。</p>
      </div>

      <details className="rounded-[var(--r-md)] border border-border bg-secondary/60 px-3 py-2 text-[11.5px] leading-relaxed text-muted-foreground">
        <summary className="cursor-pointer select-none text-[12px] font-semibold text-foreground">怎麼看</summary>
        <div className="mt-1.5 grid gap-1.5">
          <p>
            期間以這檔股票的交易日計算：1週＝{WINDOWS[0].days} 天、1月＝{WINDOWS[1].days} 天、3月＝{WINDOWS[2].days} 天，
            截至最新一天的分點資料。期間內任一天缺分點資料，整個期間就不列名單。
          </p>
          <p>
            囤貨要同時符合四件事：期間淨買至少 {MIN_LOTS} 張，且至少佔期間總成交量的 {Number((MIN_SHARE * 100).toFixed(2))}%；買超天數至少 {MIN_DAYS[WINDOWS[0].days]}／{MIN_DAYS[WINDOWS[1].days]}／
            {MIN_DAYS[WINDOWS[2].days]} 天（依期間）；留倉率 ≥{Math.round(RETAIN_MIN * 100)}%——留倉率＝期間淨買 ÷ 買超日淨買合計，看的是張數不是天數，散戶在同一分點小賣幾天不會讓大買的主力出局；最近 {RECENT_DAYS} 個交易日的淨賣
            不超過期間淨買的 {Math.round(RECENT_REVERSAL * 100)}%。出貨是完全相反的條件。買賣天數只是參考，不是門檻。
            單一分點一天的大單不算囤貨，常是鉅額交易或轉倉。
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
