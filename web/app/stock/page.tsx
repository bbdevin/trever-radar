"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import KChart from "@/components/KChart";
import type { StockJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct } from "@/lib/format";

function StockView() {
  const id = useSearchParams().get("id");
  const [data, setData] = useState<StockJson | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!id) return;
    fetch(`/data/stocks/${id}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [id]);

  if (!id) return <div className="state">網址缺少股票代號(?id=2330)</div>;
  if (error)
    return (
      <div className="state">
        尚無 {id} 的個股資料檔。目前僅產出雷達清單內的股票,之後擴大到全候選池。
      </div>
    );
  if (!data) return <div className="state">載入中…</div>;

  const cs = data.candles;
  const last = cs[cs.length - 1];
  const prev = cs.length > 1 ? cs[cs.length - 2] : null;
  const chg = prev ? ((last.c - prev.c) / prev.c) * 100 : null;

  return (
    <>
      <div className="stock-head">
        <a className="back" href="/">
          ← 今日雷達
        </a>
        <span className="sid">{data.id}</span>
        <span className="sname">{data.name}</span>
        <span className="chip">{MARKET_LABEL[data.market] ?? data.market}</span>
        <span className="close">{last.c.toLocaleString("zh-TW")}</span>
        <span className={`chg ${chgClass(chg)}`}>{fmtPct(chg == null ? null : Math.round(chg * 100) / 100)}</span>
        <span className="meta">
          {last.t}|量 {last.v.toLocaleString("zh-TW")} 張|額 {fmtE8(last.amt)}|共 {cs.length} 個交易日
        </span>
      </div>
      <KChart candles={cs} />
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
