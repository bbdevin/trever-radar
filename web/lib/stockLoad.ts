/**
 * 個股資料載入(docs/44 P1 §3.2):新佈局優先,舊單一檔退回。
 *
 * 流程:抓 `stocks/core/{id}.json` → 404 就抓舊 `stocks/{id}.json`(一次到齊)。
 * 核心到了就並行抓 chips(四個籌碼鍵)與 hist(cut 以前的 K 線,只有聯集股有):
 *   1. core + chips 到 → `onUpdate({data, complete: !hist})`:第一次畫面(多空摘要要 chips,
 *      K 線主力 pane 也要,所以 chips 不延後)。
 *   2. hist 到 → `onUpdate({data: 全部, complete: true})`:多空摘要與 5 年／全部區間此時才算得出
 *      與舊單一檔一模一樣的結果。
 * hist 抓不到(部署瞬間雜湊換了):重抓一次 core 再抓 hist;還是不行就退回舊單一檔;舊檔也沒有才算失敗。
 *
 * 純邏輯、不碰 React,`fetcher` 可注入(node 測試)。
 */
import type { StockJson } from "./types.ts";
import { isSplitCore, mergeStockParts, type StockChipsFile, type StockCoreJson, type StockHistFile } from "./stockParts.ts";

export type Fetcher = (path: string, init?: RequestInit) => Promise<Response>;

export interface StockLoadState {
  data: StockJson;
  /** true = 舊單一檔的全部內容都在 data 裡(多空摘要可以算了) */
  complete: boolean;
}

export const STOCK_CORE_PATH = (id: string) => `/data/stocks/core/${encodeURIComponent(id)}.json`;
export const STOCK_LEGACY_PATH = (id: string) => `/data/stocks/${encodeURIComponent(id)}.json`;
const partPath = (rel: string) => `/data/stocks/${rel}`;

export class StockNotFound extends Error {
  readonly status: number;
  constructor(status: number) {
    super(`stock json ${status}`);
    this.status = status;
  }
}

async function getJson<T>(fetcher: Fetcher, path: string, init?: RequestInit): Promise<T> {
  const res = await fetcher(path, init);
  if (!res.ok) throw new StockNotFound(res.status);
  return (await res.json()) as T;
}

/** 只要核心(自選頁:最後兩根 K 線與 scores 都在核心)。舊資料時拿到的是舊單一檔。 */
export async function fetchStockCore(id: string, fetcher: Fetcher): Promise<StockJson> {
  try {
    return await getJson<StockJson>(fetcher, STOCK_CORE_PATH(id));
  } catch (e) {
    if (e instanceof StockNotFound && e.status === 404) return getJson<StockJson>(fetcher, STOCK_LEGACY_PATH(id));
    throw e;
  }
}

/**
 * 完整載入,漸進回報。回傳取消函式(換股時呼叫,之後的 onUpdate/onError 都不會再來)。
 */
export function loadStock(
  id: string,
  fetcher: Fetcher,
  onUpdate: (s: StockLoadState) => void,
  onError: (e: unknown) => void,
): () => void {
  let cancelled = false;
  const emit = (s: StockLoadState) => {
    if (!cancelled) onUpdate(s);
  };

  const fetchHist = (core: StockCoreJson) =>
    // 內容雜湊檔名:同名就是同內容,交給瀏覽器 HTTP 快取決定(Worker 標頭說多久就多久)。
    getJson<StockHistFile>(fetcher, partPath(core.parts.hist!.file), { cache: "default" });

  (async () => {
    const first = await fetchStockCore(id, fetcher);
    if (!isSplitCore(first)) {
      emit({ data: first, complete: true });
      return;
    }
    let core: StockCoreJson = first;
    const chipsP = core.parts.chips ? getJson<StockChipsFile>(fetcher, partPath(core.parts.chips.file)) : Promise.resolve(null);
    let histP: Promise<StockHistFile | null> = core.parts.hist ? fetchHist(core) : Promise.resolve(null);
    const chips = await chipsP;
    if (cancelled) return;
    emit({ data: mergeStockParts(core, null, chips), complete: !core.parts.hist });
    if (!core.parts.hist) return;

    let hist: StockHistFile | null;
    try {
      hist = await histP;
    } catch (e) {
      if (!(e instanceof StockNotFound)) throw e;
      // 雜湊換了:重抓 core(與它新指到的 hist 與 chips 同一版)。
      const again = await getJson<StockJson>(fetcher, STOCK_CORE_PATH(id));
      if (!isSplitCore(again)) {
        emit({ data: again, complete: true });
        return;
      }
      core = again;
      const chips2 = core.parts.chips ? await getJson<StockChipsFile>(fetcher, partPath(core.parts.chips.file)) : null;
      if (!core.parts.hist) {
        emit({ data: mergeStockParts(core, null, chips2), complete: true });
        return;
      }
      try {
        hist = await fetchHist(core);
      } catch (e2) {
        if (!(e2 instanceof StockNotFound)) throw e2;
        // 最後退路:舊單一檔(過渡期還在)。
        emit({ data: await getJson<StockJson>(fetcher, STOCK_LEGACY_PATH(id)), complete: true });
        return;
      }
      emit({ data: mergeStockParts(core, hist, chips2), complete: true });
      return;
    }
    emit({ data: mergeStockParts(core, hist, chips), complete: true });
  })().catch((e) => {
    if (!cancelled) onError(e);
  });

  return () => {
    cancelled = true;
  };
}
