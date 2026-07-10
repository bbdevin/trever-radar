export interface Candle {
  t: string; // YYYY-MM-DD
  o: number;
  h: number;
  l: number;
  c: number;
  v: number; // 張
  amt: number; // 元
  af: number; // backward adjustment factor(均線等指標由前端以全序列計算)
}

/** 分點進出(張;權證列可展開) */
export interface BranchRow {
  name: string;
  buy: number;
  sell: number;
  net: number;
  pct?: number | null;
}

export interface ReasonItem {
  code: string;
  points?: number;
  text: string;
  value?: number | string | null;
}

export interface TechnicalSummary {
  score: number;
  ma20: number | null;
  ma60: number | null;
  rsi14: number | null;
  volume_ratio: number | null;
  reasons: ReasonItem[];
  risks: ReasonItem[];
}

export interface WarrantSummary {
  call_turnover: number;
  call_volume: number;
  call_count: number;
  put_turnover: number;
  put_volume: number;
  put_count: number;
  call_avg20: number | null;
  call_turnover_ratio: number | null;
  put_call_ratio: number | null;
}

export interface WarrantHistoryPoint {
  t: string;
  call_turnover: number;
  put_turnover: number;
  call_count: number;
  put_count: number;
}

export interface ActiveWarrant {
  id: string;
  name: string;
  kind: "call" | "put";
  strike: number | null;
  exercise_ratio: number | null;
  maturity_date: string | null;
  close: number | null;
  volume_lots: number;
  turnover: number;
  branches?: BranchRow[]; // 該權證當日前8大分點進出(僅上市權證有來源)
}

export interface StockJson {
  id: string;
  name: string;
  market: "twse" | "tpex";
  candles: Candle[];
  scores: ScoreBreakdown | null;
  reasons: string[];
  risks: string[];
  technical: TechnicalSummary | null;
  branches: BranchRow[];
  branch_history?: {
    t: string;
    branches: {
      n: string;
      b: number;
      s: number;
      net: number;
    }[];
  }[];
  warrant: WarrantSummary | null;
  warrant_history: WarrantHistoryPoint[];
  active_warrants: ActiveWarrant[];
}

/** 產業下鑽子題材(僅 sectors 帶;口徑同題材聚合但限定產業內成分) */
export interface SectorSubFlow {
  name: string;
  turnover: number;
  vs20: number | null; // 今日金額 / 該(產業,題材)組合近20日均
  avg_chg: number | null;
  up: number;
  down: number;
  top: { id: string; name: string; chg_pct: number | null }[]; // 產業內金額前 5
}

export interface SectorFlow {
  name: string;
  turnover: number;
  share: number; // 佔全市場 %(題材成分重疊,僅供相對比較)
  vs20: number | null; // 今日金額 / 20 日均 → 資金流入/流出
  avg_chg: number | null;
  up: number;
  down: number;
  top: { id: string; name: string; chg_pct: number | null; turnover?: number }[];
  subs?: SectorSubFlow[]; // 產業內成分 ≥2 檔的題材,依金額取前 10;題材模式(themes)無此欄
}

export type ListKey = "score" | "hot" | "surge" | "strong" | "weak" | "warrant";

export interface ConcentrationRow {
  id: string;
  name: string;
  market: "twse" | "tpex";
  buy_concentration: number; // 前5大買超分點佔今日成交量比
  concentration_avg20: number; // 近20日均值(不含當日)
  vs20: number; // 躍升幅度(今日 / 20日均)
}

export interface ScoreBreakdown {
  final: number;
  branch: number | null;
  warrant: number | null;
  tech: number | null;
  inst: number | null;
  theme: number | null;
  risk_penalty: number;
  watch_price: number | null;
  stop_price: number | null;
}

export interface RadarStock {
  spark: number[]; // 近 30 日收盤
  id: string;
  name: string;
  market: "twse" | "tpex";
  industry: string | null;
  description?: string | null;
  themes?: string[];
  close: number;
  chg_pct: number | null;
  volume_ratio: number | null; // 今日量 / 20 日均量
  turnover: number;
  volume_lots: number;
  transactions: number | null;
  foreign_net_lots: number | null;
  trust_net_lots: number | null;
  margin_chg_lots: number | null;
  warrant: WarrantSummary | null;
  technical: TechnicalSummary | null;
  scores: ScoreBreakdown | null; // null = 該股當日未評分(流動性門檻未過等)
  reasons: string[];
  raw_reasons?: ReasonItem[];
  risks: string[];
}

export interface RadarJson {
  data_date: string;
  generated_at: string;
  note: string;
  summary: { market: string; turnover: number; up: number; down: number }[];
  freshness?: Record<string, { date: string | null; stale: boolean }>; // 各資料集有效日
  sectors: SectorFlow[];
  themes?: SectorFlow[]; // 概念股資金流(成分重疊)
  concentration?: ConcentrationRow[]; // 集中度躍升榜(探索頁)
  lists: Record<ListKey, string[]>;
  strategies?: Record<string, string[]>;
  stocks: RadarStock[];
}

export interface MetaJson {
  generated_at: string;
  datasets: {
    source: string;
    dataset: string;
    date: string;
    rows: number;
    status: "ok" | "empty" | "error";
    run_at: string;
  }[];
}
