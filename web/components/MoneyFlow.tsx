"use client";

import { useMemo, useState } from "react";
import type { SectorFlow } from "@/lib/types";
import { chgClass, fmtE8, fmtPct } from "@/lib/format";

type Mode = "industry" | "theme";

/** 相對 20 日常態的偏離 %(+96 = 資金量能 1.96×) */
function dev(g: SectorFlow): number | null {
  return g.vs20 == null ? null : Math.round((g.vs20 - 1) * 100);
}

const CAP = 150; // 條長上限 ±150%

/** 資金流向 v2:以 20 日常態為中軸的流入/流出對向條。
    右紅=資金湧入、左綠=退潮;條長=偏離幅度、列序=強度。 */
export default function MoneyFlow({ sectors, themes }: { sectors: SectorFlow[]; themes?: SectorFlow[] }) {
  const [mode, setMode] = useState<Mode>("industry");
  const [selected, setSelected] = useState<string | null>(null);
  const hasThemes = !!themes?.length;

  const { inflow, outflow, maxAbs } = useMemo(() => {
    const src = (mode === "theme" && hasThemes ? themes! : sectors).filter(
      (g) => g.vs20 != null && g.turnover >= (mode === "theme" ? 1e9 : 2e9),
    );
    const ins = src.filter((g) => (g.vs20 as number) >= 1.15)
      .sort((a, b) => (b.vs20 as number) - (a.vs20 as number)).slice(0, 7);
    const outs = src.filter((g) => (g.vs20 as number) <= 0.85)
      .sort((a, b) => (a.vs20 as number) - (b.vs20 as number)).slice(0, 7);
    const all = [...ins, ...outs].map((g) => Math.min(Math.abs(dev(g) ?? 0), CAP));
    return { inflow: ins, outflow: outs, maxAbs: Math.max(...all, 30) };
  }, [mode, sectors, themes, hasThemes]);

  const sel =
    [...inflow, ...outflow].find((g) => g.name === selected) ??
    (mode === "theme" && hasThemes ? themes! : sectors).find((g) => g.name === selected) ??
    null;

  const Row = ({ g, side }: { g: SectorFlow; side: "in" | "out" }) => {
    const d = Math.min(Math.abs(dev(g) ?? 0), CAP);
    const width = (d / maxAbs) * 100;
    return (
      <button
        className={`fr ${side} ${selected === g.name ? "selected" : ""}`}
        onClick={() => setSelected(selected === g.name ? null : g.name)}
      >
        <span className="fr-name">{g.name}</span>
        <span className="fr-track">
          <span className={`fr-bar ${side}`} style={{ width: `${Math.max(width, 6)}%` }} />
          <span className="fr-x">{g.vs20!.toFixed(1)}×</span>
        </span>
        <span className="fr-meta">
          <b className="num">{fmtE8(g.turnover)}</b>
          <span className={`num ${chgClass(g.avg_chg)}`}>
            {g.avg_chg != null ? `${g.avg_chg > 0 ? "+" : ""}${g.avg_chg.toFixed(1)}%` : "—"}
          </span>
        </span>
      </button>
    );
  };

  return (
    <section className="sector-panel flow2">
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
        <span className="flow-hint">與 20 日常態量能相比:右紅=資金湧入、左綠=退潮;條長=偏離幅度</span>
      </div>

      {inflow.length === 0 && outflow.length === 0 ? (
        <div className="state" style={{ padding: "20px 0" }}>
          今日各{mode === "theme" ? "題材" : "產業"}量能都貼近 20 日常態,無明顯資金移動
        </div>
      ) : (
        <div className="flow-cols">
          <div className="flow-col col-out">
            <div className="flow-col-title out">流出 ↓</div>
            {outflow.length ? outflow.map((g) => <Row key={g.name} g={g} side="out" />)
              : <div className="fr-none">無明顯退潮</div>}
          </div>
          <div className="flow-col">
            <div className="flow-col-title in">流入 ↑</div>
            {inflow.length ? inflow.map((g) => <Row key={g.name} g={g} side="in" />)
              : <div className="fr-none">無明顯湧入</div>}
          </div>
        </div>
      )}

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
