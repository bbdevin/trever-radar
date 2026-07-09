"use client";

import { useEffect, useMemo, useState } from "react";
import { IconCompass, IconFlame } from "@/components/Icons";
import type { RadarJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtPct, fmtX } from "@/lib/format";

const TABS = [
  { key: "concentration", label: "集中度", hint: "前5大買超分點佔成交量比,躍升幅度排序", icon: IconCompass },
  { key: "theme", label: "題材", hint: "題材成分股資金流與漲跌,依成交金額排序", icon: IconFlame },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ExplorePage() {
  const [radar, setRadar] = useState<RadarJson | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<TabKey>("concentration");

  useEffect(() => {
    fetch("/data/radar.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRadar)
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="state">
        <p>資料載入失敗,請稍後再試。</p>
      </div>
    );
  }
  if (!radar) return <div className="sk sk-strip" style={{ margin: "16px 0" }} />;

  return (
    <>
      <div className="tabbar">
        <div className="seg" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key)}
            >
              <t.icon size={16} />
              {t.label}
            </button>
          ))}
        </div>
        <span className="tabhint">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "concentration" && <ConcentrationTab radar={radar} />}
      {tab === "theme" && <ThemeTab radar={radar} />}
    </>
  );
}

function ConcentrationTab({ radar }: { radar: RadarJson }) {
  const rows = radar.concentration ?? [];
  if (rows.length === 0) {
    return (
      <div className="notice" style={{ marginTop: 14 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>集中度</span>
        <span>今日無符合條件的集中度資料(需有分點與成交量紀錄)。</span>
      </div>
    );
  }
  return (
    <div className="explore-table">
      <div className="explore-row explore-head">
        <span>股票</span>
        <span>前5大買超佔量</span>
        <span>20日均</span>
        <span>躍升幅度</span>
      </div>
      {rows.map((r) => (
        <a key={r.id} className="explore-row" href={`/stock?id=${r.id}`}>
          <span className="ex-id">
            <b>{r.name}</b>
            <small>{r.id} · {MARKET_LABEL[r.market] ?? r.market}</small>
          </span>
          <span>{(r.buy_concentration * 100).toFixed(1)}%</span>
          <span>{(r.concentration_avg20 * 100).toFixed(1)}%</span>
          <span className="ex-strong">{fmtX(r.vs20)}</span>
        </a>
      ))}
    </div>
  );
}

function ThemeTab({ radar }: { radar: RadarJson }) {
  const themes = useMemo(
    () => [...(radar.themes ?? [])].sort((a, b) => b.turnover - a.turnover),
    [radar.themes],
  );
  if (themes.length === 0) {
    return (
      <div className="notice" style={{ marginTop: 14 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>題材</span>
        <span>今日無符合門檻的題材資料。</span>
      </div>
    );
  }
  return (
    <div className="explore-table">
      <div className="explore-row explore-head theme-head">
        <span>題材</span>
        <span>成交金額</span>
        <span>vs20日均</span>
        <span>今日均漲</span>
        <span>上漲比</span>
      </div>
      {themes.map((t) => {
        const total = t.up + t.down;
        const upRatio = total > 0 ? (t.up / total) * 100 : null;
        return (
          <div key={t.name} className="explore-row theme-head">
            <span className="ex-id"><b>{t.name}</b></span>
            <span>{fmtE8(t.turnover)}</span>
            <span className={t.vs20 != null && t.vs20 >= 1 ? "ex-strong" : ""}>{fmtX(t.vs20)}</span>
            <span className={chgClass(t.avg_chg)}>{fmtPct(t.avg_chg)}</span>
            <span>{upRatio == null ? "—" : `${upRatio.toFixed(0)}%`}</span>
            <div className="theme-top">
              {t.top.slice(0, 5).map((s) => (
                <a key={s.id} href={`/stock?id=${s.id}`} className="theme-top-chip">
                  {s.name}
                  <em className={chgClass(s.chg_pct)}>{fmtPct(s.chg_pct)}</em>
                </a>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
