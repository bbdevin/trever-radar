import type {
  FuturesAnomaly,
  FuturesContract,
  FuturesDaily,
  FuturesInfo,
  FuturesOpenInterestDirection,
  FuturesVolumeAnomalyEntry,
  FuturesVolumeAnomalyMeta,
  ReasonItem,
} from "@/lib/types";

/**
 * 個股期貨存在狀態的三態判定(這個功能的重點)。
 *
 * - "unknown"：payload 完全沒有 `futures` 鍵——我們還沒 import-futures 過,
 *   不知道答案,不可以顯示成「沒有期貨」。
 * - "none"：`futures.contracts` 是空陣列——TAIFEX 完整官方清單截至
 *   `asOf` 這天確實不含這檔,是一個帶日期的正面主張。
 * - "has"：`futures.contracts` 非空——這檔股票有對應的個股期貨/選擇權契約。
 *
 * 把這個判斷抽成純函式(同 ReasonPill.tsx 的 isChipStrategyCode),因為
 * unknown 和 none 一旦被同一段 JSX 條件式不小心揉在一起,使用者會被告知
 * 一件假的事——「還沒匯入」被讀成「已確認沒有」。
 */
export type FuturesState =
  | { kind: "unknown" }
  | { kind: "none"; asOf: string }
  | { kind: "has"; asOf: string; contracts: FuturesContract[] };

export function futuresState(futures: FuturesInfo | null | undefined): FuturesState {
  if (!futures) return { kind: "unknown" };
  if (futures.contracts.length === 0) return { kind: "none", asOf: futures.list_as_of };
  return { kind: "has", asOf: futures.list_as_of, contracts: futures.contracts };
}

/* ------------------------------------------------------------------ *
 * 成交量異常(docs/38 §7)的呈現判斷。
 *
 * 全部抽成純函式的理由同上:這一節的每一條規則都是「不可以顯示什麼」,
 * 而「不可以」沒辦法靠讀 JSX 驗證。以下四條被測試鎖住:
 *   §7.5  市場層級鍵的三態不得塌成兩態。
 *   §7.1 / §7.4  `oi_change` 缺鍵 → 整列不顯示(不是 0、不是破折號)。
 *   §5 / §7.5  不排名:不算比率、不給名次,順序原封不動照 payload。
 *   §0 / §7.10  單位是契約不是股票,同一檔的兩個契約都要活下來。
 * ------------------------------------------------------------------ */

/** 口數的千分位;單位字(口)由呼叫端排版,不混進數字。 */
export function fmtLotsAbs(n: number): string {
  return n.toLocaleString("zh-TW");
}

/** 未平倉變化是有號的量,`0` 顯示為 `0`(它是一個真的觀測,不是缺值)。 */
export function fmtLotsSigned(n: number): string {
  const s = Math.abs(n).toLocaleString("zh-TW");
  return n > 0 ? `+${s}` : n < 0 ? `-${s}` : "0";
}

/**
 * 異常區塊要顯示的事實列。**只是把 payload 裡的整數換成字串**——
 * 沒有除法、沒有差值、沒有名次。`window_days` 從區塊讀進標籤(§7.10),
 * `oi_change` 缺鍵時這裡就少一列(§7.1),呼叫端不需要知道它可能缺。
 */
export interface FuturesAnomalyFact {
  key: "today" | "window_max" | "window_median" | "oi_change";
  label: string;
  value: string;
  unit: string;
}

export function anomalyFacts(a: FuturesAnomaly): FuturesAnomalyFact[] {
  const days = fmtLotsAbs(a.window_days);
  const facts: FuturesAnomalyFact[] = [
    // 「今日」不可以出現在這裡:這一列講的是期貨行情日,而那一天通常不是使用者
    // 眼前的今天(§7.12)。日期由外面的標題講,標籤只講它是什麼數字。
    { key: "today", label: "一般時段成交", value: fmtLotsAbs(a.today), unit: "口" },
    { key: "window_max", label: `前 ${days} 個比較日最高`, value: fmtLotsAbs(a.window_max), unit: "口" },
    { key: "window_median", label: `前 ${days} 個比較日中位數`, value: fmtLotsAbs(a.window_median), unit: "口" },
  ];
  // 缺鍵就是缺鍵:不補 0、不補破折號、不加一句「未公布」(§7.1)。
  if (a.oi_change !== undefined) {
    facts.push({ key: "oi_change", label: "未平倉較前日", value: fmtLotsSigned(a.oi_change), unit: "口" });
  }
  return facts;
}

/** 名單上的一列。刻意沒有 rank / position / score / ratio 這類鍵(§5、§7.5)。 */
export interface FuturesAnomalyRow {
  stockId: string;
  /** 解析不到股名時為 null——顯示 id 本身,不編一個標籤出來。 */
  name: string | null;
  code: string;
  facts: FuturesAnomalyFact[];
  reasons: ReasonItem[];
  risks: ReasonItem[];
}

/**
 * 市場層級名單的三態(§7.5)。缺鍵與空陣列**不同**:
 * 前者沒有主張,後者是一個帶日期的正面主張。
 *
 * `computed-empty` 帶著 `windowDays`(§7.11):空名單裡一個 `anomaly` 區塊都沒有,
 * 而 §7.10 不准在前端寫死 60,所以那個數字只能來自 payload 的 `_meta` 鍵。
 * 拿不到時是 `null`——那就少講比較窗口,**不是**退回一個寫死的 60,因為一個寫死
 * 的 60 會變成第二個不受 §3.5 管束的真相。
 */
export type FuturesAnomalyMarketState =
  | { kind: "not-computed" }
  | { kind: "computed-empty"; dataDate: string; asOf: string | null; windowDays: number | null }
  | { kind: "listed"; dataDate: string; asOf: string | null; rows: FuturesAnomalyRow[] };

export function futuresAnomalyMarketState(
  entries: FuturesVolumeAnomalyEntry[] | null | undefined,
  dataDate: string,
  nameById?: ReadonlyMap<string, string>,
  meta?: FuturesVolumeAnomalyMeta | null,
): FuturesAnomalyMarketState {
  if (!entries) return { kind: "not-computed" };
  // `asOf` 是期貨行情日,只能來自 payload(§7.12)。讀不到就是 null——
  // **不可以**退回 `dataDate`:那會把期貨的結果掛到現貨的日子上,而這兩個
  // 日期常態相差一個交易日,正是這個鍵存在的理由。
  const asOf = meta?.as_of ?? null;
  if (entries.length === 0) {
    return {
      kind: "computed-empty", dataDate, asOf,
      windowDays: meta?.window_days ?? null,
    };
  }
  // 順序原封不動(payload 已依 today − window_max 遞減排好);不排序、不去重。
  const rows = entries.map((e) => ({
    stockId: e.stock_id,
    name: nameById?.get(e.stock_id) ?? null,
    code: e.code,
    facts: anomalyFacts(e.anomaly),
    reasons: e.reasons,
    risks: e.risks,
  }));
  return { kind: "listed", dataDate, asOf, rows };
}

/**
 * 「算過了、今天沒有契約舉旗」那一句(§7.5 第二態)。
 *
 * 它**不在元件裡**的理由與這個檔案其他函式相同:句子裡有一個數字,而那個數字
 * 唯一合法的來源是 payload(§7.10)。寫在 JSX 裡沒有東西擋得住有人直接打一個 60;
 * 寫在這裡,`futures.test.ts` 餵 20 進來就會抓到。
 * `windowDays` 是 null(payload 沒給)時整段子句拿掉,句子照樣是一個帶日期的
 * 正面主張,只是少講比較基準——同 §7.1 的習慣:缺值就是缺值,不編一個數字上去。
 */
export function anomalyEmptyStateText(
  state: { asOf: string | null; windowDays: number | null },
): string {
  const high = state.windowDays === null
    ? "創新高"
    : `創 ${state.windowDays} 個比較日新高`;
  // 日期是**期貨行情日**,不是頁面的資料日(§7.12)。句子裡也不出現「今日」:
  // 這份計算講的不是使用者眼前的那一天,寫「今日」會把兩個日子說成同一天。
  const head = state.asOf === null ? "已完成計算" : `期貨 ${state.asOf} 已完成計算`;
  return `${head}:沒有契約的一般時段成交量${high}。`;
}

/**
 * 「期貨行情日與本頁其他資料不同一天」那一句(§7.12)。
 *
 * 兩個**有主張**的狀態(算過了沒有 / 算過了有名單)都要講,而且只在真的不同天
 * 的時候講;相同就回 `null`,不留一句廢話。這句話**不說「落後一天」**——前端
 * 沒有交易日曆,數不出兩個日期差幾個交易日,只說得出它們是哪兩天。
 */
export function anomalyLagText(asOf: string | null, dataDate: string): string | null {
  if (asOf === null || asOf === dataDate) return null;
  return `期貨行情日 ${asOf};本頁其他資料為 ${dataDate}。`;
}

/* ------------------------------------------------------------------ *
 * 每日事實(docs/38 §7.14)。旗標是少數,事實是全部:一天約 320 個契約有
 * `daily`,其中舉旗的通常個位數。以下三條被測試鎖住:
 *   §7.6   `daily.volume`(兩時段合計)與 `anomaly.today`(只有一般時段)
 *          是兩個數字,標籤必須自己講得清楚——兩者可能同時出現在同一頁上。
 *   §7.1   `oi_change` 缺鍵 → 整列不顯示;`0` 是一個真的觀測,顯示 0。
 *   §1     不算比率、不算差值、不給名次:每個顯示值都是 payload 裡的整數。
 * 未平倉是**存量**,沒有時段之分(盤後列的來源是 NULL),所以時段拆分只出現在
 * 成交量那幾列,未平倉那兩列不帶任何時段字樣。
 * ------------------------------------------------------------------ */

export interface FuturesDailyFact {
  /** `session:<名稱>` 是時段列;其餘是 payload 的鍵名本人。 */
  key: string;
  label: string;
  value: string;
  unit: string;
}

/** 已知時段的顯示順序;之外的(來源日後多一個時段)照字典序接在後面。 */
const SESSION_ORDER = ["一般", "盤後"];

function orderedSessions(sessionVolume: Record<string, number>): string[] {
  const keys = Object.keys(sessionVolume);
  const known = SESSION_ORDER.filter((s) => keys.includes(s));
  const rest = keys.filter((s) => !SESSION_ORDER.includes(s)).sort();
  return [...known, ...rest];
}

export function dailyFacts(daily: FuturesDaily): FuturesDailyFact[] {
  const facts: FuturesDailyFact[] = [];
  // 「合計」兩個字是這一列唯一的工作:旁邊的異常區塊有一列叫「一般時段成交」,
  // 而那個數字**不含盤後**(R3)。兩個數字同時出現在一頁上,分辨它們的東西
  // 只有標籤(§7.6)。所以這裡不叫「成交量」,叫它到底加了哪些時段。
  if (daily.volume !== null) {
    facts.push({ key: "volume", label: "一般+盤後合計成交", value: fmtLotsAbs(daily.volume), unit: "口" });
  }
  // 只列出**真的有列**的時段;沒有的時段不補 0(補 0 = 謊報「沒人交易」)。
  for (const session of orderedSessions(daily.session_volume)) {
    facts.push({
      key: `session:${session}`,
      label: `${session}時段成交`,
      value: fmtLotsAbs(daily.session_volume[session]),
      unit: "口",
    });
  }
  // 未平倉是存量:它沒有時段,所以標籤裡也不出現時段。
  if (daily.open_interest !== null) {
    facts.push({ key: "open_interest", label: "未平倉", value: fmtLotsAbs(daily.open_interest), unit: "口" });
  }
  // 缺鍵就是缺鍵:不補 0、不補破折號、不加一句「未公布」(§7.1)。而 `0` 會走到
  // 這裡並顯示成 `0`——「一口都沒變」是一個觀測,與「不知道」在畫面上長得一樣,
  // 分辨它們的只有這一列在不在。
  if (daily.oi_change !== undefined) {
    facts.push({ key: "oi_change", label: "未平倉較前日", value: fmtLotsSigned(daily.oi_change), unit: "口" });
  }
  return facts;
}

/**
 * 個股頁:契約裡帶 `daily` 的那些(§7.14)。旗標與這件事無關,所以這裡**不**看
 * `anomaly`;沒有 `daily` 的契約不進清單,也**不會**被標成「正常」——缺席有
 * 未掛牌 / 未公布 / 匯入失敗三種意思,刻意不可分辨(§7.7)。
 * 同一檔股票的兩個契約(1565 的 MYF/OMF)各自一列,不依股票去重(§7.10)。
 */
export type DatedContract = FuturesContract & { daily: FuturesDaily };

export function contractsWithDaily(contracts: FuturesContract[]): DatedContract[] {
  return contracts.filter((c): c is DatedContract => c.daily !== undefined);
}

/**
 * 個股頁:契約裡帶旗標的那些。**不依股票去重**,1565 的 MYF 與 OMF
 * 同一天都舉旗時兩個都要出現(§7.10)。
 */
export type FlaggedContract = FuturesContract & { anomaly: FuturesAnomaly };

export function flaggedContracts(contracts: FuturesContract[]): FlaggedContract[] {
  return contracts.filter((c): c is FlaggedContract => c.anomaly !== undefined);
}

/**
 * 個股頁:契約裡**沒有** `daily` 的那些(docs/38 §7.15)。
 *
 * 在此之前這種契約在畫面上什麼都沒有,而「什麼都沒有」與「這個功能還沒上線」
 * 長得一模一樣。§7.7 允許一個「尚未公布」性質的狀態,條件是它的依據必須是
 * `daily` 這個鍵的有無(那個鍵本身就是三態的),不是 `anomaly` 的有無。
 */
export function contractsWithoutDaily(contracts: FuturesContract[]): FuturesContract[] {
  return contracts.filter((c) => c.daily === undefined);
}

/**
 * 沒有 `daily` 的那一句。**它只陳述缺席,不解釋缺席**。
 *
 * 不寫「未公布」「未上市」「匯入失敗」:R1 說一個缺席的列恰好有這三種不可分辨的
 * 成因,挑一個講出來就是替資料做了一個它支持不了的選擇。也不寫「正常」「無交易」
 * ——§7.7 明文禁止,那是一個沒人做過的主張。剩下講得出口的只有那一天沒有那一列
 * 這件事本身,所以這句話就只有那麼多。
 *
 * 日期是**期貨行情日**(`futures.daily_as_of`),不是本頁的資料日;拿不到那一天
 * 的時候整句話不存在(呼叫端不畫),因為「沒有列」一定要說是哪一天沒有列。
 */
export function noDailyRowText(code: string, dailyAsOf: string): string {
  return `${code} 在 ${dailyAsOf} 沒有列。`;
}

/* ------------------------------------------------------------------ *
 * 市場層級的未平倉方向計數(docs/38 §7.15)。
 *
 * **這一塊沒有經過 docs/38 §3 的 battery,而那不是疏漏。** §1 的旗標主張
 * 「這個旗標告訴你一些事」——一個**資訊性**主張,可以被否證,所以 §3 先拿它去
 * 否證。這裡的四個計數只說「今天有幾個契約的未平倉比前一個期貨交易日高」,
 * 沒有說那代表什麼、也沒有說今天算不算不尋常,沒有東西可以被否證,也就沒有
 * 東西需要被檢定。豁免只在它保持描述性的時候成立,所以這裡的函式:
 *   - 只複述 payload 裡的四個整數,不算比率、不算淨額、不給總數(加法讀者自己做);
 *   - 不下任何判語(沒有「偏多」「偏空」「今天不尋常」);
 *   - 不排名任何契約(§5),連契約代碼都不出現。
 * ------------------------------------------------------------------ */

/**
 * 三態,與這個切片其他每一個鍵同一個約定:缺鍵 = 沒有算過(沒有期貨行情日),
 * 有鍵 = 數過了——**即使四個數字全是 0**。把兩者塌成一種表示,就是把「不知道」
 * 講成「今天一個契約都沒動」。
 */
export type FuturesOpenInterestDirectionState =
  | { kind: "not-computed" }
  | { kind: "counted"; counts: FuturesOpenInterestDirection };

export function futuresOpenInterestDirectionState(
  direction: FuturesOpenInterestDirection | null | undefined,
): FuturesOpenInterestDirectionState {
  if (!direction) return { kind: "not-computed" };
  return { kind: "counted", counts: direction };
}

/**
 * 那一句話。四個計數與它們比的是哪一天,句號結束——後面**不接**任何一句解讀。
 *
 * 「無法判定」那一項即使是 0 也照樣講:它與另外三項一樣是一個計數,而讀者要能
 * 看出今天有多少契約根本沒有答案。省略它會讓另外三個數字讀起來像是一個涵蓋全體
 * 的事實。成因不分類(R1:未掛牌 / 未公布 / 匯入失敗三者不可分辨)。
 */
export function openInterestDirectionText(c: FuturesOpenInterestDirection): string {
  return (
    `期貨 ${c.as_of} 未平倉較前一個期貨交易日:` +
    `增加 ${c.increased} 個契約、減少 ${c.decreased} 個、` +
    `持平 ${c.unchanged} 個、無法判定 ${c.undetermined} 個。`
  );
}
