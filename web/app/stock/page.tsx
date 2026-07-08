"use client";

import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { IconArrowLeft } from "@/components/Icons";
import KChart from "@/components/KChart";
import type { StockJson } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtLots, fmtPct, fmtX } from "@/lib/format";
import { signInWithGoogle, useSession } from "@/lib/useSession";

const RANGES = [
  { key: "1m", label: "1月", days: 22 },
  { key: "3m", label: "3月", days: 66 },
  { key: "1y", label: "1年", days: 240 },
  { key: "5y", label: "5年", days: 1200 },
  { key: "all", label: "全部", days: Infinity },
] as const;

const BRANCH_RANGES = [
  { label: "1日", days: 1 },
  { label: "3日", days: 3 },
  { label: "5日", days: 5 },
  { label: "10日", days: 10 },
  { label: "20日", days: 20 },
  { label: "60日", days: 60 },
  { label: "120日", days: 120 },
  { label: "240日", days: 240 },
  { label: "2年", days: 480 },
] as const;

function StockView() {
  const id = useSearchParams().get("id");
  const [data, setData] = useState<StockJson | null>(null);
  const [error, setError] = useState(false);
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("1y");
  const [view, setView] = useState<"chart" | "branch" | "warrant">("chart");

  useEffect(() => {
    if (!id) return;
    fetch(`/data/stocks/${id}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch(() => setError(true));
  }, [id]);

  const visibleDays = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? Infinity;
    return days === Infinity ? Number.MAX_SAFE_INTEGER : days;
  }, [range]);

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
      <div className="stock-toolbar">
        <div className="stock-tabs" role="tablist">
          <button
            role="tab"
            aria-selected={view === "chart"}
            className={view === "chart" ? "active" : ""}
            onClick={() => setView("chart")}
          >
            K線
          </button>
          <button
            role="tab"
            aria-selected={view === "branch"}
            className={view === "branch" ? "active" : ""}
            onClick={() => setView("branch")}
          >
            分點
          </button>
          <button
            role="tab"
            aria-selected={view === "warrant"}
            className={view === "warrant" ? "active" : ""}
            onClick={() => setView("warrant")}
          >
            權證
          </button>
        </div>
        {view === "chart" && (
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
        )}
      </div>
      {view === "chart" && <KChart candles={cs} visibleDays={visibleDays} />}
      {view === "branch" && <BranchPanel data={data} />}
      {view === "warrant" && <WarrantPanel data={data} />}
      {view === "chart" && <TechnicalPanel data={data} />}
    </>
  );
}

function BranchPanel({ data }: { data: StockJson }) {
  const [days, setDays] = useState<number | "custom">(1);
  const [customDays, setCustomDays] = useState<string>("5");
  const [expandedBranch, setExpandedBranch] = useState<string | null>(null);

  const activeDays = days === "custom" ? parseInt(customDays) || 1 : days;

  const agg = useMemo(() => {
    if (!data.branch_history?.length) {
      const buyers = data.branches.filter((b) => b.net > 0).sort((a,b) => b.net - a.net);
      const sellers = data.branches.filter((b) => b.net < 0).sort((a,b) => a.net - b.net);
      return { 
        buyers, sellers, 
        top13Buy: buyers.slice(0, 13).map(b => ({name: b.name, buy: b.buy, sell: b.sell, net: b.net, history: []})),
        top13Sell: sellers.slice(0, 13).map(b => ({name: b.name, buy: b.buy, sell: b.sell, net: b.net, history: []}))
      };
    }
    
    const sliced = data.branch_history.slice(0, activeDays);
    const map: Record<string, { buy: number, sell: number, net: number }> = {};
    const allDates = sliced.map(s => s.t).reverse();

    for (const day of sliced) {
      for (const b of day.branches) {
        if (!map[b.n]) map[b.n] = { buy: 0, sell: 0, net: 0 };
        map[b.n].buy += b.b;
        map[b.n].sell += b.s;
        map[b.n].net += b.net;
      }
    }

    const arr = Object.keys(map).map(name => ({ name, ...map[name] }));
    const buyers = arr.filter(x => x.net > 0).sort((a, b) => b.net - a.net);
    const sellers = arr.filter(x => x.net < 0).sort((a, b) => a.net - b.net);
    
    const top13Buy = buyers.slice(0, 13).map(b => {
      const history = allDates.map(dt => {
        const dObj = sliced.find(s => s.t === dt);
        const bObj = dObj?.branches.find(x => x.n === b.name);
        return { t: dt, net: bObj ? bObj.net : 0 };
      });
      return { ...b, history };
    });

    const top13Sell = sellers.slice(0, 13).map(b => {
      const history = allDates.map(dt => {
        const dObj = sliced.find(s => s.t === dt);
        const bObj = dObj?.branches.find(x => x.n === b.name);
        return { t: dt, net: bObj ? bObj.net : 0 };
      });
      return { ...b, history };
    });

    return { buyers, sellers, top13Buy, top13Sell };
  }, [data.branch_history, data.branches, activeDays]);

  const score = data.scores?.branch ?? null;
  const branchReasons = (data.reasons ?? []).filter((t) => t.includes("分點"));

  if (!data.branches.length && !data.branch_history?.length && score == null) {
    return (
      <div className="state">
        尚無此股分點資料。免費資料目前只抓評分池前80檔的前15大買賣超,會隨每日累積增加。
      </div>
    );
  }

  const netTotal = agg.buyers.reduce((sum, b) => sum + b.net, 0) + agg.sellers.reduce((sum, b) => sum + b.net, 0);

  return (
    <div className="branch-panel">
      <div className="branch-summary">
        <div className="branch-score">
          <span className="k">分點分</span>
          <span className="v">{score ?? "—"}</span>
        </div>
        <div className="branch-stat">
          <span className="k">{activeDays}日買超分點</span>
          <span className="v">{agg.buyers.length}</span>
        </div>
        <div className="branch-stat">
          <span className="k">{activeDays}日賣超分點</span>
          <span className="v">{agg.sellers.length}</span>
        </div>
        <div className="branch-stat">
          <span className="k">{activeDays}日淨流</span>
          <span className={`v ${netTotal > 0 ? "up" : netTotal < 0 ? "down" : ""}`}>{fmtLots(netTotal)}張</span>
        </div>
      </div>

      <div className="branch-reasons">
        {branchReasons.length > 0 ? (
          branchReasons.map((t) => <span key={t}>{t}</span>)
        ) : (
          <span>今日未觸發分點加分條件</span>
        )}
      </div>

      <div className="branch-toolbar">
        <div className="range-bar" role="tablist">
          {BRANCH_RANGES.map(r => (
            <button
              key={r.days}
              role="tab"
              aria-selected={days === r.days}
              className={days === r.days ? "active" : ""}
              onClick={() => setDays(r.days)}
            >
              {r.label}
            </button>
          ))}
          <div className={`custom-range ${days === "custom" ? "active" : ""}`}>
            <button
              role="tab"
              aria-selected={days === "custom"}
              onClick={() => setDays("custom")}
            >
              自訂
            </button>
            {days === "custom" && (
              <input 
                type="number" 
                min={1} 
                max={240} 
                value={customDays} 
                onChange={e => setCustomDays(e.target.value)} 
                className="custom-input"
                placeholder="天數"
              />
            )}
          </div>
        </div>
      </div>

      <div className="bento-grid">
        <div className="bento-card buy-card">
          <h3 className="bento-title up">前 13 大買超分點</h3>
          <div className="bento-list">
            {agg.top13Buy.map(b => (
              <BranchRow 
                key={b.name} 
                b={b} 
                expanded={expandedBranch === b.name} 
                onToggle={() => setExpandedBranch(expandedBranch === b.name ? null : b.name)} 
              />
            ))}
            {agg.top13Buy.length === 0 && <div className="state">無買超紀錄</div>}
          </div>
        </div>
        <div className="bento-card sell-card">
          <h3 className="bento-title down">前 13 大賣超分點</h3>
          <div className="bento-list">
            {agg.top13Sell.map(b => (
              <BranchRow 
                key={b.name} 
                b={b} 
                expanded={expandedBranch === b.name} 
                onToggle={() => setExpandedBranch(expandedBranch === b.name ? null : b.name)} 
              />
            ))}
            {agg.top13Sell.length === 0 && <div className="state">無賣超紀錄</div>}
          </div>
        </div>
      </div>
      
      <div className="branch-note">
        分點資料來自免費公開頁的前15大買賣超裁剪版,不是全市場全量分點;T+1 盤後資料,僅供籌碼觀察。
      </div>
    </div>
  );
}

function BranchRow({ b, expanded, onToggle }: { b: any, expanded: boolean, onToggle: () => void }) {
  const maxNet = b.history?.length ? Math.max(...b.history.map((h: any) => Math.abs(h.net))) || 1 : 1;
  return (
    <div className={`bento-item ${expanded ? 'expanded' : ''}`}>
      <div className="bento-item-header cursor-pointer" onClick={onToggle}>
        <span className="n">{b.name}</span>
        <span className={`net ${b.net > 0 ? "up" : b.net < 0 ? "down" : "flat"}`}>
          {fmtLots(b.net)}張
        </span>
      </div>
      {expanded && b.history && (
        <div className="bento-item-chart">
          {b.history.map((h: any) => (
            <div className="b-bar-wrapper" key={h.t} title={`${h.t} 淨${h.net > 0 ? '買' : '賣'}: ${Math.abs(h.net)}張`}>
              <div className="b-bar-container up">
                {h.net > 0 && <div className="b-bar up" style={{ height: `${(h.net / maxNet) * 100}%` }} />}
              </div>
              <div className="b-bar-container down">
                {h.net < 0 && <div className="b-bar down" style={{ height: `${(Math.abs(h.net) / maxNet) * 100}%` }} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TechnicalPanel({ data }: { data: StockJson }) {
  const t = data.technical;
  if (!t) {
    return (
      <div className="notice" style={{ marginTop: 14 }}>
        <span className="tag" style={{ color: "var(--ink-3)" }}>技術</span>
        <span>尚未產出技術指標;請先跑 compute-indicators。</span>
      </div>
    );
  }

  return (
    <div className="tech-panel">
      <div className="tech-score">
        <span className="k">技術分</span>
        <span className="v">{t.score}</span>
      </div>
      <div className="tech-stats">
        <span>MA20 <b>{t.ma20 == null ? "—" : t.ma20.toFixed(2)}</b></span>
        <span>MA60 <b>{t.ma60 == null ? "—" : t.ma60.toFixed(2)}</b></span>
        <span>RSI14 <b>{t.rsi14 == null ? "—" : t.rsi14.toFixed(1)}</b></span>
        <span>量比 <b>{fmtX(t.volume_ratio)}</b></span>
      </div>
      <div className="tech-reasons">
        {t.reasons.length > 0 ? t.reasons.map((r) => (
          <span key={r.code}>{r.text}</span>
        )) : <span>未觸發技術加分條件</span>}
      </div>
    </div>
  );
}

function WarrantPanel({ data }: { data: StockJson }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const { session } = useSession();
  const maxTurnover = Math.max(
    1,
    ...data.warrant_history.map((p) => Math.max(p.call_turnover, p.put_turnover)),
  );

  if (!data.warrant) {
    return <div className="state">目前沒有可彙總的權證成交資料</div>;
  }

  return (
    <div className="warrant-panel">
      <div className="warrant-summary">
        <div className="warrant-stat">
          <span className="k">認購成交</span>
          <span className="v">{fmtE8(data.warrant.call_turnover)}</span>
        </div>
        <div className="warrant-stat">
          <span className="k">20日倍數</span>
          <span className="v">{fmtX(data.warrant.call_turnover_ratio)}</span>
        </div>
        <div className="warrant-stat">
          <span className="k">認售成交</span>
          <span className="v">{fmtE8(data.warrant.put_turnover)}</span>
        </div>
        <div className="warrant-stat">
          <span className="k">有成交檔數</span>
          <span className="v">
            {data.warrant.call_count} / {data.warrant.put_count}
          </span>
        </div>
      </div>

      <div className="warrant-bars" aria-label="權證60日成交金額">
        {data.warrant_history.map((p) => (
          <div className="warrant-day" key={p.t} title={`${p.t} 認購 ${fmtE8(p.call_turnover)} / 認售 ${fmtE8(p.put_turnover)}`}>
            <span className="call" style={{ height: `${Math.max(2, (p.call_turnover / maxTurnover) * 100)}%` }} />
            <span className="put" style={{ height: `${Math.max(2, (p.put_turnover / maxTurnover) * 100)}%` }} />
          </div>
        ))}
      </div>

      {data.active_warrants.length > 0 ? (
        <table className="warrant-table">
          <thead>
            <tr>
              <th>代號</th>
              <th>名稱</th>
              <th>類型</th>
              <th>履約價</th>
              <th>到期日</th>
              <th>成交</th>
            </tr>
          </thead>
          <tbody>
            {data.active_warrants.map((w) => (
              <Fragment key={w.id}>
                <tr
                  className="warrant-row-toggle"
                  onClick={() => setExpanded(expanded === w.id ? null : w.id)}
                  title={w.branches?.length ? "點擊展開分點進出" : "此權證無分點資料(上櫃權證無來源)"}
                >
                  <td className="num">{w.id}</td>
                  <td>
                    {w.name}
                    {!!w.branches?.length && <span className="chip" style={{ marginLeft: 6 }}>分點</span>}
                  </td>
                  <td>
                    <span className={`warrant-kind ${w.kind}`}>{w.kind === "call" ? "認購" : "認售"}</span>
                  </td>
                  <td className="num">{w.strike == null ? "—" : w.strike.toLocaleString("zh-TW")}</td>
                  <td className="num">{w.maturity_date ?? "—"}</td>
                  <td className="num">{fmtE8(w.turnover)}</td>
                </tr>
                {expanded === w.id && (
                  <tr className="warrant-branches">
                    <td colSpan={6}>
                      {!session ? (
                        <button className="login-inline" onClick={signInWithGoogle}>
                          以 Google 登入後查看分點進出明細
                        </button>
                      ) : w.branches?.length ? (
                        <div className="wb-grid">
                          {w.branches.map((b) => (
                            <span className="wb-item" key={b.name}>
                              <span className="n">{b.name}</span>
                              <span className={`net ${b.net > 0 ? "up" : b.net < 0 ? "down" : "flat"}`}>
                                {b.net > 0 ? "+" : ""}{b.net.toLocaleString("zh-TW")}張
                              </span>
                            </span>
                          ))}
                          <span className="wb-empty">※ 權證分點多為發行商造市部位,重點看非發行商大額買超</span>
                        </div>
                      ) : (
                        <span className="wb-empty">此權證無分點資料(僅上市權證有免費來源,且僅榜單熱門權證每晚抓取)</span>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="state">今日沒有權證成交明細</div>
      )}
    </div>
  );
}

export default function StockPage() {
  return (
    <Suspense fallback={<div className="state">載入中…</div>}>
      <StockView />
    </Suspense>
  );
}
