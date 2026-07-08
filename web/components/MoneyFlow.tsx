"use client";

import { useMemo, useState } from "react";
import type { SectorFlow } from "@/lib/types";
import { chgClass, fmtE8, fmtPct } from "@/lib/format";
import { squarify } from "@/lib/treemap";

type Mode = "industry" | "theme";
const W = 100; // 虛擬座標,以百分比鋪排
const H = 46;

function tileFill(chg: number | null): string {
  if (chg == null) return "var(--surface-2)";
  const a = Math.min(0.16 + (Math.abs(chg) / 3) * 0.42, 0.6);
  return chg > 0 ? `rgba(230,103,103,${a})` : chg < 0 ? `rgba(12,163,12,${a})` : "var(--surface-2)";
}

function flowBadge(vs20: number | null) {
  if (vs20 == null) return null;
  if (vs20 >= 1.2) return <span className="flow-badge in">▲{vs20.toFixed(1)}×</span>;
  if (vs20 <= 0.8) return <span className="flow-badge out">▼{vs20.toFixed(1)}×</span>;
  return <span className="flow-badge">{vs20.toFixed(1)}×</span>;
}

/** 資金流 Treemap:格子大小=成交金額、顏色=平均漲跌、▲▼=相對20日均量能 */
export default function MoneyFlow({ sectors, themes }: { sectors: SectorFlow[]; themes?: SectorFlow[] }) {
  const [mode, setMode] = useState<Mode>("industry");
  const [selected, setSelected] = useState<string | null>(null);
  const hasThemes = !!themes?.length;

  const groups = useMemo(() => {
    const src = mode === "theme" && hasThemes ? themes! : sectors;
    return src.slice(0, mode === "theme" ? 20 : 14);
  }, [mode, sectors, themes, hasThemes]);

  const rects = useMemo(() => squarify(groups.map((g) => Math.max(g.turnover, 1)), W, H), [groups]);

  const leaders = useMemo(() => {
    const src = (mode === "theme" && hasThemes ? themes! : sectors).filter(
      (g) => g.vs20 != null && g.turnover >= (mode === "theme" ? 1e9 : 3e9),
    );
    const inflow = [...src].sort((a, b) => (b.vs20 ?? 0) - (a.vs20 ?? 0)).slice(0, 3)
      .filter((g) => (g.vs20 ?? 0) >= 1.15);
    const outflow = [...src].sort((a, b) => (a.vs20 ?? 0) - (b.vs20 ?? 0)).slice(0, 3)
      .filter((g) => (g.vs20 ?? 0) <= 0.85);
    return { inflow, outflow };
  }, [mode, sectors, themes, hasThemes]);

  const sel = groups.find((g) => g.name === selected) ?? null;

  return (
    <section className="sector-panel">
      <div className="flow-head">
        <h2>資金流向</h2>
        <div className="seg small">
          <button className={mode === "industry" ? "tab active" : "tab"} onClick={() => { setMode("industry"); setSelected(null); }}>
            產業
          </button>
          <button
            className={mode === "theme" ? "tab active" : "tab"}
            onClick={() => { setMode("theme"); setSelected(null); }}
            disabled={!hasThemes}
            title={hasThemes ? "概念股分類(成分重疊)" : "題材資料累積中"}
          >
            題材
          </button>
        </div>
        <span className="flow-hint">大小=成交金額 · 顏色=漲跌 · ▲▼=相對20日均量能</span>
      </div>

      {(leaders.inflow.length > 0 || leaders.outflow.length > 0) && (
        <div className="flow-leaders">
          {leaders.inflow.length > 0 && (
            <span>
              <em className="in">資金湧入</em>
              {leaders.inflow.map((g) => (
                <button key={g.name} className="leader" onClick={() => setSelected(g.name)}>
                  {g.name} {g.vs20!.toFixed(1)}×
                </button>
              ))}
            </span>
          )}
          {leaders.outflow.length > 0 && (
            <span>
              <em className="out">退潮</em>
              {leaders.outflow.map((g) => (
                <button key={g.name} className="leader" onClick={() => setSelected(g.name)}>
                  {g.name} {g.vs20!.toFixed(1)}×
                </button>
              ))}
            </span>
          )}
        </div>
      )}

      <div className="treemap" role="list">
        {groups.map((g, i) => {
          const r = rects[i];
          if (!r || r.w <= 0.2 || r.h <= 0.2) return null;
          const big = r.w * r.h > 40;
          return (
            <button
              key={g.name}
              role="listitem"
              className={`tile ${selected === g.name ? "selected" : ""}`}
              style={{
                left: `${r.x}%`,
                top: `${(r.y / H) * 100}%`,
                width: `${r.w}%`,
                height: `${(r.h / H) * 100}%`,
                background: tileFill(g.avg_chg),
              }}
              onClick={() => setSelected(selected === g.name ? null : g.name)}
              title={`${g.name} ${fmtE8(g.turnover)}｜均${g.avg_chg ?? "—"}%｜量能${g.vs20 ?? "—"}×`}
            >
              <span className="t-name">{g.name}</span>
              {big && <span className="t-amt">{fmtE8(g.turnover)}</span>}
              {big && (
                <span className={`t-chg ${chgClass(g.avg_chg)}`}>
                  {g.avg_chg != null ? `${g.avg_chg > 0 ? "+" : ""}${g.avg_chg.toFixed(1)}%` : "—"}
                </span>
              )}
              {flowBadge(g.vs20)}
            </button>
          );
        })}
      </div>

      {sel && (
        <div className="drill">
          <div className="drill-head">
            <b>{sel.name}</b>
            <span className="k">
              {fmtE8(sel.turnover)} · 量能{sel.vs20 != null ? `${sel.vs20.toFixed(1)}×` : "—"} ·{" "}
              <span className="up">↑{sel.up}</span>/<span className="down">↓{sel.down}</span>
            </span>
          </div>
          <div className="drill-stocks">
            {sel.top.map((t) => (
              <a key={t.id} href={`/stock?id=${t.id}`} className="drill-stock">
                <span className="n">{t.name}</span>
                <span className={`c ${chgClass(t.chg_pct)}`}>{fmtPct(t.chg_pct)}</span>
                {t.turnover != null && <span className="a">{fmtE8(t.turnover)}</span>}
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
