/**
 * 個股資料載入(docs/44 P1 §3.2):新佈局優先,舊單一檔退回。
 *
 * 流程:抓 `stocks/core/{id}.json` → 404 就抓舊 `stocks/{id}.json`(一次到齊)。
 * 核心到了就並行抓 chips(四個籌碼鍵)與 hist(cut 以前的 K 線,只有聯集股有):
 *   1. core + chips 到 → `onUpdate({data, complete: !hist})`:第一次畫面(多空摘要要 chips,
 *      K 線主力 pane 也要,所以 chips 不延後)。chips 抓不到 → 退回舊單一檔。
 *   2. hist 到 → `onUpdate({data: 全部, complete: true})`:多空摘要與 5 年／全部區間此時才算得出
 *      與舊單一檔一模一樣的結果。
 * hist 階段的任何失敗都**不會**把已經畫出來的頁面換成錯誤:
 *   - 404(部署瞬間雜湊換了):重抓 core 再抓 hist;core 404 或 hist 又 404 → 退回舊單一檔;
 *   - 網路錯誤:重試一次;還是不行就保留已畫的部分,`histFailed: true` 讓頁面標一行說明。
 * 只有第一次畫面之前的失敗才走 onError。
 *
 * 純邏輯、不碰 React,`fetcher` 可注入(node 測試)。
 */
import type { StockJson } from "./types.ts";
import type { IntradayFile } from "./resample.ts";
import { isSplitCore, mergeStockParts, withBranchHistory, type StockChipsFile, type StockCoreJson, type StockHistFile } from "./stockParts.ts";

export type Fetcher = (path: string, init?: RequestInit) => Promise<Response>;

export interface StockLoadState {
  data: StockJson;
  /** true = 舊單一檔的全部內容都在 data 裡(多空摘要可以算了) */
  complete: boolean;
  /** 較早的 K 線歷史最後仍抓不到:data 只到核心那段,complete 永遠不會變 true。 */
  histFailed?: boolean;
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

export const STOCK_INTRADAY_PATH = (id: string) => `/data/stocks/intraday/${encodeURIComponent(id)}.json`;

/** 分K檔(docs/50,只有榜單聯集股有)。404 = 這檔沒有分K → null;其他失敗丟 StockNotFound。
 *  形狀不對(沒有 bars 陣列或一根都沒有)也當作沒有。 */
export async function fetchStockIntraday(id: string, fetcher: Fetcher): Promise<IntradayFile | null> {
  const res = await fetcher(STOCK_INTRADAY_PATH(id));
  if (res.status === 404) return null;
  if (!res.ok) throw new StockNotFound(res.status);
  const body = (await res.json()) as IntradayFile;
  return Array.isArray(body?.bars) && body.bars.length > 0 ? body : null;
}

/** 舊單一檔;抓不到回 null(呼叫端決定要不要當失敗)。`--legacy-stocks` 寫的檔也可能帶 v2 `branch_days`。 */
async function tryLegacy(id: string, fetcher: Fetcher): Promise<StockJson | null> {
  try {
    return withBranchHistory(await getJson<StockJson>(fetcher, STOCK_LEGACY_PATH(id)));
  } catch {
    return null;
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
  const fetchChips = (core: StockCoreJson) =>
    core.parts.chips ? getJson<StockChipsFile>(fetcher, partPath(core.parts.chips.file)) : Promise.resolve(null);

  /** hist 404 之後的恢復:重抓 core 與它指到的 chips/hist;任一環節失敗回 null(呼叫端退舊檔)。 */
  async function recoverAfterHist404(): Promise<StockLoadState | null> {
    try {
      const again = await getJson<StockJson>(fetcher, STOCK_CORE_PATH(id));
      if (!isSplitCore(again)) return { data: withBranchHistory(again), complete: true };
      const chips2 = await fetchChips(again);
      if (!again.parts.hist) return { data: mergeStockParts(again, null, chips2), complete: true };
      const hist2 = await fetchHist(again);
      return { data: mergeStockParts(again, hist2, chips2), complete: true };
    } catch {
      return null;
    }
  }

  (async () => {
    const first = await fetchStockCore(id, fetcher);
    if (!isSplitCore(first)) {
      emit({ data: withBranchHistory(first), complete: true });
      return;
    }
    const core: StockCoreJson = first;
    const histP: Promise<StockHistFile | null> = core.parts.hist ? fetchHist(core) : Promise.resolve(null);
    histP.catch(() => {}); // 這裡只是先發出去;錯誤在下面 await 時處理,不要變成 unhandled rejection
    let chips: StockChipsFile | null;
    try {
      chips = await fetchChips(core);
    } catch (e) {
      // chips 抓不到(404 或網路):第一次畫面還沒出,退回舊單一檔;舊檔也沒有才算失敗。
      const legacy = await tryLegacy(id, fetcher);
      if (!legacy) throw e;
      emit({ data: legacy, complete: true });
      return;
    }
    if (cancelled) return;
    const partial = mergeStockParts(core, null, chips);
    emit({ data: partial, complete: !core.parts.hist });
    if (!core.parts.hist) return;

    // ── 以下已經有畫面:任何失敗都只能「保留已畫的 + 標記」,不能丟 onError ──
    let hist: StockHistFile | null = null;
    try {
      hist = await histP;
    } catch (e) {
      if (e instanceof StockNotFound) {
        // 雜湊換了(部署瞬間):重抓 core;不行就退回舊單一檔(過渡期還在)。
        const recovered = (await recoverAfterHist404()) ?? (await (async () => {
          const legacy = await tryLegacy(id, fetcher);
          return legacy ? { data: legacy, complete: true } : null;
        })());
        if (recovered) {
          emit(recovered);
          return;
        }
      } else {
        // 網路錯誤:再試一次。
        try {
          hist = await fetchHist(core);
        } catch {
          hist = null;
        }
      }
    }
    if (hist) {
      emit({ data: mergeStockParts(core, hist, chips), complete: true });
    } else {
      emit({ data: partial, complete: false, histFailed: true });
    }
  })().catch((e) => {
    if (!cancelled) onError(e);
  });

  return () => {
    cancelled = true;
  };
}
