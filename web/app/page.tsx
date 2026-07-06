"use client";

import { useEffect, useState } from "react";
import StockCard from "@/components/StockCard";
import type { MetaJson, RadarJson } from "@/lib/types";
import { DATASET_LABEL, SOURCE_LABEL, fmtE8 } from "@/lib/format";

export default function RadarPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));
    fetch("/data/meta.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setMeta)
      .catch(() => {});
  }, []);

  if (error) {
    return (
      <div className="state">
        找不到資料檔。請先執行管線:<code>python -m radar import-daily</code> 再{" "}
        <code>python -m radar export-json</code>
      </div>
    );
  }
  if (!radar) return <div className="state">載入中…</div>;

  const missing = (meta?.datasets ?? []).filter(
    (d) => d.date === radar.data_date && d.status !== "ok",
  );

  return (
    <>
      <div className="strip">
        <div className="item">
          <span className="k">資料日</span>
          <span className="v">{radar.data_date}</span>
        </div>
        {radar.summary.map((m) => (
          <div className="item" key={m.market}>
            <span className="k">{SOURCE_LABEL[m.market] ?? m.market}成交金額</span>
            <span className="v">
              {fmtE8(m.turnover)}
              <span className="sub">
                <span className="up">↑{m.up}</span> / <span className="down">↓{m.down}</span> 家
              </span>
            </span>
          </div>
        ))}
      </div>

      <div className="notice warn">
        <span className="tag">建置中</span>
        <span>{radar.note}。評分模組完成後,將依「盤後綜合分數」排序並附觸發理由與風險提醒。</span>
      </div>

      {missing.length > 0 && (
        <div className="notice">
          <span className="tag" style={{ color: "var(--ink-3)" }}>
            資料狀態
          </span>
          <span>
            尚未取得:
            {missing
              .map((d) => `${SOURCE_LABEL[d.source] ?? d.source}${DATASET_LABEL[d.dataset] ?? d.dataset}`)
              .join("、")}
            (交易所公布後重跑匯入即補齊)
          </span>
        </div>
      )}

      <div className="grid">
        {radar.stocks.map((s) => (
          <StockCard key={s.id} s={s} />
        ))}
      </div>
    </>
  );
}
