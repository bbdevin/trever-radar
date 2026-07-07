"use client";

import { useEffect, useMemo, useState } from "react";
import { IconFlame, IconPulse, IconTrend, IconZap } from "@/components/Icons";
import SectorPanel from "@/components/SectorPanel";
import StockCard from "@/components/StockCard";
import type { ListKey, MetaJson, RadarJson } from "@/lib/types";
import { DATASET_LABEL, SOURCE_LABEL, fmtE8 } from "@/lib/format";

const TABS: { key: ListKey; label: string; hint: string; icon: typeof IconFlame }[] = [
  { key: "hot", label: "熱門", hint: "成交金額最大", icon: IconFlame },
  { key: "surge", label: "爆量", hint: "量比 = 今日量/20日均量,≥1.5 且金額 ≥1億", icon: IconZap },
  { key: "strong", label: "強勢", hint: "漲幅排序,金額 ≥1億", icon: IconTrend },
  { key: "warrant", label: "權證", hint: "認購權證成交金額相對20日均值放大", icon: IconPulse },
];

function Skeleton() {
  return (
    <>
      <div className="strip">
        {[0, 1, 2].map((i) => (
          <div className="sk sk-strip" key={i} />
        ))}
      </div>
      <div className="sk sk-panel" />
      <div className="grid">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div className="sk sk-card" key={i} />
        ))}
      </div>
    </>
  );
}

export default function RadarPage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [meta, setMeta] = useState<MetaJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<ListKey>("hot");

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

  const shown = useMemo(() => {
    if (!radar) return [];
    const byId = new Map(radar.stocks.map((s) => [s.id, s]));
    return (radar.lists?.[tab] ?? []).map((id) => byId.get(id)!).filter(Boolean);
  }, [radar, tab]);

  if (error) {
    return (
      <div className="state">
        找不到資料檔。請先執行管線:<code>python -m radar import-daily</code> 再{" "}
        <code>python -m radar export-json</code>
      </div>
    );
  }
  if (!radar) return <Skeleton />;

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

      <SectorPanel sectors={radar.sectors} />

      <div className="tabbar">
        <div className="seg" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key)}
              title={t.hint}
            >
              <t.icon size={15} />
              {t.label}
              <small>{radar.lists?.[t.key]?.length ?? 0}</small>
            </button>
          ))}
        </div>
        <span className="tabhint">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {shown.length === 0 ? (
        <div className="state">此榜今日無符合條件的股票</div>
      ) : (
        <div className="grid">
          {shown.map((s) => (
            <StockCard key={s.id} s={s} />
          ))}
        </div>
      )}

      <div className="notice warn" style={{ marginTop: 4 }}>
        <span className="tag">建置中</span>
        <span>{radar.note}。評分模組完成後,將加入「盤後綜合分數」榜與觸發理由、風險提醒。</span>
      </div>
    </>
  );
}
