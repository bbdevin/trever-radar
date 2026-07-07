import Sparkline from "@/components/Sparkline";
import type { RadarStock } from "@/lib/types";
import { MARKET_LABEL, chgClass, fmtE8, fmtLots, fmtPct } from "@/lib/format";

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
        </div>
        <div className="price">
          <div className="close">{s.close.toLocaleString("zh-TW")}</div>
          <span className={`chg-badge ${chgClass(s.chg_pct)}`}>{fmtPct(s.chg_pct)}</span>
        </div>
      </div>
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
        {s.scores ? "分數載入中" : "綜合評分建置中 — 完成後顯示分項分數、觸發理由與風險提醒"}
      </div>
    </a>
  );
}
