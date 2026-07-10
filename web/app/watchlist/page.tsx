"use client";

import { useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import WatchlistButton from "@/components/WatchlistButton";
import type { StockJson } from "@/lib/types";
import { chgClass, fmtPct, MARKET_LABEL } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";
import { useWatchlist } from "@/lib/watchlist";
import { cn } from "@/lib/utils";

type Row = {
  stock_id: string;
  data: StockJson | null; // null = 未入評分池,無快取 JSON
  found: boolean;
};

const CHG_TEXT: Record<string, string> = { up: "text-up", down: "text-down", flat: "text-foreground" };
const CHG_BADGE: Record<string, string> = {
  up: "text-up bg-up/15",
  down: "text-down bg-down/15",
  flat: "text-foreground bg-secondary",
};

function EmptyNotice({ children }: { children: React.ReactNode }) {
  return (
    <Alert className="mt-6 bg-card">
      <AlertDescription className="flex flex-wrap items-baseline gap-2.5 text-[13px] text-foreground">
        <span className="shrink-0 rounded-md bg-[color:var(--ink-2)]/10 px-2 py-0.5 text-[11.5px] font-bold tracking-[0.3px] text-[color:var(--ink-2)]">自選股</span>
        <span>{children}</span>
      </AlertDescription>
    </Alert>
  );
}

export default function WatchlistPage() {
  const { session, loading: sessionLoading } = useSession();
  const { items, loading: listLoading } = useWatchlist();
  const [rows, setRows] = useState<Row[] | null>(null);

  useEffect(() => {
    if (!items.length) {
      setRows([]);
      return;
    }
    let cancelled = false;
    Promise.all(
      items.map(async (it) => {
        try {
          const res = await fetch(`/data/stocks/${it.stock_id}.json`);
          if (!res.ok) return { stock_id: it.stock_id, data: null, found: false };
          const data = (await res.json()) as StockJson;
          return { stock_id: it.stock_id, data, found: true };
        } catch {
          return { stock_id: it.stock_id, data: null, found: false };
        }
      }),
    ).then((r) => { if (!cancelled) setRows(r); });
    return () => { cancelled = true; };
  }, [items]);

  if (sessionLoading) return null;

  if (!session) {
    return (
      <EmptyNotice>
        登入後可將任意個股加入自選,快速追蹤觀察價/失效價與最新綜合分。
        <Button variant="outline" size="sm" className="mt-2.5 block" onClick={signInWithGoogle}>
          以 Google 登入
        </Button>
      </EmptyNotice>
    );
  }

  if (listLoading || rows === null) {
    return (
      <div>
        <div className="my-3.5 flex gap-2.5">
          <Skeleton className="h-[64px] w-[120px] rounded-[var(--r-md)]" />
        </div>
        <div className="flex flex-col gap-2 pb-7">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-[66px] rounded-[var(--r-md)]" />
          ))}
        </div>
      </div>
    );
  }

  if (rows.length === 0) {
    return <EmptyNotice>還沒有自選股。到任一股票卡片或個股頁點右上角的星號加入。</EmptyNotice>;
  }

  return (
    <div>
      <div className="my-3.5 flex gap-2.5">
        <div className="flex flex-col gap-0.5 rounded-[var(--r-md)] border border-border bg-card p-3 shadow-[var(--shadow-card)]">
          <span className="text-[11.5px] text-muted-foreground">自選股</span>
          <span className="num text-[17px] font-bold">共 {rows.length} 檔</span>
        </div>
      </div>
      <div className="flex flex-col gap-2 pb-7">
        {rows.map((r) => (
          <WatchlistRow key={r.stock_id} row={r} />
        ))}
      </div>
    </div>
  );
}

function WatchlistRow({ row }: { row: Row }) {
  const { stock_id, data, found } = row;

  if (!found || !data) {
    return (
      <div className="flex flex-wrap items-center gap-3.5 rounded-[var(--r-md)] border border-border bg-card p-3.5 text-muted-foreground shadow-[var(--shadow-card)]">
        <div className="flex min-w-[90px] flex-col gap-0.5">
          <span className="text-xs text-muted-foreground">{stock_id}</span>
          <span className="text-[11.5px] text-muted-foreground">未入評分池(20日均額 &lt;3,000萬),無快取資料</span>
        </div>
        <WatchlistButton stockId={stock_id} />
      </div>
    );
  }

  const last = data.candles[data.candles.length - 1];
  const prev = data.candles.length > 1 ? data.candles[data.candles.length - 2] : null;
  const chg = prev ? Math.round(((last.c - prev.c) / prev.c) * 10000) / 100 : null;
  const cls = chgClass(chg);

  return (
    <a
      href={`/stock?id=${stock_id}`}
      className="flex min-h-11 flex-wrap items-center gap-3.5 rounded-[var(--r-md)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)] cursor-pointer transition-colors duration-200 hover:border-[color:var(--border-strong)]"
    >
      <div className="flex min-w-[90px] flex-col gap-0.5">
        <span className="text-sm font-bold text-foreground">{data.name}</span>
        <span className="text-[11.5px] text-muted-foreground">
          {stock_id} · {MARKET_LABEL[data.market] ?? data.market}
        </span>
      </div>
      <div className="flex min-w-[70px] flex-col items-end gap-0.5">
        <span className={cn("num text-[15px] font-bold", CHG_TEXT[cls])}>{last.c.toLocaleString("zh-TW")}</span>
        <span className={cn("num inline-block rounded-full px-2 py-px text-[12.5px] font-bold", CHG_BADGE[cls])}>{fmtPct(chg)}</span>
      </div>
      <div className="min-w-10 text-center">
        {data.scores ? (
          <span className={cn("num text-xl font-extrabold text-[color:var(--ink-2)]", data.scores.final >= 65 && "text-warn")}>
            {data.scores.final}
          </span>
        ) : (
          <span className="text-[11.5px] text-muted-foreground">未評分</span>
        )}
      </div>
      <div className="ml-auto flex flex-col gap-0.5 text-[11px]">
        {data.scores?.watch_price != null && <span className="text-[color:var(--accent-2)]">觀察 {data.scores.watch_price.toFixed(2)}</span>}
        {data.scores?.stop_price != null && <span className="text-up">失效 {data.scores.stop_price.toFixed(2)}</span>}
      </div>
      <WatchlistButton stockId={stock_id} />
    </a>
  );
}
