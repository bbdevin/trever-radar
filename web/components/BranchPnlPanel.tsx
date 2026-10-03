"use client";

import { useEffect, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import ChangeText from "@/components/ChangeText";
import SectionHeader from "@/components/SectionHeader";
import {
  DEFAULT_VISIBLE,
  PNL_FOOTER,
  PNL_FORMULA,
  PNL_HEADING,
  PNL_LEAD,
  PNL_WINDOWS,
  availableWindows,
  captionText,
  fmtMoney,
  fmtPrice,
  fmtRetPct,
  normalizePnl,
  rowNotes,
  sideCount,
  sideRows,
  splitBar,
  summaryText,
  type PnlSide,
  type PnlWindowKey,
} from "@/lib/branchPnl";
import type { BranchPnlEst, BranchPnlRow } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";

/**
 * 個股頁「區間損益（估算）」(docs/42,`pnl-avgcost-v1`)。
 *
 * 只把 pipeline 算好的估算畫出來:金額排序、賺／賠分開列、每張卡都帶「看得見幾天、
 * 還有沒有持股、有沒有找不到來源的賣出」的條件註記。這是估算,不是帳戶損益;
 * 文案鎖在 lib/branchPnl.ts 與它的測試裡。紅綠只表正負(全站慣例),金額一律帶正負號,
 * 顏色不是唯一訊號。點卡片開同一個分點下鑽畫面。
 */
const WINDOW_STORAGE_KEY = "trever.branchPnl.window";

function readStoredWindow(): PnlWindowKey | null {
  try {
    const v = window.localStorage.getItem(WINDOW_STORAGE_KEY);
    return v === "60" || v === "240" || v === "all" ? v : null;
  } catch {
    return null;
  }
}

export default function BranchPnlPanel({
  data,
  onOpenBranch,
}: {
  data: BranchPnlEst | undefined;
  onOpenBranch?: (name: string) => void;
}) {
  const est = normalizePnl(data);
  const [windowKey, setWindowKey] = useState<PnlWindowKey>("240");
  const [side, setSide] = useState<PnlSide>("gain");
  const [expanded, setExpanded] = useState(false);

  // 上次選的區間只在瀏覽器端讀,避免靜態輸出與水合不一致。
  useEffect(() => {
    const stored = readStoredWindow();
    if (stored) setWindowKey(stored);
  }, []);

  if (!est) return null;
  const keys = availableWindows(est);
  const activeKey = keys.includes(windowKey) ? windowKey : keys[0];
  const win = est.windows[activeKey]!;
  const rows = sideRows(win, side);
  const shown = expanded ? rows : rows.slice(0, DEFAULT_VISIBLE);

  const chooseWindow = (key: PnlWindowKey) => {
    setWindowKey(key);
    setExpanded(false);
    try {
      window.localStorage.setItem(WINDOW_STORAGE_KEY, key);
    } catch {
      // 寫不進去只是下次回到預設的 1 年。
    }
  };

  return (
    <section
      aria-labelledby="branch-pnl-heading"
      data-testid="branch-pnl-panel"
      className="mt-3.5 grid min-w-0 max-w-full gap-2.5 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3 shadow-[var(--shadow-card)]"
    >
      <SectionHeader
        family="chips"
        id="branch-pnl-heading"
        title={PNL_HEADING}
        meta={<span className="num">{win.first_date} ～ {est.as_of}（{win.window_days} 個可見交易日）</span>}
      />
      <p className="text-[11.5px] leading-snug text-foreground">{PNL_LEAD}</p>

      <div
        role="tablist"
        aria-label="估算區間"
        className="grid grid-cols-3 gap-0.5 rounded-full border border-border bg-card p-[3px]"
      >
        {PNL_WINDOWS.filter((w) => keys.includes(w.key)).map((w) => (
          <button
            key={w.key}
            type="button"
            role="tab"
            aria-selected={activeKey === w.key}
            data-testid={`branch-pnl-window-${w.key}`}
            onClick={() => chooseWindow(w.key)}
            className={cn(pillTabClass(activeKey === w.key), "min-h-11 touch-manipulation")}
          >
            {w.label}
          </button>
        ))}
      </div>

      <div role="tablist" aria-label="估算賺或賠" className="grid grid-cols-2 gap-1 rounded-[var(--r-md)] bg-secondary p-1">
        {(
          [
            { key: "gain" as const, label: "估算賺" },
            { key: "loss" as const, label: "估算賠" },
          ]
        ).map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={side === s.key}
            data-testid={`branch-pnl-side-${s.key}`}
            onClick={() => {
              setSide(s.key);
              setExpanded(false);
            }}
            className={cn(
              "min-h-11 rounded-[var(--r-sm)] px-2 py-1.5 text-[13px] font-semibold transition-colors touch-manipulation",
              side === s.key
                ? s.key === "gain"
                  ? "bg-up/15 text-up"
                  : "bg-down/15 text-down"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {s.label} <span className="num">{sideCount(win, s.key)}</span> 個
          </button>
        ))}
      </div>

      <p className="text-[12.5px] font-semibold text-foreground" data-testid="branch-pnl-summary">
        {summaryText(win)}
      </p>

      {rows.length === 0 ? (
        <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
          這段期間沒有分點達門檻且估算為{side === "gain" ? "賺" : "賠"}。
          {win.pairs_skipped_missing_price > 0 && ` 另有 ${win.pairs_skipped_missing_price} 個分點因交易日缺收盤價未列。`}
        </p>
      ) : (
        <div className="grid gap-2">
          <ol className="grid gap-2">
            {shown.map((row, i) => (
              <PnlCard key={row.name} row={row} rank={i + 1} onOpenBranch={onOpenBranch} />
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

      <details className="rounded-[var(--r-md)] border border-border bg-secondary/60 px-3 text-[11.5px] leading-relaxed text-muted-foreground">
        <summary className="flex min-h-11 cursor-pointer select-none items-center text-[12px] font-semibold text-foreground">怎麼算</summary>
        <div className="grid gap-1.5 pb-2.5">
          {PNL_FORMULA.map((line) => (
            <p key={line}>{line}</p>
          ))}
          {win.pairs_skipped_missing_price > 0 && (
            <p>這個區間有 {win.pairs_skipped_missing_price} 個分點因交易日缺收盤價未列。</p>
          )}
          <p className="num">定義版本 {est.definitions_version}</p>
        </div>
      </details>

      <p className="text-[11px] leading-relaxed text-muted-foreground">{PNL_FOOTER}</p>
    </section>
  );
}

/** StatTile 的同一個外觀,但數值可以換行(手機上三格各約 110px,單行放不下價格與金額)。 */
function Tile({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5 rounded-[var(--r-sm)] border border-border bg-secondary p-2">
      <span className="truncate text-[11px] text-muted-foreground">{label}</span>
      {children}
    </span>
  );
}

function PnlCard({
  row,
  rank,
  onOpenBranch,
}: {
  row: BranchPnlRow;
  rank: number;
  onOpenBranch?: (name: string) => void;
}) {
  const pct = fmtRetPct(row.ret_pct);
  const bar = splitBar(row);
  const notes = rowNotes(row);
  const body = (
    <>
      <span className="flex min-w-0 items-center gap-2">
        <span className="num grid size-6 shrink-0 place-items-center rounded-full bg-secondary text-[11.5px] font-bold text-foreground">
          {rank}
        </span>
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-foreground" title={row.name}>
          {row.name}
        </span>
        {onOpenBranch && <ChevronRight size={16} aria-hidden className="shrink-0 text-muted-foreground" />}
      </span>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <span className="num text-[22px] font-extrabold leading-tight">
          <ChangeText text={fmtMoney(row.est_total)} />
        </span>
        {pct && (
          <span className="num text-[11.5px] text-muted-foreground">
            對最大持有成本 <ChangeText text={pct} />
          </span>
        )}
      </span>
      <span className="grid grid-cols-3 gap-1.5">
        <Tile label="均價→現價">
          <span className="num block text-[13px] font-bold text-foreground">{fmtPrice(row.avg_cost)}</span>
          <span className="num block text-[11.5px] text-muted-foreground">→ {fmtPrice(row.last_close)}</span>
        </Tile>
        <Tile label="持有（下限）">
          <span className="num block text-[13px] font-bold text-foreground">{row.pos_lots.toLocaleString("zh-TW")} 張</span>
        </Tile>
        <Tile label="已實現／未實現">
          {bar ? (
            <span aria-hidden className="mt-0.5 flex h-1.5 w-full overflow-hidden rounded-full bg-background">
              <span className="block h-full bg-primary/70" style={{ width: `${bar.realized}%` }} />
              <span className="block h-full bg-[color:var(--accent-2)]/70" style={{ width: `${bar.unrealized}%` }} />
            </span>
          ) : null}
          {/* 條的兩色各配一個同色圓點與「已／未」字樣,顏色不是唯一訊號 */}
          <span className="num mt-0.5 flex items-center gap-1 text-[11.5px] font-semibold">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-primary/70" />
            <span className="text-muted-foreground">已</span>
            <ChangeText text={fmtMoney(row.realized)} />
          </span>
          <span className="num flex items-center gap-1 text-[11.5px] font-semibold">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-[color:var(--accent-2)]/70" />
            <span className="text-muted-foreground">未</span>
            <ChangeText text={fmtMoney(row.unrealized)} />
          </span>
        </Tile>
      </span>
      <span className="num block text-[11px] text-muted-foreground">{captionText(row)}</span>
      {notes.map((n) => (
        <span key={n} className="block text-[11px] leading-snug text-[color:var(--ink-2)]">
          {n}
        </span>
      ))}
    </>
  );
  const cls = "grid w-full min-w-0 gap-1.5 rounded-[var(--r-md)] border border-border bg-background px-2.5 py-2.5 text-left";
  return (
    <li className="min-w-0">
      {onOpenBranch ? (
        <button
          type="button"
          onClick={() => onOpenBranch(row.name)}
          className={cn(cls, "min-h-11 transition-colors hover:bg-secondary/60 touch-manipulation")}
        >
          {body}
        </button>
      ) : (
        <div className={cls}>{body}</div>
      )}
    </li>
  );
}
