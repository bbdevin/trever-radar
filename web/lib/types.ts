export interface Candle {
  t: string; // YYYY-MM-DD
  o: number;
  h: number;
  l: number;
  c: number;
  v: number; // 張
  amt: number; // 元
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
}

export interface StockJson {
  id: string;
  name: string;
  market: "twse" | "tpex";
  candles: Candle[];
  warrant: WarrantSummary | null;
  warrant_history: WarrantHistoryPoint[];
  active_warrants: ActiveWarrant[];
}

export interface SectorFlow {
  name: string;
  turnover: number;
  share: number; // 佔全市場 %
  vs20: number | null; // 今日金額 / 20 日均
  avg_chg: number | null;
  up: number;
  down: number;
  top: { id: string; name: string; chg_pct: number | null }[];
}

export type ListKey = "hot" | "surge" | "strong" | "warrant";

export interface RadarStock {
  spark: number[]; // 近 30 日收盤
  id: string;
  name: string;
  market: "twse" | "tpex";
  industry: string | null;
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
  scores: null | Record<string, number>; // null until scoring module ships
  reasons: string[];
  risks: string[];
}

export interface RadarJson {
  data_date: string;
  generated_at: string;
  note: string;
  summary: { market: string; turnover: number; up: number; down: number }[];
  sectors: SectorFlow[];
  lists: Record<ListKey, string[]>;
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
