export interface Candle {
  t: string; // YYYY-MM-DD
  o: number;
  h: number;
  l: number;
  c: number;
  v: number; // 張
  amt: number; // 元
}

export interface StockJson {
  id: string;
  name: string;
  market: "twse" | "tpex";
  candles: Candle[];
}

export interface RadarStock {
  spark: number[]; // 近 30 日收盤
  id: string;
  name: string;
  market: "twse" | "tpex";
  close: number;
  chg_pct: number | null;
  turnover: number;
  volume_lots: number;
  transactions: number | null;
  foreign_net_lots: number | null;
  trust_net_lots: number | null;
  margin_chg_lots: number | null;
  scores: null | Record<string, number>; // null until scoring module ships
  reasons: string[];
  risks: string[];
}

export interface RadarJson {
  data_date: string;
  generated_at: string;
  note: string;
  summary: { market: string; turnover: number; up: number; down: number }[];
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
