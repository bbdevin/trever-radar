/**
 * 個股 JSON 拆檔(docs/44 P1 §3.2)的前端合併規則。與 `pipeline/radar/export/stock_parts.py`
 * 是同一條規則的兩個實作:`stocks/core/{id}.json`(含 `parts` 指標)+ `stocks/hist/{id}.{hash}.json`
 * (cut 以前的 K 線)+ `stocks/chips/{id}.json`(四個籌碌鍵)接回來。只換包裝,不改任何值。
 *
 * chips v2(docs/44 §3.4,2026-10-10):`branch_history`(每天 |淨額| 前 12 列)換成緊湊的 `branch_days`
 * (每天全部列、名字查表)。接回時在這裡解碼成 `branch_history` 的形狀,畫面與事實一律讀 `branch_history`;
 * 舊 chips v1 直接放回。`decodeBranchDays` 與 Python `decode_branch_days` 是同一條規則。
 *
 * 只用相對路徑 import、不碰 React、不碰 fetch:多方榜建置器(node 直接跑 TS)與個股頁共用。
 */
import type { BranchDay, BranchDaysV2, Candle, StockJson } from "./types.ts";

/** chips 檔可能帶的鍵(v1 `branch_history` 與 v2 `branch_days` 都認)。 */
export const CHIPS_KEYS = ["branch_days", "branch_history", "branch_pctile_counts", "branch_tags", "branch_pnl_est"] as const;
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

export type StockChipsFile = { version: number; id: string } & Partial<Pick<StockJson, ChipsKey>>;

/** 核心檔:舊 StockJson 的子集 + `parts`。chips 鍵在這裡一定不存在。 */
export type StockCoreJson = StockJson & { parts: StockParts };

export function isSplitCore(json: StockJson): json is StockCoreJson {
  const p = (json as Partial<StockCoreJson>).parts;
  return !!p && typeof p === "object" && typeof p.version === "number" && !!p.chips;
}

/** `branch_days` v2 → `branch_history` 形狀(新→舊)。壞形狀(不是 v2)回 []。 */
export function decodeBranchDays(v2: BranchDaysV2 | null | undefined): BranchDay[] {
  if (!v2 || !Array.isArray(v2.names) || !Array.isArray(v2.days)) return [];
  const names = v2.names;
  return v2.days.map(([t, rows]) => ({
    t,
    branches: rows.map((r) => ({ n: names[r[0]] ?? "", b: r[1], s: r[2], net: r.length > 3 ? r[3] : r[1] - r[2] })),
  }));
}

/**
 * 同一個物件就地正規化:有 `branch_days` 就解碼成 `branch_history` 並拿掉 `branch_days`(畫面不讀它)。
 * 沒有 `branch_days`(舊 JSON)原樣。回傳同一個物件,方便串接。
 */
export function withBranchHistory<T extends StockJson>(json: T): T {
  if (json.branch_days !== undefined) {
    if (json.branch_days) json.branch_history = decodeBranchDays(json.branch_days);
    delete json.branch_days;
  }
  return json;
}

/**
 * 三份接回一份。`hist` / `chips` 缺省(還沒抓到或這檔沒有)就只接有的;
 * 回傳的物件沒有 `parts`。chips 檔的 `version`/`id` 包裝不會進結果,只搬 CHIPS_KEYS 裡**真的有**的鍵;
 * v2 的 `branch_days` 解碼成 `branch_history`。
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
  return withBranchHistory(out as unknown as StockJson);
}

/** 舊單一檔原樣回傳(只正規化 branch_days);核心檔接回。給只讀磁碟的程式(建置器)用。 */
export function mergeIfSplit(json: StockJson, read: (relToStocks: string) => unknown): StockJson {
  if (!isSplitCore(json)) return withBranchHistory(json);
  const hist = json.parts.hist ? (read(json.parts.hist.file) as StockHistFile) : null;
  const chips = json.parts.chips ? (read(json.parts.chips.file) as StockChipsFile) : null;
  return mergeStockParts(json, hist, chips);
}
