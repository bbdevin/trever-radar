/**
 * 首頁資料載入(docs/44 P2):`home/head.json` 先到,`home/stocks.json` 等到要畫股票的分頁才抓;
 * 新佈局抓不到(舊資料、並行 export 的空窗、網路錯誤)一律退回 `radar.json` 一次到齊。
 *
 * 為什麼拆:radar.json(正式約 770 KB raw)每次打開首頁都整包下載,而預設分頁「多方榜」只讀表頭
 * (資料日、成交額、分頁檔數、題材/產業資金流),stocks 那一大塊要到未發動/策略/掃描…分頁才用。
 * 兩個檔由同一輪 export 寫出、帶同一個 `generated_at`;對不上就是兩輪夾到(mid-backfill 並行匯出),
 * 重抓一次 head 讓兩者同輪,還是不行就退回 radar.json(一個檔永遠自洽)。
 *
 * 投影(與 pipeline/radar/export/home_split.py 同一份清單,pytest 讀本檔核對):
 * - head 沒有 HOME_DROPPED_TOP 那幾個頂層鍵(首頁沒讀);
 * - 每檔沒有 HOME_DROPPED_STOCK 那幾個欄位(卡片沒畫),warrant 只有 HOME_WARRANT_KEYS 三鍵。
 * 畫面上每一個數字都還在;少掉的欄位在 RadarStock 型別上標為可選,免得有人以後在卡片上讀它而不自知。
 *
 * 純邏輯、不碰 React,`fetcher` 可注入(node 測試)。
 */
import type { RadarHeadJson, RadarJson, RadarStock } from "./types.ts";

export type Fetcher = (path: string, init?: RequestInit) => Promise<Response>;

export const HOME_HEAD_PATH = "/data/home/head.json";
export const HOME_STOCKS_PATH = "/data/home/stocks.json";
export const RADAR_PATH = "/data/radar.json";

/** 與 home_split.py 一致(順序也一樣;pytest 會比對)。 */
export const HOME_DROPPED_TOP = ["concentration", "summary_text", "score_list_meta"];
export const HOME_DROPPED_STOCK = ["technical", "volume_lots", "transactions", "margin_chg_lots", "chg5_pct", "pocket_score", "pocket_families"];
export const HOME_WARRANT_KEYS = ["call_turnover", "call_turnover_ratio", "call_count"];

export interface HomeStocksFile {
  version: number;
  data_date: string;
  generated_at: string;
  stocks: RadarStock[];
}

export interface HomeData {
  head: RadarHeadJson;
  /** null = 拆檔佈局、還沒抓(首頁預設分頁不需要) */
  stocks: RadarStock[] | null;
  layout: "split" | "legacy";
}

export class HomeNotFound extends Error {
  readonly status: number;
  constructor(status: number) {
    super(`home json ${status}`);
    this.status = status;
  }
}

async function getJson<T>(fetcher: Fetcher, path: string): Promise<T> {
  const res = await fetcher(path);
  if (!res.ok) throw new HomeNotFound(res.status);
  return (await res.json()) as T;
}

/** 舊單一檔 → 一次到齊(head = radar 扣掉 stocks)。 */
function fromLegacy(radar: RadarJson): HomeData {
  const { stocks, ...head } = radar;
  return { head, stocks, layout: "legacy" };
}

async function loadLegacy(fetcher: Fetcher): Promise<HomeData> {
  return fromLegacy(await getJson<RadarJson>(fetcher, RADAR_PATH));
}

/**
 * 第一步:只要表頭。拆檔佈局 → `stocks: null`;抓不到(404、其他錯誤)→ 退回 radar.json。
 * radar.json 也抓不到才丟錯(與今天「找不到資料」的錯誤畫面相同)。
 */
export async function loadHomeHead(fetcher: Fetcher): Promise<HomeData> {
  try {
    const head = await getJson<RadarHeadJson>(fetcher, HOME_HEAD_PATH);
    return { head, stocks: null, layout: "split" };
  } catch {
    return loadLegacy(fetcher);
  }
}

/**
 * 第二步:要畫股票的分頁打開時抓 stocks。回傳與 head **同一輪**的一對;head 可能被換成較新的那一份
 * (兩輪夾到時:stocks 是新輪 → 重抓 head 也拿到新輪;若 head 已經是新輪而 stocks 舊 → 重抓 stocks)。
 * 兩次都對不上、或任一檔抓不到 → 退回 radar.json。已經有 stocks 的 HomeData 原樣回傳。
 */
export async function loadHomeStocks(fetcher: Fetcher, home: HomeData): Promise<HomeData> {
  if (home.stocks) return home;
  try {
    const first = await getJson<HomeStocksFile>(fetcher, HOME_STOCKS_PATH);
    if (first.generated_at === home.head.generated_at) return { ...home, stocks: first.stocks };
    const head2 = await getJson<RadarHeadJson>(fetcher, HOME_HEAD_PATH);
    if (head2.generated_at === first.generated_at) return { head: head2, stocks: first.stocks, layout: "split" };
    const second = await getJson<HomeStocksFile>(fetcher, HOME_STOCKS_PATH);
    if (second.generated_at === head2.generated_at) return { head: head2, stocks: second.stocks, layout: "split" };
  } catch {
    /* 退回 radar.json */
  }
  return loadLegacy(fetcher);
}
