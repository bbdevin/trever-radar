"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { IconArrowLeft } from "@/components/Icons";
import KChart from "@/components/KChart";
import type { StockJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct } from "@/lib/format";

const RANGES = [
  { key: "1m", label: "1月", days: 22 },
  { key: "3m", label: "3月", days: 66 },
  { key: "1y", label: "1年", days: 240 },
  { key: "5y", label: "5年", days: 1200 },
  { key: "all", label: "全部", days: Infinity },
] as const;

function StockView() {
  const id = useSearchParams().get("id");
  const [data, setData] = useState<StockJson | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1y");

  useEffect(() => {
    if (!id) return;
    fetch(`/data/stocks/${id}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [id]);

  const candles = useMemo(() => {
    if (!data) return [];
    const days = RANGES.find((r) => r.key === range)?.days ?? Infinity;
    return days === Infinity ? data.candles : data.candles.slice(-days);
  }, [data, range]);

  if (!id) return <div className="state">網址缺少股票代號(?id=2330)</div>;
  if (error)
    return (
      <div className="state">
        尚無 {id} 的個股資料檔。目前僅產出雷達榜單內的股票,之後擴大到全候選池。
      </div>
    );
  if (!data)
    return (
      <>
        <div className="sk sk-strip" style={{ margin: "16px 0 10px" }} />
        <div className="sk" style={{ height: "52vh", borderRadius: 16 }} />
      </>
    );

  const cs = data.candles;
  const last = cs[cs.length - 1];
  const prev = cs.length > 1 ? cs[cs.length - 2] : null;
  const chg = prev ? Math.round(((last.c - prev.c) / prev.c) * 10000) / 100 : null;

  return (
    <>
      <div className="stock-head">
        <a className="back" href="/">
          <IconArrowLeft size={16} />
          雷達
        </a>
        <span className="sname">{data.name}</span>
        <span className="sid">
          {data.id} · {MARKET_LABEL[data.market] ?? data.market}
        </span>
        <div className="price-group">
          <span className="close">{last.c.toLocaleString("zh-TW")}</span>
          <span className={`chg-badge ${chgClass(chg)}`}>{fmtPct(chg)}</span>
        </div>
      </div>
      <div className="stock-meta">
        <span>
          {last.t} · 量 <span className="num">{last.v.toLocaleString("zh-TW")}</span> 張 · 額{" "}
          <span className="num">{fmtE8(last.amt)}</span>
        </span>
        <span>
          資料 <span className="num">{cs.length.toLocaleString("zh-TW")}</span> 個交易日(自 {cs[0].t})
        </span>
      </div>
      <div className="range-bar" role="tablist">
        {RANGES.map((r) => (
          <button
            key={r.key}
            role="tab"
            aria-selected={range === r.key}
            className={range === r.key ? "active" : ""}
            onClick={() => setRange(r.key)}
          >
            {r.label}
          </button>
        ))}
      </div>
      <KChart candles={candles} />
      <div className="notice" style={{ marginTop: 14 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>預告</span>
        <span>均線、布林、訊號標記與分點足跡將於評分模組與分點資料接上後疊加於此圖。</span>
      </div>
    </>
  );
}

export default function StockPage() {
  return (
    <Suspense fallback={<div className="state">載入中…</div>}>
      <StockView />
    </Suspense>
  );
}
