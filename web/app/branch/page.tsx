"use client";

import { useEffect, useState, useMemo } from "react";
import { IconFlame, IconTrend, IconZap } from "@/components/Icons";
import { fmtE8 } from "@/lib/format";

type Ranking = {
  branch_name: string;
  as_of: string;
  rank_score: number;
  win_rate: number | null;
  avg_ret5: number | null;
  samples: number;
  style: string;
  is_daytrade: number;
};

type Movement = {
  branch_name: string;
  stock_id: string;
  stock_name: string;
  buy_lots: number;
  sell_lots: number;
  net_lots: number;
  pct: number;
};

type TodayMovements = Record<string, Movement[]>;

type WarrantMover = {
  branch_name: string;
  warrant_id: string;
  warrant_name: string;
  kind: "call" | "put";
  underlying_id: string | null;
  underlying_name: string | null;
  net_lots: number;
  buy_lots: number;
  active_days: number;
  last_date: string;
};

const TABS = [
  { key: "rankings", label: "排行榜", hint: "分點操作勝率與可信度排行", icon: IconFlame },
  { key: "today", label: "今日動向", hint: "追蹤分點於最近交易日的買超明細", icon: IconZap },
  { key: "warrant", label: "權證分點", hint: "近40個交易日對單一權證淨買 ≥300 張的分點(多為發行商造市,重點看非發行商)", icon: IconTrend },
];

function Skeleton() {
  return (
    <>
      <div className="strip">
        {[0, 1].map((i) => (
          <div className="sk sk-strip" key={i} />
        ))}
      </div>
      <div className="grid">
        {[0, 1, 2, 3].map((i) => (
          <div className="sk sk-card" key={i} />
        ))}
      </div>
    </>
  );
}

export default function BranchPage() {
  const [tab, setTab] = useState<"rankings" | "today" | "warrant">("rankings");
  const [rankings, setRankings] = useState<Ranking[] | null>(null);
  const [today, setToday] = useState<TodayMovements | null>(null);
  const [movers, setMovers] = useState<WarrantMover[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch("/data/branches/rankings.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setRankings)
      .catch(() => setError(true));

    fetch("/data/branches/today.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setToday)
      .catch(() => setError(true));

    fetch("/data/branches/warrant_movers.json")
      .then((r) => (r.ok ? r.json() : []))
      .then(setMovers)
      .catch(() => {});
  }, []);

  if (error) {
    return (
      <div className="state">
        找不到分點資料。請先執行 <code>python -m radar compute-branch-stats</code> 與 <code>export-json</code>
      </div>
    );
  }
  if (!rankings || !today) return <Skeleton />;

  const hasDataWarning = rankings.some((r) => r.win_rate === null);

  return (
    <>
      <div className="strip">
        <div className="item">
          <span className="k">資料狀態</span>
          <span className="v">
            追蹤 {rankings.length} 個分點
          </span>
        </div>
      </div>

      {hasDataWarning && (
        <div className="notice warn">
          <span className="tag warn">樣本不足</span>
          <span>
            由於系統自 2026-07-07 才開始收集免費分點資料，部分分點的歷史交易筆數過少，導致無法計算勝率。需待資料持續累積數週。
          </span>
        </div>
      )}

      <div className="tabbar">
        <div className="seg" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              className={tab === t.key ? "tab active" : "tab"}
              onClick={() => setTab(t.key as any)}
              title={t.hint}
            >
              <t.icon size={15} />
              {t.label}
            </button>
          ))}
        </div>
        <span className="tabhint">{TABS.find((t) => t.key === tab)?.hint}</span>
      </div>

      {tab === "rankings" && (
        <div className="grid">
          {rankings.map((r) => (
            <div key={r.branch_name} className="card" style={{ display: "block" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <h3 style={{ fontSize: 18, color: "var(--ink)", margin: 0 }}>{r.branch_name}</h3>
                {r.is_daytrade === 1 && (
                  <span className="tag warn" style={{ background: "rgba(250, 178, 25, 0.1)", color: "var(--warn)" }}>
                    疑似隔日沖
                  </span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <div style={{ color: "var(--ink-3)", fontSize: 12 }}>勝率 (5日)</div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: r.win_rate ? (r.win_rate > 50 ? "var(--up)" : "var(--down)") : "var(--ink-2)" }}>
                    {r.win_rate ? `${r.win_rate.toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div>
                  <div style={{ color: "var(--ink-3)", fontSize: 12 }}>平均報酬 (5日)</div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: r.avg_ret5 ? (r.avg_ret5 > 0 ? "var(--up)" : "var(--down)") : "var(--ink-2)" }}>
                    {r.avg_ret5 ? `${r.avg_ret5.toFixed(1)}%` : "-"}
                  </div>
                </div>
                <div>
                  <div style={{ color: "var(--ink-3)", fontSize: 12 }}>交易筆數</div>
                  <div className="num">{r.samples}</div>
                </div>
                <div>
                  <div style={{ color: "var(--ink-3)", fontSize: 12 }}>可信度分數</div>
                  <div className="num" style={{ color: "var(--accent-2)" }}>{r.rank_score}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "warrant" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {movers.length === 0 && (
            <div className="state">
              近期無權證分點大額淨買紀錄(資料自每日成交前15大上市權證累積;上櫃權證無免費來源)
            </div>
          )}
          {movers.map((m) => (
            <div key={`${m.branch_name}-${m.warrant_id}`} className="card" style={{ display: "grid", gridTemplateColumns: "1.2fr 1.6fr 1fr 1fr", gap: 10, alignItems: "center", padding: "10px 14px" }}>
              <div style={{ fontWeight: 650 }}>{m.branch_name}</div>
              <div>
                <a href={m.underlying_id ? `/stock?id=${m.underlying_id}` : "#"} style={{ color: "var(--ink)" }}>
                  {m.underlying_name ?? "—"}
                </a>{" "}
                <span style={{ color: "var(--ink-3)", fontSize: 12 }} className="sid">
                  {m.warrant_name}({m.warrant_id})
                </span>{" "}
                <span className={`warrant-kind ${m.kind}`}>{m.kind === "call" ? "認購" : "認售"}</span>
              </div>
              <div className="num" style={{ textAlign: "right", color: "var(--up)", fontWeight: 700 }}>
                淨買 {m.net_lots.toLocaleString("zh-TW")} 張
              </div>
              <div style={{ textAlign: "right", color: "var(--ink-3)", fontSize: 12 }}>
                {m.active_days} 個交易日 · 最近 {m.last_date}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "today" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {Object.entries(today).length === 0 && (
            <div className="state">今日無追蹤分點的買超紀錄</div>
          )}
          {Object.entries(today).map(([branchName, trades]) => (
            <div key={branchName} className="card" style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, borderBottom: "1px solid var(--border)", paddingBottom: 12 }}>
                <span style={{ fontSize: 18, fontWeight: 600, color: "var(--ink)" }}>{branchName}</span>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {trades.map((t) => (
                  <a href={`/stock?id=${t.stock_id}`} key={t.stock_id} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 8, alignItems: "center", padding: "6px 8px", background: "var(--surface-2)", borderRadius: 6, textDecoration: "none" }}>
                    <div>
                      <span style={{ color: "var(--ink)" }}>{t.stock_name}</span>{" "}
                      <span style={{ color: "var(--ink-3)", fontSize: 12 }} className="sid">{t.stock_id}</span>
                    </div>
                    <div style={{ textAlign: "right", color: "var(--up)" }}>
                      買 {t.buy_lots}
                    </div>
                    <div style={{ textAlign: "right", color: t.net_lots > 0 ? "var(--up)" : "var(--down)" }}>
                      淨 {t.net_lots}
                    </div>
                    <div style={{ textAlign: "right", color: "var(--ink-2)", fontSize: 12 }}>
                      佔比 {t.pct}%
                    </div>
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
