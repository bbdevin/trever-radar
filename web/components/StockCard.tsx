import Sparkline from "@/components/Sparkline";
import WatchlistButton from "@/components/WatchlistButton";
import type { RadarStock } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtLots, fmtPct, fmtX } from "@/lib/format";

export default function StockCard({ s }: { s: RadarStock }) {
  return (
    <a className="card" href={`/stock?id=${s.id}`}>
      <div className="row1">
        <div className="idblock">
          <span className="sname">{s.name}</span>
          <span className="sid">
            {s.id} · {MARKET_LABEL[s.market] ?? s.market}
            {s.industry ? ` · ${s.industry}` : ""}
          </span>
          <div className="themes">
            {s.themes?.slice(0, 3).map((t) => (
              <span key={t} className="theme-badge">{t}</span>
            ))}
          </div>
        </div>
        <div className="price">
          <div className={`close ${chgClass(s.chg_pct)}`}>{s.close.toLocaleString("zh-TW")}</div>
          <span className={`chg-badge ${chgClass(s.chg_pct)}`}>{fmtPct(s.chg_pct)}</span>
        </div>
        <WatchlistButton stockId={s.id} />
      </div>
      {s.description && (
        <div className="desc-block">
          {s.description}
        </div>
      )}

      <div className="sparkrow">
        <Sparkline data={s.spark} id={s.id} />
        <span className="k">近{Math.min(s.spark?.length ?? 0, 30)}日</span>
      </div>
      <div className="stats">
        <div className="item">
          <span className="k">成交金額</span>
          <span className="v">{fmtE8(s.turnover)}</span>
        </div>
        <div className="item">
          <span className="k">量比(20日)</span>
          <span className="v">{s.volume_ratio != null ? `${s.volume_ratio.toFixed(1)}×` : "—"}</span>
        </div>
        <div className="item">
          <span className="k">外資(張)</span>
          <span className="v">{fmtLots(s.foreign_net_lots)}</span>
        </div>
        <div className="item">
          <span className="k">投信(張)</span>
          <span className="v">{fmtLots(s.trust_net_lots)}</span>
        </div>
      </div>
      <div className="score-slot">
        {s.scores ? (
          <div className="score-block">
            <div className="score-line">
              <span className={`score-final ${s.scores.final >= 65 ? "pass" : ""}`}>
                {s.scores.final}
              </span>
              <span className="k" style={{ marginLeft: "4px" }}>綜合評分</span>
            </div>
            {(s.scores.watch_price != null || s.scores.stop_price != null) && (
              <div className="watch-stop-line">
                {s.scores.watch_price != null && (
                  <span className="watch-price">觀察 {s.scores.watch_price.toFixed(2)}</span>
                )}
                {s.scores.stop_price != null && (
                  <span className="stop-price">失效 {s.scores.stop_price.toFixed(2)}</span>
                )}
              </div>
            )}
            {s.reasons.slice(0, 2).map((t) => (
              <div className="reason" key={t}>
                {t}
              </div>
            ))}
            {s.risks.slice(0, 1).map((t) => (
              <div className="risk" key={t}>
                {t}
              </div>
            ))}
          </div>
        ) : s.warrant ? (
          <div className="warrant-mini">
            <span>
              認購 <b>{fmtE8(s.warrant.call_turnover)}</b>
            </span>
            <span>{fmtX(s.warrant.call_turnover_ratio)}</span>
            <span>{s.warrant.call_count} 檔</span>
          </div>
        ) : (
          "未達評分門檻(20日均額 <3,000萬)"
        )}
      </div>
    </a>
  );
}
