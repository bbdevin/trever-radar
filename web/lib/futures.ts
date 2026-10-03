import type {
  FuturesAnomaly,
  FuturesAnomalyHistoryDay,
  FuturesAnomalyHistoryEntry,
  FuturesAnomalyHistoryMeta,
  FuturesContract,
  FuturesSpotAfter,
  FuturesDaily,
  FuturesInfo,
  FuturesOpenInterestDirection,
  FuturesVolumeAnomalyEntry,
  FuturesVolumeAnomalyMeta,
  ReasonItem,
  StockFuturesAnomalyHistory,
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
  /** 卡片空間小時用的短標籤(§7.17);守同樣的規則——不寫「今日」、天數來自區塊。 */
  short?: string;
  value: string;
  unit: string;
  /** 有正負意義的列(未平倉增減)帶原數字,畫面用來上紅增綠減;其餘列沒有。 */
  signed?: number;
}

export function anomalyFacts(a: FuturesAnomaly): FuturesAnomalyFact[] {
  const days = fmtLotsAbs(a.window_days);
  const facts: FuturesAnomalyFact[] = [
    // 「今日」不可以出現在這裡:這一列講的是期貨行情日,而那一天通常不是使用者
    // 眼前的今天(§7.12)。日期由外面的標題講,標籤只講它是什麼數字。
    { key: "today", label: "一般時段成交", short: "成交", value: fmtLotsAbs(a.today), unit: "口" },
    { key: "window_max", label: `前 ${days} 個比較日最高`, short: `前 ${days} 日最高`, value: fmtLotsAbs(a.window_max), unit: "口" },
    { key: "window_median", label: `前 ${days} 個比較日中位數`, short: `前 ${days} 日中位`, value: fmtLotsAbs(a.window_median), unit: "口" },
  ];
  // 缺鍵就是缺鍵:不補 0、不補破折號、不加一句「未公布」(§7.1)。
  if (a.oi_change !== undefined) {
    facts.push({ key: "oi_change", label: "未平倉較前日", short: "未平倉增減", value: fmtLotsSigned(a.oi_change), unit: "口", signed: a.oi_change });
  }
  return facts;
}

/* ------------------------------------------------------------------ *
 * 契約的白話名稱(docs/38 §7.19,2026-10-03)。使用者原話:「期貨的英文看不懂
 * 什麼 REF JFF 這些縮寫都要寫清楚是什麼 不然就不要寫」。畫面上一律不顯示
 * 契約代碼,只顯示這個名稱(代碼最多放在 title 裡)。同一檔股票的兩個契約
 * (1565 的 MYF 2,000 股/口與 OMF 100 股/口)名稱必須分得開(§7.10)。
 * 規則與 pipeline 的 `futures_digest.contract_label` 相同。
 * ------------------------------------------------------------------ */
export function contractLabel(multiplier: number | null | undefined, stockId: string): string {
  // ETF 是縮寫,依使用者規則不能裸寫;「ETF(指數股票型基金)期貨」在 390px 的卡片
  // 標籤放不下,所以用「指數基金期貨」,完整名稱放在 title(見 contractLabelTitle)。
  if (stockId.startsWith("00")) return ETF_FUTURES_LABEL;
  if (multiplier === 2000) return "個股期貨";
  if (multiplier === 100) return "小型個股期貨";
  if (typeof multiplier === "number") return `期貨（每口 ${multiplier.toLocaleString("zh-TW")} 股）`;
  return "期貨";
}

export const ETF_FUTURES_LABEL = "指數基金期貨";

/** 標籤的滑鼠提示:代碼只放在這裡;指數基金期貨另外寫出 ETF 的全名。 */
export function contractLabelTitle(label: string, code: string): string {
  return label.startsWith(ETF_FUTURES_LABEL)
    ? `ETF（指數股票型基金）期貨，契約代碼 ${code}`
    : `契約代碼 ${code}`;
}

/**
 * 一檔股票的每個契約 → 名稱,**保證兩兩不同**。同名時先補「每口幾股」;
 * 乘數未知(舊 payload)或補了仍同名,再補「第 N 個契約」——絕不讓兩個契約
 * 在畫面上長得一樣(§7.10)。
 */
export function contractLabelsByCode(
  contracts: ReadonlyArray<{ code: string; multiplier?: number }>,
  stockId: string,
): Map<string, string> {
  const unique = new Map<string, { code: string; multiplier?: number }>();
  for (const c of contracts) if (!unique.has(c.code)) unique.set(c.code, c);
  const list = [...unique.values()];
  const count = (labels: string[]) => {
    const m = new Map<string, number>();
    for (const l of labels) m.set(l, (m.get(l) ?? 0) + 1);
    return m;
  };
  let labels = list.map((c) => contractLabel(c.multiplier, stockId));
  let counts = count(labels);
  labels = labels.map((label, i) => {
    const m = list[i].multiplier;
    return (counts.get(label) ?? 0) > 1 && typeof m === "number" && !label.includes("每口")
      ? `${label}（每口 ${m.toLocaleString("zh-TW")} 股）`
      : label;
  });
  counts = count(labels);
  const seen = new Map<string, number>();
  labels = labels.map((label) => {
    if ((counts.get(label) ?? 0) <= 1) return label;
    const n = (seen.get(label) ?? 0) + 1;
    seen.set(label, n);
    return `${label}（第 ${n} 個契約）`;
  });
  return new Map(list.map((c, i) => [c.code, labels[i]]));
}

/**
 * 一份名單(可能跨很多檔股票、很多天)裡每一筆的名稱:**依股票**把出現過的契約
 * 收在一起去重,所以同一檔的兩個契約在名單、紀錄、推播裡都分得開。鍵 `${stock}|${code}`。
 */
export function entryContractLabels(
  entries: ReadonlyArray<{ stock_id: string; code: string; multiplier?: number }>,
): Map<string, string> {
  const byStock = new Map<string, { code: string; multiplier?: number }[]>();
  for (const e of entries) {
    const list = byStock.get(e.stock_id) ?? [];
    list.push({ code: e.code, multiplier: e.multiplier });
    byStock.set(e.stock_id, list);
  }
  const out = new Map<string, string>();
  byStock.forEach((list, stockId) => {
    contractLabelsByCode(list, stockId).forEach((label, code) => out.set(`${stockId}|${code}`, label));
  });
  return out;
}

/** 名單上的一列。刻意沒有 rank / position / score / ratio 這類鍵(§5、§7.5)。 */
export interface FuturesAnomalyRow {
  stockId: string;
  /** 解析不到股名時為 null——顯示 id 本身,不編一個標籤出來。 */
  name: string | null;
  code: string;
  /** 契約的白話名稱(§7.19);畫面上顯示這個,不顯示 `code`。 */
  label: string;
  facts: FuturesAnomalyFact[];
  reasons: ReasonItem[];
  risks: ReasonItem[];
  /** 現貨當日有沒有同步創高(§7.17)。舊 payload 沒有這個鍵 → unknown。 */
  spot: SpotFollow;
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
  const labels = entryContractLabels(entries);
  const rows = entries.map((e) => ({
    stockId: e.stock_id,
    name: nameById?.get(e.stock_id) ?? null,
    code: e.code,
    label: labels.get(`${e.stock_id}|${e.code}`) ?? contractLabel(e.multiplier, e.stock_id),
    facts: anomalyFacts(e.anomaly),
    reasons: e.reasons,
    risks: e.risks,
    spot: spotFollow(e.spot_new_high),
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
  /** 同 FuturesAnomalyFact.signed:只有未平倉增減帶,畫面上紅增綠減。 */
  signed?: number;
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
    facts.push({ key: "oi_change", label: "未平倉較前日", value: fmtLotsSigned(daily.oi_change), unit: "口", signed: daily.oi_change });
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
/* ------------------------------------------------------------------ *
 * 個股頁的「期貨」分頁(2026-09-30,docs/38 §7.16)。
 *
 * 期貨資訊原本直接攤在個股頁標頭與 K 線上方,使用者覺得擾人。改成一個分頁,
 * 只在這檔股票**確實有個股期貨**時出現;標頭只在當天真的舉旗時才放一顆按鈕
 * ——那是整個期貨切片唯一通過事前檢定的訊號,出現的日子很少,值得打斷。
 * ------------------------------------------------------------------ */

/** 分頁要不要出現、標頭要不要放按鈕。unknown / none 都不出現分頁。 */
export function stockFuturesTab(futures: FuturesInfo | null | undefined): {
  show: boolean;
  flaggedCodes: string[];
} {
  const state = futuresState(futures);
  if (state.kind !== "has") return { show: false, flaggedCodes: [] };
  return { show: true, flaggedCodes: flaggedContracts(state.contracts).map((c) => c.code) };
}

/**
 * docs/38 第 1 次檢定的結果(`docs/evidence/futures-volume-battery-20260921.json`)。
 * 這是一份**已凍結的歷史紀錄**,不是每天重算的數字——所以寫死在這裡,並把出處
 * 與截止日一起講出來。之後若依 §3.5 重跑,這裡要跟著換成新的那一次。
 */
export const ANOMALY_EVIDENCE = {
  asOf: "2026-09-17",
  tradingDays: 250,
  forwardDays: 5,
  windowDays: 60,
  events: 680,
  hits: 141,
  placeboMin: 43,
  placeboMax: 67,
} as const;

/**
 * 「這個訊號歷史上代表什麼」——給想拿它做決策的人的那一句實話。
 *
 * 只講檢定**實際證明**的東西:期貨量先創高、而**當天現貨量還沒創高**之後,
 * 現貨量在 5 個交易日內跟著創高的次數,明顯多於同一批股票的平常日子。它講的是
 * **量會跟上**,不是價格方向;檢定從來沒有測過漲跌,所以句子明講這一點。
 * 次數與基準一起給,除法由人做(docs/38 §1)。
 */
export function anomalyMeaningText(e: typeof ANOMALY_EVIDENCE = ANOMALY_EVIDENCE): string {
  return (
    `回測(至 ${e.asOf},${e.tradingDays} 個期貨交易日):期貨量創 ${e.windowDays} 日新高、` +
    `而當天現貨量還沒創新高的情況共 ${e.events} 次,之後 ${e.forwardDays} 個交易日內` +
    `現貨量也創 ${e.windowDays} 日新高的有 ${e.hits} 次;同一批股票平常的日子等量抽樣 10 組,` +
    `只有 ${e.placeboMin}–${e.placeboMax} 次。` +
    "它預告的是「現貨量會跟上」,不是漲或跌——方向要搭配籌碼與價格自己判斷。"
  );
}

export function openInterestDirectionText(c: FuturesOpenInterestDirection): string {
  return (
    `期貨 ${c.as_of} 未平倉較前一個期貨交易日:` +
    `增加 ${c.increased} 個契約、減少 ${c.decreased} 個、` +
    `持平 ${c.unchanged} 個、無法判定 ${c.undetermined} 個。`
  );
}

/* ------------------------------------------------------------------ *
 * 現貨有沒有跟上(docs/38 §7.17,2026-10-02)。
 *
 * 檢定 B 證明的是 F_only:期貨量創新高、而**當天現貨量還沒創新高**之後,現貨量
 * 在 5 個交易日內跟著創高的次數明顯多於平常日子。現貨當天已經同步爆量的那一種
 * 不在檢定裡——它比較像同一個消息的兩個回聲,不是期貨在「預告」。所以這是讀
 * 每一個旗標時最重要的一個位元,畫面上要先講它。
 * ------------------------------------------------------------------ */
export type SpotFollow = "lagging" | "followed" | "unknown";

export function spotFollow(spotNewHigh: boolean | null | undefined): SpotFollow {
  if (spotNewHigh === false) return "lagging";
  if (spotNewHigh === true) return "followed";
  return "unknown";
}

/**
 * 卡片上的標籤;unknown 不貼標籤(不知道就不講)。
 * `when: "flag"` 給近 N 日紀錄用:那是**舉旗當天**的狀態,不是現在——用現在式
 * 會與同一張卡上「現貨量 09-30 跟上」互相矛盾(§7.19)。
 */
export function spotFollowLabel(s: SpotFollow, when: "now" | "flag" = "now"): string | null {
  if (when === "flag") {
    if (s === "lagging") return "舉旗時現貨未跟上";
    if (s === "followed") return "舉旗時現貨同步爆量";
    return null;
  }
  if (s === "lagging") return "現貨尚未跟上";
  if (s === "followed") return "現貨已同步爆量";
  return null;
}

/**
 * 依檢定條件分組:現貨尚未跟上(符合檢定)→ 無法判定 → 現貨已同步爆量。
 * **組內維持 payload 原本的順序**——這是分組,不是名次(§5 不做跨契約排名)。
 */
export function groupBySpotFollow<T extends { spot: SpotFollow }>(rows: T[]): T[] {
  const order: SpotFollow[] = ["lagging", "unknown", "followed"];
  return order.flatMap((s) => rows.filter((r) => r.spot === s));
}

/* ------------------------------------------------------------------ *
 * 近 N 個期貨交易日的舉旗紀錄(docs/38 §7.19,2026-10-03,post-data,只動呈現)。
 *
 * 每一天都是用今天的資料重算的(規則本人,不是另一條),不是「那一天頁面上顯示
 * 的東西」——說明句講明這件事。「現貨量跟上」是檢定 B 驗證過的那個問題;價格
 * 只是事後紀錄,不是預測:docs/40 量過,這個訊號之後第二個交易日的漲跌兩邊都有,
 * 而且跌 ≥3% 比漲 ≥3% 還多。所以:
 *   - 不依任何價格排序,順序照 payload(日期新到舊、日內照當日名單順序);
 *   - 永遠同時講最高與最低;
 *   - 價格的 % 只在 `priceAfterText` 這一個純函式裡出現;
 *   - 顏色中性(不用紅綠)。
 * ------------------------------------------------------------------ */

/**
 * docs/40 第 1 次執行(`docs/evidence/next-day-futures-signal-battery-20261002.json`,
 * `companion.signal` 與 `placebo_counts` 的 20 組)。已凍結的歷史紀錄,寫死在這裡並
 * 附出處;重跑後要跟著換。pipeline 的 `futures_digest.NEXT_DAY_EVIDENCE` 是同一份。
 */
export const NEXT_DAY_EVIDENCE = {
  source: "docs/evidence/next-day-futures-signal-battery-20261002.json",
  asOf: "2026-09-30",
  events: 551,
  up3: 81,
  down3: 112,
  placeboUpMin: 54,
  placeboUpMax: 77,
  placeboDownMin: 64,
  placeboDownMax: 97,
} as const;

/** 「怎麼看」的說明(文字由測試逐字鎖住)。天數全部讀 meta,不寫死。 */
export function anomalyHistoryHeaderText(
  meta: Pick<FuturesAnomalyHistoryMeta, "forward_days" | "window_days">,
  days: ReadonlyArray<{ as_of: string }>,
  e: typeof NEXT_DAY_EVIDENCE = NEXT_DAY_EVIDENCE,
): string {
  const range = days.length > 0
    ? `（${days[days.length - 1].as_of.slice(5)}–${days[0].as_of.slice(5)}）`
    : "";
  return (
    `近 ${days.length} 個期貨交易日${range}的舉旗紀錄，以今天的資料重算。` +
    `每筆的「現貨量跟上」只看之後 ${meta.forward_days} 個交易日內現貨量有沒有創 ` +
    `${meta.window_days} 日新高——這是回測驗證過的事。它不預告漲跌：回測 ${e.events} 次訊號，` +
    `第二個交易日漲 ≥3% 有 ${e.up3} 次、跌 ≥3% 有 ${e.down3} 次，平常日子抽樣為漲 ` +
    `${e.placeboUpMin}–${e.placeboUpMax}、跌 ${e.placeboDownMin}–${e.placeboDownMax} 次。`
  );
}

/** 價格區塊的標題(逐字鎖)。 */
export const PRICE_AFTER_HEADING = "之後走勢（事後紀錄，不是預測；量的檢定沒測過漲跌）";

/** 價格區塊下的那句回測(逐字鎖)。 */
export function nextDayEvidenceText(e: typeof NEXT_DAY_EVIDENCE = NEXT_DAY_EVIDENCE): string {
  return (
    `回測 ${e.events} 次：第二個交易日漲 ≥3% ${e.up3} 次、跌 ≥3% ${e.down3} 次；` +
    `平常日子 ${e.placeboUpMin}–${e.placeboUpMax} / ${e.placeboDownMin}–${e.placeboDownMax} 次。` +
    "它預告的是波動，不是上漲。"
  );
}

/** 舉旗之後「現貨量有沒有跟上」的四種狀態(三態的 null 依天數再分兩種)。 */
export type FollowStatus =
  | { kind: "followed"; on: string | null }
  | { kind: "missed" }
  | { kind: "watching"; observed: number }
  | { kind: "unknown" };

export function followStatus(
  e: Pick<FuturesAnomalyHistoryEntry, "spot_followed" | "spot_followed_on" | "forward_days_observed">,
  forwardDays: number,
): FollowStatus {
  if (e.spot_followed === true) return { kind: "followed", on: e.spot_followed_on ?? null };
  if (e.spot_followed === false) return { kind: "missed" };
  if (e.forward_days_observed < forwardDays) return { kind: "watching", observed: e.forward_days_observed };
  return { kind: "unknown" };
}

/** 狀態標籤。天數讀 meta(不寫死 5);不說「還沒噴」「尚未發動」——那是在預告價格。 */
export function followStatusLabel(s: FollowStatus, forwardDays: number): string {
  if (s.kind === "followed") return s.on ? `現貨量 ${s.on.slice(5)} 跟上` : "現貨量已跟上";
  if (s.kind === "missed") return `${forwardDays} 日內現貨量未跟上`;
  if (s.kind === "watching") return `觀察中（${s.observed}/${forwardDays} 日）`;
  return "無法判定";
}

function fmtPrice(n: number): string {
  return n.toLocaleString("zh-TW", { minimumFractionDigits: 1, maximumFractionDigits: 2 });
}

/** 相對舉旗日收盤的變化,一位小數;負號用「−」。這是整個期貨表面唯一算 % 的地方。 */
function fmtPctFrom(base: number, v: number): string {
  const pct = (v / base - 1) * 100;
  const abs = Math.abs(pct).toFixed(1);
  if (abs === "0.0") return "0.0%";
  return `${pct > 0 ? "+" : "−"}${abs}%`;
}

/**
 * 舉旗之後的現貨價格一句話。缺 → 「—」;之後還沒有交易日 → 「尚無之後交易日」。
 * 最高與最低**永遠一起**給(這個訊號預告的是波動)。
 *
 * **每一句都標「未扣除權息」**:production 的日 K 沒有可靠的除權息訊號——
 * `adj_factor` 只有手動跑 compute-adjustments 才會更新(不在排程裡),新列一律 1.0,
 * 而 daily_prices 不存漲跌價/參考價、也沒有除權息日表。所以除權息當天的缺口會被
 * 算成真的跌幅,而我們偵測不到;誠實的作法是每一句都講明沒扣。`ex_rights` 為真
 * (偵測得到的少數情況)時改講得更確定:「窗內有除權息」。
 */
export function priceAfterText(after: FuturesSpotAfter | undefined): string {
  if (!after) return "—";
  if (after.days === 0 || after.last_close === undefined) return "尚無之後交易日";
  const base = after.flag_close;
  const high = after.high ?? after.last_close;
  const low = after.low ?? after.last_close;
  return (
    `現貨收盤 ${fmtPrice(base)} → ${fmtPrice(after.last_close)}` +
    `（${fmtPctFrom(base, after.last_close)}，${after.days} 個交易日後）；` +
    `期間最高 ${fmtPctFrom(base, high)}／最低 ${fmtPctFrom(base, low)}` +
    (after.ex_rights ? "（窗內有除權息，未扣除）" : "（未扣除權息）")
  );
}

/**
 * 「目前高於 / 低於 / 持平舉旗日收盤」的計數(不是比率)。單位是「檔」:同一天同一檔
 * 的兩個契約參考的是同一個現貨收盤,只數一次;不同天舉旗各自一個參考點,各數一次。
 * 只數舉旗後至少有 1 個交易日的。
 */
export function priceAfterCounts(days: ReadonlyArray<FuturesAnomalyHistoryDay>): {
  higher: number;
  lower: number;
  flat: number;
} {
  const seen = new Set<string>();
  const counts = { higher: 0, lower: 0, flat: 0 };
  for (const day of days) {
    for (const e of day.entries ?? []) {
      const a = e.spot_after;
      if (!a || a.days < 1 || a.last_close === undefined) continue;
      const key = `${day.as_of}|${e.stock_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (a.last_close > a.flag_close) counts.higher += 1;
      else if (a.last_close < a.flag_close) counts.lower += 1;
      else counts.flat += 1;
    }
  }
  return counts;
}

export function priceAfterCountsText(c: { higher: number; lower: number; flat: number }): string {
  return `目前高於舉旗日收盤 ${c.higher} 檔、低於 ${c.lower} 檔、持平 ${c.flat} 檔（含舉旗後至少 1 個交易日者）`;
}

export interface FuturesHistoryRow extends FuturesAnomalyRow {
  follow: FollowStatus;
  followLabel: string;
  priceAfter: string;
}

export type FuturesAnomalyHistoryState =
  | { kind: "not-computed" }
  | {
      kind: "listed";
      meta: FuturesAnomalyHistoryMeta;
      /** 新到舊,照 payload。`computed: false` = 那一天規則答不出來(不主張)。 */
      days: { asOf: string; computed: boolean; rows: FuturesHistoryRow[] }[];
    };

export function futuresAnomalyHistoryState(
  history: FuturesAnomalyHistoryDay[] | null | undefined,
  meta: FuturesAnomalyHistoryMeta | null | undefined,
  nameById?: ReadonlyMap<string, string>,
): FuturesAnomalyHistoryState {
  if (!history || !meta) return { kind: "not-computed" };
  // 名稱依股票跨整份紀錄去重:同一檔的兩個契約在不同天出現也叫不同的名字。
  const labels = entryContractLabels(history.flatMap((d) => d.entries ?? []));
  return {
    kind: "listed",
    meta,
    days: history.map((day) => ({
      asOf: day.as_of,
      computed: day.entries !== undefined,
      // 順序原封不動:不依價格、不依狀態重排,也不合併同一個契約的多次舉旗。
      rows: (day.entries ?? []).map((e) => {
        const follow = followStatus(e, meta.forward_days);
        return {
          stockId: e.stock_id,
          name: nameById?.get(e.stock_id) ?? null,
          code: e.code,
          label: labels.get(`${e.stock_id}|${e.code}`) ?? contractLabel(e.multiplier, e.stock_id),
          facts: anomalyFacts(e.anomaly),
          reasons: e.reasons,
          risks: e.risks,
          spot: spotFollow(e.spot_new_high),
          follow,
          followLabel: followStatusLabel(follow, meta.forward_days),
          priceAfter: priceAfterText(e.spot_after),
        };
      }),
    })),
  };
}

/* ------------------------------------------------------------------ *
 * 個股頁的近 N 日舉旗紀錄(docs/38 §7.20,2026-10-03,post-data,只動呈現)。
 *
 * payload 是 radar.json 那一份只留這一檔的條目(`futures.anomaly_history`),所以
 * 判斷直接沿用 `futuresAnomalyHistoryState`,只是:
 *   - 契約名稱改用這一檔**全部契約**的名稱表(與同一頁其他區塊叫同一個名字);
 *   - 多帶兩個計數(舉旗次數、沒算出結果的天數),空狀態的句子由它們決定。
 * 「這檔沒有舉旗」只在**有算過**的日子才講得出口:鍵缺 = 沒算過(不主張);
 * 那天缺 `entries` = 那天規則答不出來,不算進「沒有舉旗」。
 * ------------------------------------------------------------------ */
export type StockAnomalyHistoryState =
  | { kind: "not-computed" }
  | {
      kind: "listed";
      meta: FuturesAnomalyHistoryMeta;
      days: { asOf: string; computed: boolean; rows: FuturesHistoryRow[] }[];
      /** 舉旗筆數(契約-日,不合併)。 */
      total: number;
      /** 規則答不出來的那幾天(新到舊)。 */
      uncomputed: string[];
    };

export function stockAnomalyHistoryState(
  history: StockFuturesAnomalyHistory | null | undefined,
  labels?: ReadonlyMap<string, string>,
): StockAnomalyHistoryState {
  const base = futuresAnomalyHistoryState(history?.days, history?.meta);
  if (base.kind === "not-computed") return base;
  const days = base.days.map((d) => ({
    ...d,
    rows: d.rows.map((r) => ({ ...r, label: labels?.get(r.code) ?? r.label })),
  }));
  return {
    kind: "listed",
    meta: base.meta,
    days,
    total: days.reduce((n, d) => n + d.rows.length, 0),
    uncomputed: days.filter((d) => !d.computed).map((d) => d.asOf),
  };
}

/** 紀錄的一句摘要(次數,不是比率)。天數讀 payload 的天數,不寫死 10。 */
export function stockAnomalyHistorySummaryText(
  s: Extract<StockAnomalyHistoryState, { kind: "listed" }>,
): string {
  const n = s.days.length;
  const u = s.uncomputed.length;
  if (n === 0) return "沒有可看的期貨交易日。";
  if (u === n) return `近 ${n} 個期貨交易日都沒有算出結果。這不代表沒有舉旗。`;
  const missing = u > 0 ? `；另 ${u} 天沒有算出結果` : "";
  if (s.total === 0) {
    return u > 0
      ? `近 ${n} 個期貨交易日中，算出結果的 ${n - u} 天這檔都沒有舉旗${missing}。`
      : `近 ${n} 個期貨交易日這檔沒有舉旗。`;
  }
  return `近 ${n} 個期貨交易日舉旗 ${s.total} 次${missing}。`;
}

/** 個股紀錄下方的一行說明:重算的事實與「跟上」的定義。天數全部讀 meta。 */
export function stockAnomalyHistoryNoteText(
  meta: Pick<FuturesAnomalyHistoryMeta, "forward_days" | "window_days">,
): string {
  return (
    `以今天的資料重算。「現貨量跟上」= 之後 ${meta.forward_days} 個交易日內` +
    `現貨量創 ${meta.window_days} 日新高；價格是事後紀錄，未扣除權息。`
  );
}

/** 個股頁「回測依據」摺疊列的那一行(不帶數字;數字都在展開後的凍結常數句子裡)。 */
export const EVIDENCE_SUMMARY = "回測依據：預告的是現貨量與波動，不是漲跌";

/** 首頁期貨分頁「當日｜近 N 日」的記憶值;讀不懂就回預設「當日」。 */
export type FuturesView = "today" | "history";
export const FUTURES_VIEW_KEY = "trever.home.futuresView.v1";
export function parseFuturesView(raw: string | null | undefined): FuturesView {
  return raw === "history" ? "history" : "today";
}