import type { SectorFlow } from "@/lib/types";
import { chgClass, fmtE8 } from "@/lib/format";

/** 族群資金流:桌機列表 + 手機橫滑卡(同資料雙排版) */
export default function SectorPanel({ sectors }: { sectors: SectorFlow[] }) {
  if (!sectors?.length) return null;
  const maxShare = Math.max(...sectors.map((s) => s.share));
  return (
    <section className="sector-panel">
      <h2>
        族群資金流 <span className="sub">金額佔比與 20 日均比較;點個股看 K 線</span>
      </h2>

      {/* 桌機列表 */}
      <div className="sector-list">
        {sectors.map((s) => (
          <div className="sector-row" key={s.name}>
            <span className="sname">{s.name}</span>
            <div className="bar-track">
              <div className="bar" style={{ width: `${(s.share / maxShare) * 100}%` }} title={`佔全市場 ${s.share}%`} />
            </div>
            <span className="v amt">{fmtE8(s.turnover)}</span>
            <span className={`v vs20 ${s.vs20 != null && s.vs20 >= 1.5 ? "hotmark" : ""}`}>
              {s.vs20 != null ? `${s.vs20.toFixed(1)}×` : "—"}
            </span>
            <span className={`v ${chgClass(s.avg_chg)}`}>
              {s.avg_chg != null ? `${s.avg_chg > 0 ? "+" : ""}${s.avg_chg.toFixed(2)}%` : "—"}
            </span>
            <span className="v updown">
              <span className="up">{s.up}</span>/<span className="down">{s.down}</span>
            </span>
            <span className="tops">
              {s.top.map((t) => (
                <a key={t.id} href={`/stock?id=${t.id}`} className={chgClass(t.chg_pct)}>
                  {t.name}
                </a>
              ))}
            </span>
          </div>
        ))}
      </div>

      {/* 手機橫滑卡 */}
      <div className="sector-cards">
        {sectors.map((s) => (
          <div className="sector-card" key={s.name}>
            <span className="sname">{s.name}</span>
            <span className="amt num">{fmtE8(s.turnover)}</span>
            <div className="bar-track">
              <div className="bar" style={{ width: `${(s.share / maxShare) * 100}%` }} />
            </div>
            <div className="row">
              <span className={`num ${s.vs20 != null && s.vs20 >= 1.5 ? "vs20 hotmark" : "num"}`}>
                {s.vs20 != null ? `${s.vs20.toFixed(1)}×/20日` : "—"}
              </span>
              <span className={`num ${chgClass(s.avg_chg)}`}>
                {s.avg_chg != null ? `${s.avg_chg > 0 ? "+" : ""}${s.avg_chg.toFixed(1)}%` : "—"}
              </span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
