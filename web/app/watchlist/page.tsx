"use client";

import { useEffect, useState } from "react";
import WatchlistButton from "@/components/WatchlistButton";
import type { StockJson } from "@/lib/types";
import { chgClass, fmtPct, MARKET_LABEL } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";
import { useWatchlist } from "@/lib/watchlist";

type Row = {
  stock_id: string;
  data: StockJson | null; // null = 未入評分池,無快取 JSON
  found: boolean;
};

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
      <div className="notice" style={{ marginTop: 24 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>自選股</span>
        <span>
          登入後可將任意個股加入自選,快速追蹤觀察價/失效價與最新綜合分。
        </span>
        <button className="auth-btn" style={{ marginTop: 10 }} onClick={signInWithGoogle}>
          以 Google 登入
        </button>
      </div>
    );
  }

  if (listLoading || rows === null) {
    return <div className="sk sk-strip" style={{ margin: "16px 0" }} />;
  }

  if (rows.length === 0) {
    return (
      <div className="notice" style={{ marginTop: 24 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>自選股</span>
        <span>還沒有自選股。到任一股票卡片或個股頁點右上角的星號加入。</span>
      </div>
    );
  }

  return (
    <div className="watchlist-page">
      <div className="strip">
        <div className="item">
          <span className="k">自選股</span>
          <span className="v">共 {rows.length} 檔</span>
        </div>
      </div>
      <div className="watchlist-list">
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
      <div className="watchlist-row watchlist-row-empty">
        <div className="wl-id">
          <span className="sid">{stock_id}</span>
          <span className="k">未入評分池(20日均額 &lt;3,000萬),無快取資料</span>
        </div>
        <WatchlistButton stockId={stock_id} />
      </div>
    );
  }

  const last = data.candles[data.candles.length - 1];
  const prev = data.candles.length > 1 ? data.candles[data.candles.length - 2] : null;
  const chg = prev ? Math.round(((last.c - prev.c) / prev.c) * 10000) / 100 : null;

  return (
    <a className="watchlist-row" href={`/stock?id=${stock_id}`}>
      <div className="wl-id">
        <span className="sname">{data.name}</span>
        <span className="sid">{stock_id} · {MARKET_LABEL[data.market] ?? data.market}</span>
      </div>
      <div className="wl-price">
        <span className={`close ${chgClass(chg)}`}>{last.c.toLocaleString("zh-TW")}</span>
        <span className={`chg-badge ${chgClass(chg)}`}>{fmtPct(chg)}</span>
      </div>
      <div className="wl-score">
        {data.scores ? (
          <span className={`score-final ${data.scores.final >= 65 ? "pass" : ""}`}>
            {data.scores.final}
          </span>
        ) : (
          <span className="k">未評分</span>
        )}
      </div>
      <div className="wl-watchstop">
        {data.scores?.watch_price != null && (
          <span className="watch-price">觀察 {data.scores.watch_price.toFixed(2)}</span>
        )}
        {data.scores?.stop_price != null && (
          <span className="stop-price">失效 {data.scores.stop_price.toFixed(2)}</span>
        )}
      </div>
      <WatchlistButton stockId={stock_id} />
    </a>
  );
}
