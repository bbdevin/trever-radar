import type { RadarStock } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtLots, fmtPct } from "@/lib/format";

export default function StockCard({ s }: { s: RadarStock }) {
  return (
    <div className="card">
      <div className="row1">
        <span className="sid">{s.id}</span>
        <span className="sname">{s.name}</span>
        <span className="chip">{MARKET_LABEL[s.market] ?? s.market}</span>
        <div className="price">
          <div className="close">{s.close.toLocaleString("zh-TW")}</div>
          <div className={`chg ${chgClass(s.chg_pct)}`}>{fmtPct(s.chg_pct)}</div>
        </div>
      </div>
      <div className="stats">
        <div className="item">
          <span className="k">成交金額</span>
          <span className="v">{fmtE8(s.turnover)}</span>
        </div>
        <div className="item">
          <span className="k">外資(張)</span>
          <span className="v">{fmtLots(s.foreign_net_lots)}</span>
        </div>
        <div className="item">
          <span className="k">投信(張)</span>
          <span className="v">{fmtLots(s.trust_net_lots)}</span>
        </div>
        <div className="item">
          <span className="k">融資增減(張)</span>
          <span className="v">{fmtLots(s.margin_chg_lots)}</span>
        </div>
      </div>
      <div className="score-slot">
        {s.scores
          ? "分數載入中"
          : "綜合評分建置中 — 完成後此處顯示:權證/技術/法人/題材分項與觸發理由"}
      </div>
    </div>
  );
}
