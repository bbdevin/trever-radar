/**
 * 個股 JSON 拆檔(docs/44 P1 §3.2)的前端合併規則。與 `pipeline/radar/export/stock_parts.py`
 * 是同一條規則的兩個實作:`stocks/core/{id}.json`(含 `parts` 指標)+ `stocks/hist/{id}.{hash}.json`
 * (cut 以前的 K 線)+ `stocks/chips/{id}.json`(四個籌碼鍵)接回來,必須與舊單一檔
 * `stocks/{id}.json` 逐鍵深度相等。只換包裝,不改任何值。
 *
 * 只用相對路徑 import、不碰 React、不碰 fetch:多方榜建置器(node 直接跑 TS)與個股頁共用。
 */
import type { Candle, StockJson } from "./types.ts";

export const CHIPS_KEYS = ["branch_history", "branch_pctile_counts", "branch_tags", "branch_pnl_est"] as const;
export type ChipsKey = (typeof CHIPS_KEYS)[number];

export interface StockHistPointer {
  /** 相對 `stocks/` 的路徑,例:`hist/2330.1a2b3c4d.json` */
  file: string;
  bars: number;
  cut: string;
  first: string;
}

export interface StockParts {
  version: number;
  hist: StockHistPointer | null;
  chips: { file: string; keys: string[] };
}

export interface StockHistFile {
  version: number;
  id: string;
  cut: string;
  bars: number;
  candles: Candle[];
}

export type StockChipsFile = { version: number; id: string } & Pick<StockJson, ChipsKey>;

/** 核心檔:舊 StockJson 的子集 + `parts`。chips 四鍵在這裡一定不存在。 */
export type StockCoreJson = StockJson & { parts: StockParts };

export function isSplitCore(json: StockJson): json is StockCoreJson {
  const p = (json as Partial<StockCoreJson>).parts;
  return !!p && typeof p === "object" && typeof p.version === "number" && !!p.chips;
}

/**
 * 三份接回一份。`hist` / `chips` 缺省(還沒抓到或這檔沒有)就只接有的;
 * 回傳的物件沒有 `parts`。chips 檔的 `version`/`id` 包裝不會進結果,只搬 CHIPS_KEYS 裡**真的有**的鍵。
 */
export function mergeStockParts(
  core: StockJson,
  hist?: StockHistFile | null,
  chips?: Partial<StockChipsFile> | null,
): StockJson {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(core)) {
    if (k === "parts") continue;
    out[k] = k === "candles" && hist ? [...hist.candles, ...(v as Candle[])] : v;
  }
  if (chips) {
    for (const k of CHIPS_KEYS) {
      if (k in chips && chips[k] !== undefined) out[k] = chips[k];
    }
  }
  return out as unknown as StockJson;
}

/** 舊單一檔原樣回傳;核心檔接回。給只讀磁碟的程式(建置器)用。 */
export function mergeIfSplit(json: StockJson, read: (relToStocks: string) => unknown): StockJson {
  if (!isSplitCore(json)) return json;
  const hist = json.parts.hist ? (read(json.parts.hist.file) as StockHistFile) : null;
  const chips = json.parts.chips ? (read(json.parts.chips.file) as StockChipsFile) : null;
  return mergeStockParts(json, hist, chips);
}
