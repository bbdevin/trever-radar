"use client";

import { useEffect, useMemo, useState } from "react";
import { IconFlame, IconPulse, IconRadar, IconTrend, IconZap, IconStar } from "@/components/Icons";
import MoneyFlow from "@/components/MoneyFlow";
import StockCard from "@/components/StockCard";
import { useSession, signInWithGoogle } from "@/lib/useSession";
import type { ListKey, MetaJson, RadarJson } from "@/lib/types";
import { DATASET_LABEL, SOURCE_LABEL, fmtE8 } from "@/lib/format";

const TABS: { key: ListKey; label: string; hint: string; icon: typeof IconFlame }[] = [
  { key: "score", label: "綜合", hint: "盤後綜合分數:分點/權證/技術/法人加權−風險扣分,≥65 為觀察門檻", icon: IconRadar },
  { key: "mark", label: "策略", hint: "策略: 20日內曾漲停/大漲, MACD金叉, 5日內爆量", icon: IconStar },
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
  const [tab, setTab] = useState<ListKey>("score");
  const { session, loading } = useSession();

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

  const FRESH_LABEL: Record<string, string> = {
    insti: "法人", margin: "融資券", warrant: "權證", branch: "分點",
  };
  const stale = Object.entries(radar.freshness ?? {})
    .filter(([k, v]) => k !== "quotes" && v.stale && v.date)
    .map(([k, v]) => ({ label: FRESH_LABEL[k] ?? k, date: v.date! }));

  return (
    <>
      <div className="strip">
        <div className="item">
          <span className="k">資料日</span>
          <span className="v">
            {radar.data_date}
            {stale.length > 0 && <span className="sub stale-mark">部分待更新</span>}
          </span>
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

      {stale.length > 0 && (
        <div className="notice">
          <span className="tag info">資料狀態</span>
          <span>
            {stale.map((s) => `${s.label}今日尚未公布,暫用 ${s.date}`).join("；")}
            (依交易所公布時間分批自動更新)
          </span>
        </div>
      )}

      <MoneyFlow sectors={radar.sectors} themes={radar.themes} />

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

      {tab === "mark" && !loading && !session ? (
        <div className="state" style={{ display: "flex", flexDirection: "column", gap: 16, alignItems: "center" }}>
          <span>進階策略榜單為會員專屬功能，請先登入 Google 帳號解鎖。</span>
          <button onClick={signInWithGoogle} style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid var(--border, #444)", background: "var(--panel, #222)", color: "var(--fg, #fff)", cursor: "pointer", fontSize: 14 }}>
            使用 Google 登入
          </button>
        </div>
      ) : shown.length === 0 ? (
        <div className="state">此榜今日無符合條件的股票</div>
      ) : (
        <div className="grid">
          {shown.map((s) => (
            <StockCard key={s.id} s={s} />
          ))}
        </div>
      )}

      <div className="notice warn" style={{ marginTop: 4 }}>
        <span className="tag">免責聲明</span>
        <span>{radar.note}。本系統資訊僅供參考，不構成投資建議。分點資料目前涵蓋熱門股，效力隨每日數據累積提升。</span>
      </div>
    </>
  );
}
