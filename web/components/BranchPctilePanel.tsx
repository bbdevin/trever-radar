"use client";

import type { BranchPctileCounts, BranchPctileRow } from "@/lib/types";

/**
 * 個股頁：分點在這檔股票的買點／賣點價格分位計數。
 *
 * 為什麼這裡沒有徽章、沒有名次、沒有分數。2026-09-03 的唯讀量測有兩半：傾向為真
 * (樣本外仍以 2.3–2.9× 勝過該股自身基準,規模配對安慰劑貼著機率),但**標籤不可
 * 重現**(同一對隔一個年度再次合格只有 1.6–5.4%)。所以這一節只呈現「數到幾次／
 * 共幾次」與該股自身的同側比率,由讀的人自己判斷,不替他下結論,也不暗示會延續。
 *
 * 為什麼每一列都要把該股自身的比率畫在同一條軸上。兩側基準率差很多(全市場低買
 * 53.4%、高賣 35.4%):一個 60% 的低買率幾乎就是基準值,一個 60% 的高賣率卻是大幅
 * 超出。只給兩個百分比要讀的人自己心算差額,等於把這把尺丟掉。
 */

const CONTRACT_VERSION = 1;

/** 次日回吐一列的定義,寫在 title 裡,與另外兩側同一種講法。 */
const DAYTRADE_LABEL = "次日回吐";
const DAYTRADE_DEFINITION =
  "合格買超日的次日，同一分點又出現在這檔股票的前 15 大賣超，"
  + "且賣出張數達當日淨買的七成以上";

type SideSpec = {
  key: "buy" | "sell";
  label: string;
  /** 這一側「數到的那件事」的定義,講清楚才不會被讀成損益。 */
  definition: string;
  hit: (row: BranchPctileRow) => number;
  known: (row: BranchPctileRow) => number;
  unknown: (row: BranchPctileRow) => number;
  stockHit: (payload: BranchPctileCounts) => number | null;
  stockKnown: (payload: BranchPctileCounts) => number | null;
};

const SIDES: SideSpec[] = [
  {
    key: "buy",
    label: "買點偏低",
    definition: "買進當日收盤落在近 20 日區間的低四成",
    hit: (row) => row.low_buy_count,
    known: (row) => row.buy_pctile_known,
    unknown: (row) => row.buy_pctile_unknown,
    stockHit: (payload) => payload.stock_low_buy_count,
    stockKnown: (payload) => payload.stock_buy_pctile_known,
  },
  {
    key: "sell",
    label: "賣點偏高",
    definition: "賣出當日收盤落在近 20 日區間的高四成",
    hit: (row) => row.high_sell_count,
    known: (row) => row.sell_pctile_known,
    unknown: (row) => row.sell_pctile_unknown,
    stockHit: (payload) => payload.stock_high_sell_count,
    stockKnown: (payload) => payload.stock_sell_pctile_known,
  },
];

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isRow(value: unknown): value is BranchPctileRow {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.branch_name === "string"
    && row.branch_name.length > 0
    && isCount(row.buy_pctile_known)
    && isCount(row.buy_pctile_unknown)
    && isCount(row.low_buy_count)
    && isCount(row.sell_pctile_known)
    && isCount(row.sell_pctile_unknown)
    && isCount(row.high_sell_count)
  );
}

/** 比率以外都不算數:分母 0 時回 null,絕不用 0/0 充當 0%。 */
function rate(hit: number | null, known: number | null): number | null {
  if (!isCount(hit) || !isCount(known) || known <= 0 || hit > known) return null;
  return (hit / known) * 100;
}

function fmtPct(value: number): string {
  return `${value.toFixed(1)}%`;
}

function fmtPp(value: number): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}pp`;
}

/**
 * 個股頁「買點／賣點分位計數」。舊版 payload(缺鍵或版本不符)整節不渲染,
 * 因為程式碼會早於下一次 VPS 匯出上線,線上一定會出現新程式碼配舊 JSON。
 */
export default function BranchPctilePanel({ data }: { data: BranchPctileCounts | undefined }) {
  if (!data || typeof data !== "object" || data.version !== CONTRACT_VERSION) return null;
  if (!Array.isArray(data.branches)) return null;

  const rows = data.branches.filter(isRow);
  const minPerSide = isCount(data.min_known_episodes_per_side) ? data.min_known_episodes_per_side : null;
  const windowFrom = typeof data.window_from === "string" ? data.window_from : null;
  const asOf = typeof data.as_of === "string" ? data.as_of : null;
  const marketDays = isCount(data.window_market_days) ? data.window_market_days : null;

  // 窗口一定要說出來,舊版 payload 缺欄位時也講清楚缺的是什麼,不留白。
  const windowLabel = windowFrom && asOf
    ? `${windowFrom} ～ ${asOf}${marketDays ? `，共 ${marketDays} 個交易日` : ""}`
    : "區間未提供（舊版資料）";

  return (
    <section
      aria-labelledby="branch-pctile-heading"
      className="mt-3.5 grid min-w-0 max-w-full gap-3 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]"
    >
      <div className="flex flex-col gap-1">
        <h2 id="branch-pctile-heading" className="text-[15px] font-bold text-foreground">
          歷史上在這檔股票買點偏低、賣點偏高的分點
        </h2>
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          統計窗口 {windowLabel}。這是窗口內累積下來的紀錄，不是今日盤後名單；
          分點列在這裡是因為它在窗口內的進出，與它今天有沒有交易、有沒有進今天的前 15 大無關。
        </p>
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          資料只記錄當日進入這檔股票前 15 大買超或賣超的分點。多數股票淨買賣個幾張就進得了
          前 15，成交熱絡的個股則要數十張以上，所以下列次數是該分點活動量的下限，
          不是完整紀錄。
        </p>
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">
          每一列都附上這檔股票自身的同一項比率當作尺——各項的基準本來就不同，
          只看單一個百分比會誤讀。以下全部是進出場時點的計次（價格分位與次日回吐），
          不是損益，也不代表之後會延續。
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-4 text-[13px] leading-relaxed text-muted-foreground">
          統計窗口 {windowLabel}。窗口內這檔股票沒有任何分點在買、賣兩側各累積到
          {minPerSide != null ? ` 至少 ${minPerSide} 次` : "足夠次數"}分位可知的紀錄，
          所以沒有可以放上這把尺比較的對象。這是窗口內觀察到的次數不足，不是資料載入失敗。
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => (
            <li
              key={row.branch_name}
              className="grid gap-2 rounded-[var(--r-md)] border border-border bg-background p-3"
            >
              <h3 className="truncate text-[13.5px] font-semibold text-foreground" title={row.branch_name}>
                {row.branch_name}
              </h3>
              <div className="grid gap-2.5 md:grid-cols-2 md:gap-3">
                {SIDES.map((side) => (
                  <SideBar key={side.key} side={side} row={row} payload={data} />
                ))}
              </div>
              <DaytradeBar row={row} payload={data} />
            </li>
          ))}
        </ul>
      )}

      <p className="text-[11px] leading-relaxed text-muted-foreground">
        「低四成／高四成」指當日收盤在該股近 20 日收盤區間中的位置。買、賣兩側各自獨立計數，
        沒有配對成一筆交易，因此不能讀成賺賠。「次日回吐」數的是{DAYTRADE_DEFINITION}的次數；
        出場多半落在看不見的成交裡，所以那個次數同樣是下限，不是完整紀錄，也不能當成對某個分點的判定。
      </p>
    </section>
  );
}

/**
 * 第三列:次日回吐。與上面兩側同一個窗口、同一種視覺語言。
 *
 * 這裡刻意有三種狀態,不是兩種:
 *   1. 缺鍵(舊版 payload)——整列不畫。沒有這項觀察,和觀察到 0 次不是同一件事。
 *   2. 觀察數 < min_daytrade_obs ——明講「無法判定」。這正是這次改版的重點:
 *      未判定不等於「不會回吐」,絕不能退化成 0 或空白。
 *   3. 觀察數足夠 —— 分子/分母 + 百分比 + 該股自身的尺。
 *
 * 門檻不寫死在前端,只讀 payload 帶來的 min_daytrade_obs:定義留在 pipeline 一處。
 * 方向色同樣不用——這是計次,不是判定,更不是「這是隔日沖分點」這種斷言。
 */
function DaytradeBar({
  row,
  payload,
}: {
  row: BranchPctileRow;
  payload: BranchPctileCounts;
}) {
  const obs = row.daytrade_obs;
  const paybacks = row.daytrade_paybacks;
  const minObs = payload.min_daytrade_obs;
  // 舊 JSON 配新程式碼是常態(程式碼會早於下一次 VPS 匯出上線),缺任何一項就不畫。
  if (!isCount(obs) || !isCount(paybacks) || !isCount(minObs) || paybacks > obs) return null;

  const determined = obs >= minObs;
  const branchRate = determined ? rate(paybacks, obs) : null;
  const stockObs = payload.stock_daytrade_obs;
  const stockPaybacks = payload.stock_daytrade_paybacks;
  const stockRate = rate(
    isCount(stockPaybacks) ? stockPaybacks : null,
    isCount(stockObs) ? stockObs : null,
  );
  const diff = branchRate != null && stockRate != null ? branchRate - stockRate : null;

  const summary = branchRate != null
    ? `${DAYTRADE_LABEL}：${obs} 次合格買超中有 ${paybacks} 次，${fmtPct(branchRate)}；`
      + (stockRate != null
        ? `此股自身 ${fmtPct(stockRate)}，${diff! >= 0 ? "高於" : "低於"}此股 ${fmtPp(diff!)}`
        : "此股自身比率未提供")
    : `${DAYTRADE_LABEL}：窗口內只有 ${obs} 次可觀察的合格買超，未達 ${minObs} 次，無法判定`;

  return (
    <div className="grid min-w-0 gap-1.5" role="group" aria-label={summary}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <span className="text-[12px] font-semibold text-foreground" title={DAYTRADE_DEFINITION}>
          {DAYTRADE_LABEL}
        </span>
        {determined ? (
          <span className="num text-[12.5px] text-foreground">
            <span className="font-bold">{paybacks}</span>
            <span className="text-muted-foreground"> / {obs} 次</span>
            {branchRate != null && <span className="ml-1 font-bold">{fmtPct(branchRate)}</span>}
          </span>
        ) : (
          <span className="text-[12px] font-semibold text-muted-foreground">無法判定</span>
        )}
      </div>

      {/* 同一條 0–100% 軸。未判定時不畫實心條——沒有可以畫的比率;但刻度線照畫,
          因為那把尺(此股自身)本身是已知的。 */}
      <div className="relative h-2.5 w-full rounded-full bg-secondary" aria-hidden="true">
        {branchRate != null && (
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-primary/70"
            style={{ width: `${Math.min(100, Math.max(0, branchRate))}%` }}
          />
        )}
        {stockRate != null && (
          <div
            className="absolute -top-1 h-4.5 w-0.5 rounded-full bg-[color:var(--ink-2)]"
            style={{ left: `${Math.min(100, Math.max(0, stockRate))}%`, transform: "translateX(-1px)" }}
          />
        )}
      </div>

      <p className="text-[11px] leading-snug text-muted-foreground">
        {determined ? (
          stockRate != null && isCount(stockPaybacks) && isCount(stockObs) ? (
            <>
              此股全體分點同項 {stockPaybacks} / {stockObs} 次（{fmtPct(stockRate)}）
              {diff != null && (
                <span className="text-foreground">
                  {" "}· {diff >= 0 ? "高於" : "低於"}此股 {fmtPp(diff)}
                </span>
              )}
            </>
          ) : (
            <>此股自身同項比率未提供，這一格沒有可比的尺</>
          )
        ) : (
          <>
            窗口內只有 {obs} 次可觀察的合格買超，未達 {minObs} 次，無法判定；
            這是次數不足，不是「沒有回吐」。
          </>
        )}
      </p>
    </div>
  );
}

/** 一側的證據列:分子/分母、該股自身比率,以及把兩者畫在同一條軸上的對照。 */
function SideBar({
  side,
  row,
  payload,
}: {
  side: SideSpec;
  row: BranchPctileRow;
  payload: BranchPctileCounts;
}) {
  const hit = side.hit(row);
  const known = side.known(row);
  const unknown = side.unknown(row);
  const branchRate = rate(hit, known);
  const stockHit = side.stockHit(payload);
  const stockKnown = side.stockKnown(payload);
  const stockRate = rate(stockHit, stockKnown);
  const diff = branchRate != null && stockRate != null ? branchRate - stockRate : null;

  const summary = branchRate != null
    ? `${side.label}：${known} 次分位可知中有 ${hit} 次，${fmtPct(branchRate)}；`
      + (stockRate != null
        ? `此股自身 ${fmtPct(stockRate)}，${diff! >= 0 ? "高於" : "低於"}此股 ${fmtPp(diff!)}`
        : "此股自身比率未提供")
    : `${side.label}：分位可知次數不足，無法計算比率`;

  return (
    <div className="grid min-w-0 gap-1.5" role="group" aria-label={summary}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
        <span className="text-[12px] font-semibold text-foreground" title={side.definition}>
          {side.label}
        </span>
        <span className="num text-[12.5px] text-foreground">
          <span className="font-bold">{hit}</span>
          <span className="text-muted-foreground"> / {known} 次</span>
          {branchRate != null && <span className="ml-1 font-bold">{fmtPct(branchRate)}</span>}
        </span>
      </div>

      {/* 同一條 0–100% 軸:實心條是這個分點,刻度線是這檔股票自身的同側比率。
          兩者畫在一起,差額才不必由讀的人心算。方向色刻意不用——這是計數,不是漲跌。 */}
      <div className="relative h-2.5 w-full rounded-full bg-secondary" aria-hidden="true">
        {branchRate != null && (
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-primary/70"
            style={{ width: `${Math.min(100, Math.max(0, branchRate))}%` }}
          />
        )}
        {stockRate != null && (
          <div
            className="absolute -top-1 h-4.5 w-0.5 rounded-full bg-[color:var(--ink-2)]"
            style={{ left: `${Math.min(100, Math.max(0, stockRate))}%`, transform: "translateX(-1px)" }}
          />
        )}
      </div>

      <p className="text-[11px] leading-snug text-muted-foreground">
        {stockRate != null && isCount(stockHit) && isCount(stockKnown) ? (
          <>
            此股全體分點同側 {stockHit} / {stockKnown} 次（{fmtPct(stockRate)}）
            {diff != null && (
              <span className="text-foreground">
                {" "}· {diff >= 0 ? "高於" : "低於"}此股 {fmtPp(diff)}
              </span>
            )}
          </>
        ) : (
          <>此股自身同側比率未提供，這一格沒有可比的尺</>
        )}
        {unknown > 0 && <>；另有 {unknown} 次分位不可知，未計入分母</>}
      </p>
    </div>
  );
}
