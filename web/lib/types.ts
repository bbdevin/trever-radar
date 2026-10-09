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

/** 個股 `price_levels`(docs/45 §3,export `compute/price_levels.py`)。價格皆為還原到資料日基準的價。 */
export interface PriceLevelPoint {
  p: number;
  t: string;
}
export interface PriceLevelZone {
  lo: number;
  hi: number;
  /** 該格成交量 ÷ 視窗總量 */
  share: number;
}
/** 未回補缺口(docs/45 F9,version ≥2):還原價 lo–hi,t = 跳空那天 */
export interface PriceLevelGap {
  lo: number;
  hi: number;
  t: string;
}
/** 收盤相對 20 日線的連續天數(docs/45 F11,version ≥2);capped = 可算的 K 棒全同向,真實天數只多不少 */
export interface Ma20Streak {
  n: number;
  side: "above" | "below";
  capped: boolean;
}
export type PriceLevels =
  | { version: number; status: "insufficient"; as_of: string; bars: number }
  | {
      version: number;
      status: "ok";
      as_of: string;
      bars: number;
      close: number;
      ma: Partial<Record<"5" | "10" | "20" | "60" | "120" | "240", number | null>>;
      ma_align: "bull" | "bear" | null;
      highs: Partial<Record<"20" | "60" | "120" | "240", PriceLevelPoint | null>>;
      lows: Partial<Record<"20" | "60" | "120" | "240", PriceLevelPoint | null>>;
      new_high_20: boolean;
      new_low_20: boolean;
      vol_price_2d: "up" | "down" | null;
      vol_profile: { window: number; above: number; below: number; at: number } | null;
      dense_above: PriceLevelZone | null;
      dense_below: PriceLevelZone | null;
      /** version 1 的舊 JSON 沒有這三個鍵:缺口改由前端 K 棒自算(只進壓力段),連續天數不列 */
      gaps_above?: PriceLevelGap[] | null;
      gaps_below?: PriceLevelGap[] | null;
      ma20_streak?: Ma20Streak | null;
    };

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

export interface PocketTag {
  code: string;
  // "KEY" kept for payloads exported before the K1→T1 rename (docs/27); drop once
  // no shipped JSON predates it. New payloads emit "TRACKED".
  family: "GEO" | "KEY" | "TRACKED" | "THEME" | "BUYBACK";
  text: string;
  strength?: "weak" | "strong";
  branches?: string[];
  themes?: string[];
}

/** Official company basic data; absent on JSON snapshots exported before docs/37 B. */
export interface CompanyProfile {
  stock_id: string;
  address: string | null;
  city: string | null;
  district: string | null;
  market: "twse" | "tpex";
  industry_code: string | null;
  transfer_agent: string | null;
  transfer_agent_phone: string | null;
  transfer_agent_address: string | null;
  source: string | null;
  source_updated_at: string | null;
  updated_at: string;
}

/** Official MOPS t35sc09 fact.  It is present only for a plan active on the export date. */
export interface Buyback {
  plan_id: string;
  stock_id: string;
  name: string;
  market: "twse" | "tpex";
  board_date: string | null;
  purpose: string | null;
  total_amount_limit: number | null;
  planned_shares: number | null; // 股
  price_min: number | null; // 元/股
  price_max: number | null; // 元/股
  start_date: string | null;
  end_date: string | null;
  completed_flag: string | null;
  status: "in_progress";
  executed_shares: number | null; // 股
  transferred_shares: number | null; // 股
  execution_pct: number | null; // 百分點
  executed_amount: number | null; // 元
  avg_price: number | null; // 元/股
  share_ratio_pct: number | null; // 百分點
  incomplete_reason: string | null;
  report_date: string | null;
  source_updated_at: string | null;
  source: string;
}

/** Versioned repo mapping membership; does not imply a score or recommendation. */
export interface CompanyGroupMembership {
  id: string;
  name: string;
  source: string;
  source_updated_at: string | null;
  observed_at: string;
}

export interface CompanyGroupMember {
  id: string;
  name: string | null;
  market: "twse" | "tpex" | null;
  industry: string | null;
  quote_date: string | null;
  close: number | null;
  turnover: number | null;
  chg_pct: number | null;
  effective_from: string | null;
  effective_to: string | null;
}

export interface CompanyGroup {
  id: string;
  name: string;
  source: string;
  source_updated_at: string | null;
  observed_at: string;
  members: CompanyGroupMember[];
}

/** Additive company classification; `status` is null for legacy DB exports. */
export interface CompanyTheme {
  id: string;
  name: string;
  source: string | null;
  source_updated_at: string | null;
  data_date: string | null;
  status: "active" | "stale" | "retired" | null;
}

/** Current-market heat joined to a company classification; never a causal claim. */
export interface RecentThemeHeat {
  id: string;
  name: string;
  status: "active" | "stale" | "retired" | null;
  data_date: string | null;
  heat_date: string | null;
  vs20: number | null;
  avg_chg: number | null;
  turnover: number;
  up: number;
  down: number;
  eligible: boolean;
}

export interface CompanyGroupsJson {
  version: number;
  data_date: string;
  generated_at: string;
  groups: CompanyGroup[];
}

/**
 * 股代的一段:from = 首次觀察日(還沒有歷史時為 null)、to = 下一段的 from(最新一段 null);
 * broker null = 銀行或自辦。
 */
export interface BranchAgentPeriod {
  broker: string | null;
  from: string | null;
  to: string | null;
  /** 此股 payload 裡、該段股代券商的總公司席位名稱。 */
  names: string[];
}

/**
 * 籌碼日報分點標籤的原始事實(json_export `_branch_tags_payload`)。
 * 名字只限此股 payload 會出現的分點;鍵永遠存在,沒有就是空清單。
 */
export interface BranchTags {
  /** 資料日(與籌碼日相同)。 */
  as_of: string;
  /** rule:雙北同區 "district"、其他同縣市 "city";公司地址判不了為 null。 */
  geo: { rule: "district" | "city" | null; names: string[] };
  /**
   * 股代(docs/37 §3.1):股務代理是券商時,該券商的總公司席位。current = 現在;
   * periods 舊→新,換過股代才有多段(日期 d 用 from ≤ d 的最後一段,早於最早一段沿用最早)。
   * 舊 JSON 沒有這個鍵,缺鍵時不標;沒有 periods 時只用 current。
   */
  agent?: { current: { broker: string | null; names: string[] }; periods?: BranchAgentPeriod[] };
  /** 只收判定為隔日沖的配對;未判定(NULL)不輸出。rows 值為 [觀察數, 次日回吐數]。 */
  daytrade: {
    min_obs: number;
    rate: number;
    /** 次日賣出 ≥ 當日淨買的這個比例才算回吐。 */
    payback?: number;
    rows: Record<string, [number, number]>;
  };
  /** 追蹤名單(手動/自動入選 ∪ 排行高分非隔日沖),與口袋「追蹤分點同買」同一份。 */
  tracked: string[];
}

/** 區間損益(估算)的一列:一個分點在這檔股票、一個窗口內的平均成本法估算。NT$ 為整數。 */
export interface BranchPnlRow {
  name: string;
  est_total: number;
  realized: number;
  unrealized: number;
  pos_lots: number;
  avg_cost: number;
  last_close: number;
  buy_lots: number;
  sell_lots_attributed: number;
  sell_lots_unattributed: number;
  visible_days: number;
  max_cost: number;
  ret_pct: number | null;
  af_adjusted: boolean;
  first_date: string;
  last_date: string;
}

export interface BranchPnlWindow {
  window_days: number;
  first_date: string;
  pairs_considered: number;
  pairs_skipped_missing_price: number;
  /** 全部賺／賠的分點數(清單只留前 15);舊 payload 沒有時用清單長度。 */
  n_gainers?: number;
  n_losers?: number;
  gainers: BranchPnlRow[];
  losers: BranchPnlRow[];
}

export interface BranchPnlEst {
  as_of: string;
  definitions_version: string;
  windows: Partial<Record<"60" | "240" | "all", BranchPnlWindow>>;
}

export interface StockJson {
  id: string;
  name: string;
  market: "twse" | "tpex";
  /** Existing stock master industry label; may be absent from legacy JSON. */
  industry?: string | null;
  /** Additive official company profile; legacy JSON intentionally omits it. */
  company_profile?: CompanyProfile | null;
  /** Additive official MOPS fact; legacy snapshots intentionally omit it. */
  buyback?: Buyback | null;
  /** Additive, source-controlled group memberships; legacy JSON intentionally omits it. */
  company_groups?: CompanyGroupMembership[];
  /** Additive company classifications; absent from JSON snapshots exported before docs/37 C. */
  company_themes?: CompanyTheme[];
  /** Additive current heat candidates; absence is not evidence of no related theme. */
  recent_theme_heat?: RecentThemeHeat[];
  candles: Candle[];
  scores: ScoreBreakdown | null;
  reasons: string[];
  raw_reasons?: ReasonItem[]; // 帶 code 的原始理由(JSON 既有);前端用 code 前綴判語意家族色
  pocket_tags?: PocketTag[]; // docs/27 G2;不進綜合分
  pocket_score?: number;
  risks: string[];
  /** 帶 code 的完整風險項(docs/46;≤7)。舊 JSON 沒有 → 多空摘要用 risks 字串回推。 */
  raw_risks?: ReasonItem[];
  technical: TechnicalSummary | null;
  /** 價格位置事實(docs/45);舊 JSON 沒有此鍵,K 棒不足 20 根時 status = "insufficient"。只供顯示,不進任何分數。 */
  price_levels?: PriceLevels | null;
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
  /**
   * 每一對(分點, 個股)在固定窗口內的買/賣進出場價格分位計數。
   * 只有分子與分母,沒有旗標、分數或名次——這個性質量測到「傾向為真、標籤不可
   * 重現」,所以讀取端只能呈現次數與該股自身的同側比率,不得做成判定徽章
   * (籌碼日報的「買低 NN%／賣高 NN%」標籤只是同一個比率的文字,中性色、點開是分子分母)。
   * 舊版 JSON 沒有這個鍵;缺鍵時整節不渲染。
   */
  branch_pctile_counts?: BranchPctileCounts;
  /** 籌碼日報分點標籤(地緣/隔日沖/追蹤);舊 JSON 沒有這個鍵,缺鍵時不標。 */
  branch_tags?: BranchTags;
  /** 區間損益(估算,docs/42);舊 JSON 或這檔沒有分點列時缺鍵,分段不出現。 */
  branch_pnl_est?: BranchPnlEst;
  warrant: WarrantSummary | null;
  warrant_history: WarrantHistoryPoint[];
  active_warrants: ActiveWarrant[];
  /** 三大法人日買賣超(張);新→舊。下次 export-json 後才有 */
  insti_history?: {
    t: string;
    foreign: number;
    trust: number;
    dealer: number;
    total: number;
  }[];
  /** 資券日統計(張);新→舊。含融資成本估算(docs/34) */
  margin_history?: MarginHistoryPoint[];
  margin_meta?: MarginMeta;
  /** TDCC 大戶週序列(docs/34 B1/B2);新→舊 */
  holders_history?: HoldersHistoryPoint[];
  holders_meta?: HoldersMeta;
  /** 董監最新月明細(docs/34 §4.6 D1) */
  directors_latest?: DirectorsLatest | null;
  /**
   * 個股期貨標的存在事實(docs 個股期貨切片)。缺鍵 = 尚未 import-futures 過,
   * 「不知道」;有鍵但 contracts 是空陣列 = TAIFEX 完整官方清單截至
   * list_as_of 確實不含這檔,是一個正面主張,不是缺資料。兩者不得混同。
   */
  futures?: FuturesInfo;
  /**
   * 拆檔指標(docs/44 P1 §3.2):只出現在 `stocks/core/{id}.json`。有它代表 chips 四鍵在
   * `stocks/chips/{id}.json`、cut 以前的 K 線(若有)在 `hist` 指到的檔;舊單一檔沒有這個鍵。
   * 型別在 `lib/stockParts.ts`;接回後的 StockJson 沒有它。
   */
  parts?: import("./stockParts.ts").StockParts;
}

/** 個股期貨:存在與否的事實,外加(若當日已公布)原始量/未平倉,無比率無名次。 */
export interface FuturesInfo {
  version: number;
  /** 標的清單最後一次刷新日(TAIFEX 官方清單日),不是報價日。 */
  list_as_of: string;
  /**
   * 期貨**行情日**(docs/38 §7.12):這個區塊的 `daily` 與 `anomaly` 講的是哪一天。
   * 與 `list_as_of` 是兩件事(清單刷新日 vs 行情日),所以不叫裸的 `as_of`;
   * 與頁面的現貨資料日通常也差一個交易日,所以它必須自己帶著日期。
   * 缺鍵 = 一天期貨行情都還沒有,不是「未知的那一天」。
   */
  daily_as_of?: string;
  contracts: FuturesContract[];
  /** 近 N 日舉旗紀錄(docs/38 §7.20)。缺鍵 = 沒有算過,不是「沒有舉旗」。 */
  anomaly_history?: StockFuturesAnomalyHistory;
}

export interface FuturesContract {
  code: string;
  /** 契約乘數(股/口;docs/38 §7.19)。前端用它把代碼換成「個股期貨 / 小型個股期貨」。缺 = 未知。 */
  multiplier?: number;
  is_futures: boolean;
  is_option: boolean;
  is_weekly_option: boolean;
  /** 當日沒有列時整個省略,不可補 0——0 代表「沒人交易」,省略代表「還沒公布」。 */
  daily?: FuturesDaily;
  /**
   * 成交量異常旗標(docs/38 §1)。**沒有這個鍵有三種意思**——被 §2 否決、規則看過
   * 但沒創高、期貨還沒匯進來——而且刻意不可分辨,三者都不是一個異常。
   * **不得把任何一種標成「正常」**(§7.7)。
   */
  anomaly?: FuturesAnomaly;
  /** 與 `anomaly` 同生共死;沒有旗標就沒有這兩個鍵(§7.3)。 */
  reasons?: ReasonItem[];
  risks?: ReasonItem[];
  /** 與 `anomaly` 同生共死:現貨當日有沒有同步創高(§7.17)。舊 payload 沒有 → 無法判定。 */
  spot_new_high?: boolean | null;
}

/**
 * 個股頁的近 N 日舉旗紀錄(docs/38 §7.20)= radar.json 那一份只留這一檔的條目,
 * 不是另外算的。`days` 每一天的三態同市場那一份:`entries` 缺鍵 = 那一天規則答不出來;
 * `[]` = 算過、這一檔沒有舉旗。整個鍵缺 = 紀錄沒有算過。
 */
export interface StockFuturesAnomalyHistory {
  meta: FuturesAnomalyHistoryMeta;
  days: FuturesAnomalyHistoryDay[];
}

/**
 * 某一個契約在**期貨行情日**當天的原始事實。整數,沒有比率、名次、分數。
 *
 * `volume` 是**一般 + 盤後**兩時段之和,與只算一般時段(R3)的 `anomaly.today`
 * 是**不同的數字**,不得當成同一個顯示(docs/38 §7.6);各時段的口數另外列在
 * `session_volume` 裡,而且只列出**真的有列**的時段。
 *
 * 未平倉是**存量不是流量**:盤後列的來源是 '-'(NULL),所以它沒有時段之分,
 * `session_volume` 的拆分只適用於成交量。
 */
export interface FuturesDaily {
  date: string;
  volume: number | null;
  open_interest: number | null;
  session_volume: Record<string, number>;
  /**
   * 未平倉較**前一個期貨交易日**的變化(口)。與 `FuturesAnomaly.oi_change`
   * 同一個定義、同一個函式,只是這裡**每一個**契約-日都給,不只舉旗的那些。
   * 選填:任一邊為 NULL 時整個省略——缺鍵時**整列不顯示**,不是 0 也不是破折號
   * (§7.1)。`0` 本身是一個真的觀測(「一口都沒變」),必須顯示成 0。
   */
  oi_change?: number;
}

/** §1 表格的五個整數事實,一個不多。沒有比率、均值、名次、分數。 */
export interface FuturesAnomaly {
  /** 一般時段口數(R3;**不是** `daily.volume`)。 */
  today: number;
  window_max: number;
  window_median: number;
  /** 比較日天數。UI 顯示「N 個比較日」時讀這個,**不要在前端寫死 60**(§7.10)。 */
  window_days: number;
  /**
   * 選填:任一邊的未平倉為 NULL 時**整個省略**。缺鍵時**整列不顯示**——
   * 不是 0,也不是破折號(§7.1 / §7.4)。所以這個區塊是四個或五個鍵。
   */
  oi_change?: number;
}

/**
 * `radar.json` 的市場層級今日名單(docs/38 §7.5)。三態,與 `futures` 鍵同一個約定:
 * 缺鍵 = 今天沒有算過(期貨還沒跟上 export 日),沒有主張;空陣列 = 算過了、今天沒有
 * 契約舉旗,是一個有日期的正面主張;非空 = 今天舉旗的契約。**兩者不得混同。**
 *
 * 順序已由 pipeline 依 `today − window_max` 遞減(同分用 `code`)排好。
 * 這是**順序不是名次**:§5 不做跨契約排序,所以沒有 rank / position / score。
 * 單位是**契約**不是股票:1565 的 MYF/OMF 可以同一天都在名單裡,不得依股票去重。
 */
export interface FuturesVolumeAnomalyEntry {
  stock_id: string;
  code: string;
  /** 契約乘數(股/口;docs/38 §7.19)。舊 payload 沒有 → 標籤退回「期貨」。 */
  multiplier?: number;
  anomaly: FuturesAnomaly;
  reasons: ReasonItem[];
  risks: ReasonItem[];
  /** 現貨當日有沒有同步創高(docs/38 §7.17)。可選:舊 payload 沒有 → 無法判定。 */
  spot_new_high?: boolean | null;
  /**
   * 現貨股價與漲跌(docs/38 §7.21)。只出現在今日名單(radar.json / home/head.json);
   * 舊 payload、或現貨資料日沒有收盤 → 缺鍵,畫面不顯示股價。
   */
  spot_quote?: FuturesSpotQuote;
}

/**
 * 現貨資料日(= `data_date`,不是期貨行情日)的未還原收盤與漲跌%,與 `radar.stocks`
 * 的 close / chg_pct 同一個公式。前一日沒有收盤時 `chg_pct` 缺鍵。
 */
export interface FuturesSpotQuote {
  date: string;
  close: number;
  chg_pct?: number;
  /**
   * 只在前一日與當日之間偵測到除權息(`adj_factor` 變動)時出現,值恆為 true:
   * `chg_pct` 未扣除權息,含除權息缺口。缺鍵 = 沒偵測到,不代表沒有。
   */
  exdiv?: true;
}

/**
 * 舉旗之後的現貨價格,**原始觀測值**(docs/38 §7.19)。payload 裡沒有任何除法;
 * 百分比只由 `lib/futures.ts` 的 `priceAfterText` 算給人看。之後還沒有交易日時
 * 只有 `flag_close` 與 `days: 0`。價格未經還原,`ex_rights` 為真表示窗內有除權息。
 */
export interface FuturesSpotAfter {
  flag_close: number;
  days: number;
  last_close?: number;
  last_date?: string;
  high?: number;
  low?: number;
  ex_rights?: boolean;
}

/**
 * 近 N 個期貨交易日的舉旗紀錄裡的一筆(docs/38 §7.19)= 當日名單條目 + 事後欄位。
 * 每一天都是用**今天的資料重算**的,不是「那一天頁面上顯示的東西」。
 */
export interface FuturesAnomalyHistoryEntry extends FuturesVolumeAnomalyEntry {
  /** true = 往後 N 天內現貨量創新高;false = N 天都過去且都算得出來、沒有;null = 觀察中或無法判定。 */
  spot_followed: boolean | null;
  /** 只在 `spot_followed === true` 時出現:哪一天跟上。 */
  spot_followed_on?: string;
  /** 已經過去的往後現貨交易日數(0..forward_days)。 */
  forward_days_observed: number;
  /** 舉旗日沒有現貨價格列時缺鍵。 */
  spot_after?: FuturesSpotAfter;
}

/** 一天:`entries` 缺鍵 = 那一天規則答不出來(不主張);`[]` = 算過、沒有契約舉旗。 */
export interface FuturesAnomalyHistoryDay {
  as_of: string;
  entries?: FuturesAnomalyHistoryEntry[];
}

export interface FuturesAnomalyHistoryMeta {
  as_of: string;
  window_days: number;
  history_days: number;
  forward_days: number;
  /** 往後現貨看到哪一天(現貨資料日)。 */
  observed_through: string;
}

/**
 * 市場層級名單的隨附事實(docs/38 §7.11)。目前只有一個欄位,而且**不是**一個
 * 名次或評分的落腳處:§5 不做跨契約排序,這裡永遠不會長出 rank / score。
 */
export interface FuturesVolumeAnomalyMeta {
  /**
   * 這份名單講的是哪一天——期貨**行情日**,不是 `radar.json` 的 `data_date`
   * (docs/38 §7.12)。兩者常態差一個交易日。選填是為了舊 payload:
   * 讀不到就少講日期,不可以拿 `data_date` 頂替。
   */
  as_of?: string;
  /** 與 `FuturesAnomaly.window_days` 同一個常數;空名單那一態靠它講出比較窗口。 */
  window_days: number;
}

/**
 * 市場層級的未平倉方向計數(docs/38 §7.15)。**四個計數,沒有總數、沒有比率、
 * 沒有淨額、沒有旗標**——它是一句描述(今天有幾個契約的未平倉比前一個期貨交易日
 * 高),不是一個訊號,所以不需要也無從套用 §3 的 battery。加一個門檻或一句判語就
 * 會把它變成一個從來沒有被檢定過的訊號,而它穿著這個功能的外衣。
 */
export interface FuturesOpenInterestDirection {
  /** 這四個計數講的是哪一天——期貨**行情日**,同 `FuturesVolumeAnomalyMeta.as_of`。 */
  as_of: string;
  increased: number;
  decreased: number;
  unchanged: number;
  /**
   * 判不出方向的契約數:當天或前一個期貨交易日沒有列、或未平倉是 NULL。
   * 它**必須**被數出來而不是從分母消失——成因依 R1 有未掛牌 / 未公布 / 匯入失敗
   * 三種,三者不可分辨,所以只數,不分類,也不說成「沒有變動」。
   */
  undetermined: number;
}

/** 單一分點在這檔股票的兩側計數;known 是分母,unknown 分位不可知另計。 */
export interface BranchPctileRow {
  branch_name: string;
  buy_pctile_known: number;
  buy_pctile_unknown: number;
  low_buy_count: number;
  sell_pctile_known: number;
  sell_pctile_unknown: number;
  high_sell_count: number;
  /**
   * 次日回吐:同一個窗口內,可判定的合格買超日數,以及其中次日賣出達當日淨買
   * 七成以上的次數。此欄早於資料上線,舊 payload 會缺;缺鍵 = 沒有這項觀察,
   * 不是 0 次。obs 低於 `min_daytrade_obs` 時是「無法判定」,同樣不是 0 次。
   */
  daytrade_obs?: number;
  daytrade_paybacks?: number;
  /**
   * v2 起:與上面次數同一個分類的張數(episode 張數 = 各合格日 |淨買賣| 加總)。
   * v1 payload 缺鍵;v2 但快照尚未重算時為 null(此時排序退回次數)。
   */
  buy_lots_known?: number | null;
  low_buy_lots?: number | null;
  sell_lots_known?: number | null;
  high_sell_lots?: number | null;
}

/** v2 的一派(短線派 20 日／長線派 120 日)。 */
export interface BranchPctileCamp {
  /** 這份快照有沒有算這一派;false 時 branches 為空,不是「沒有分點」。 */
  available: boolean;
  stock_buy_pctile_known: number | null;
  stock_low_buy_count: number | null;
  stock_sell_pctile_known: number | null;
  stock_high_sell_count: number | null;
  stock_buy_lots_known: number | null;
  stock_low_buy_lots: number | null;
  stock_sell_lots_known: number | null;
  stock_high_sell_lots: number | null;
  /** 收縮強度 K(該側已知張數的分點中位數);次數排序時為 null。 */
  shrink_k_buy_lots: number | null;
  shrink_k_sell_lots: number | null;
  branches: BranchPctileRow[];
}

/**
 * v2 payload(2026-10-02):兩派各一份排序清單,加上 `lookup`——其餘分點的精簡陣列,
 * 欄位順序見 `lookup_fields`(`branch_name`, `short.<field>`…, `long.<field>`…)。
 */
export interface BranchPctileCountsV2 {
  version: 2;
  /** "lots_shrunk_v2"(張數加權＋收縮；v1 同為 lots_shrunk 系列)或 "counts_v1"(舊快照退路)。 */
  ranking: string;
  min_known_episodes_per_side: number;
  max_branches: number;
  windows: { short: number; long: number };
  low_buy_max_pctile: number;
  high_sell_min_pctile: number;
  min_daytrade_obs: number;
  as_of: string | null;
  window_market_days: number | null;
  window_from: string | null;
  computed_at: string | null;
  definitions_version: string | null;
  stock_daytrade_obs: number | null;
  stock_daytrade_paybacks: number | null;
  short: BranchPctileCamp;
  long: BranchPctileCamp;
  lookup_fields: string[];
  lookup: (string | number | null)[][];
}

export type BranchPctileCounts = BranchPctileCountsV1 | BranchPctileCountsV2;

/** v1 payload(舊 JSON);`branches` 可能是空陣列(誠實的空,不是錯誤)。 */
export interface BranchPctileCountsV1 {
  version: 1;
  /** 窗口結束日;整份快照尚未產生時可能為 null。 */
  as_of: string | null;
  window_market_days: number | null;
  window_from: string | null;
  computed_at: string | null;
  definitions_version: string | null;
  min_known_episodes_per_side: number;
  max_branches: number;
  /** 同一檔股票所有分點合計的同側計數,當作讀每一列的尺。 */
  stock_buy_pctile_known: number | null;
  stock_low_buy_count: number | null;
  stock_sell_pctile_known: number | null;
  stock_high_sell_count: number | null;
  /** 次日回吐的判定門檻與該股自身 pooled 計數;舊 payload 會缺這三鍵。 */
  min_daytrade_obs?: number;
  stock_daytrade_obs?: number | null;
  stock_daytrade_paybacks?: number | null;
  branches: BranchPctileRow[];
}

export interface HoldersThresholdCell {
  holders: number;
  shares_pct: number;
}

export interface HoldersHistoryPoint {
  t: string;
  thresholds: Record<string, HoldersThresholdCell>;
  /** 未滿 400 張散戶持股％（export 後才有；舊 JSON 可能缺） */
  retail_pct?: number | null;
  retail_holders?: number | null;
  /** 董監持股加總÷集保庫存％（月更 ffill） */
  insider_pct?: number | null;
}

export interface HoldersMeta {
  display_from: string;
  display_to: string;
  db_earliest: string | null;
  window_label?: string;
  source?: string;
  note?: string;
  insider_as_of_ym?: string | null;
  insider_note?: string | null;
}

export interface DirectorsLatestRow {
  title: string;
  name: string;
  shares: number;
  lots: number;
  shares_at_election?: number | null;
  pledged_shares?: number | null;
  pledged_pct?: number | null;
  related_shares?: number | null;
  market?: string;
}

export interface DirectorsLatest {
  as_of_ym: string;
  source?: string;
  note?: string;
  rows: DirectorsLatestRow[];
}

export interface MarginHistoryPoint {
  t: string;
  balance: number | null;
  prev: number | null;
  limit: number | null;
  usage: number | null;
  chg: number | null;
  buy: number | null;
  sell: number | null;
  repay: number | null;
  short_balance: number | null;
  short_prev: number | null;
  cost_est: number | null;
}

export interface MarginMeta {
  display_from: string;
  display_to: string;
  db_earliest: string | null;
  backfill_target_days: number;
  window_label?: string;
}

export interface MarginUsageItem {
  id: string;
  name: string;
  usage: number;
  balance: number;
  limit: number;
  chg: number | null;
  /** 較前一日使用率變化（百分點，例 +1.4 = 88.4%→89.8%） */
  usage_chg: number | null;
  close: number | null;
  /** @deprecated 股價漲跌幅，新 export 已改 usage_chg */
  chg_pct?: number | null;
}

export interface MarginUsageJson {
  as_of: string | null;
  data_date: string;
  generated_at: string;
  items: MarginUsageItem[];
}

/** 法人族群(docs/49):rankings/insti_flow_1d.json */
export type InstiIdentity = "foreign" | "trust" | "dealer" | "total";

export interface InstiFlowMember {
  id: string;
  name: string;
  market: string;
  net_lots: number;
  /** 淨股數 × 當日收盤(估) */
  amt_est: number;
  chg_pct: number | null;
}

export interface InstiFlowGroup {
  name: string;
  /** 該日有法人列的成分數 */
  n: number;
  buy_n: number;
  sell_n: number;
  net_lots: number;
  amt_est: number;
  buy_top: InstiFlowMember[];
  sell_top: InstiFlowMember[];
  /** 無收盤、金額未計的成分數(> 0 才有) */
  amt_missing_n?: number;
  /** 題材分類已過期時的分類日(只有 stale 題材帶) */
  cls_date?: string;
}

export interface InstiFlowJson {
  version: number;
  window: number;
  days_actual: number;
  as_of: string;
  data_date: string;
  generated_at: string;
  stale: boolean;
  coverage: { twse: number; tpex: number; partial: boolean };
  amt_missing_n: number;
  market: Record<InstiIdentity, { net_lots: number; amt_est: number }>;
  groups: {
    industry: Record<InstiIdentity, InstiFlowGroup[]>;
    theme: Record<InstiIdentity, InstiFlowGroup[]>;
    /** 產業「其他」(空白/字面其他/不足 3 檔),不排名 */
    other?: Record<InstiIdentity, InstiFlowGroup>;
  };
}

/** 法人買賣超個股(docs/49 §9):rankings/insti_stocks_1d.json */
export interface InstiStockRow {
  id: string;
  name: string;
  market: string;
  /** 官方產業別(空字串 = 無) */
  ind: string;
  net_lots: number;
  /** 淨股數 × 當日收盤(估);無收盤時為 0 並帶 amt_missing */
  amt_est: number;
  chg_pct: number | null;
  /** 截至法人日連續同方向的法人日數(只看最近 streak_days 日) */
  streak: number;
  amt_missing?: true;
}

export interface InstiStockSide {
  buy_n: number;
  sell_n: number;
  buy: InstiStockRow[];
  sell: InstiStockRow[];
}

export interface InstiStocksJson {
  version: number;
  window: number;
  as_of: string;
  data_date: string;
  generated_at: string;
  stale: boolean;
  coverage: { twse: number; tpex: number; partial: boolean };
  amt_missing_n: number;
  streak_days: number;
  top_n: number;
  ranks: Record<InstiIdentity, InstiStockSide>;
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

export type ListKey = "score" | "hot" | "surge" | "strong" | "weak" | "warrant" | "armed" | "triggered" | "extended" | "faded" | "pocket";

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
  spark: number[]; // 近 30 日收盤;缺當日分時時當 fallback
  spark_day?: number[]; // 當日分時(降採樣 ~60 點)
  spark_open?: number; // 當日開盤,分時圖平盤基準
  id: string;
  name: string;
  market: "twse" | "tpex";
  industry: string | null;
  description?: string | null;
  themes?: string[];
  close: number;
  chg_pct: number | null;
  /** 首頁沒畫 → `home/stocks.json` 沒有這個鍵(docs/44 P2);radar.json 仍有。 */
  chg5_pct?: number | null;
  volume_ratio: number | null; // 今日量 / 20 日均量
  turnover: number;
  /** 首頁沒畫 → `home/stocks.json` 沒有(同 chg5_pct)。 */
  volume_lots?: number;
  transactions?: number | null;
  foreign_net_lots: number | null;
  trust_net_lots: number | null;
  margin_chg_lots?: number | null;
  /** 首頁卡片只畫這三個權證欄位;`home/stocks.json` 也只給這三個,radar.json 是完整的 WarrantSummary。 */
  warrant: Pick<WarrantSummary, "call_turnover" | "call_turnover_ratio" | "call_count"> | null;
  /** 首頁沒畫 → `home/stocks.json` 沒有(個股頁讀的是 StockJson.technical)。 */
  technical?: TechnicalSummary | null;
  scores: ScoreBreakdown | null; // null = 該股當日未評分(流動性門檻未過等)
  state?: "armed" | "triggered" | "extended" | "faded" | null;
  sources?: ("branch" | "warrant")[];
  reasons: string[];
  raw_reasons?: ReasonItem[];
  /** Additive S4 two-phase details; absent in legacy JSON. */
  strategy_signals?: {
    strategy: "S4_VOLATILITY_CONTRACTION";
    phase: "legacy" | "setup" | "breakout";
    quality_rank?: number | null;
  }[];
  pocket_tags?: PocketTag[];
  pocket_score?: number;
  pocket_families?: string[];
  risks: string[];
}

export interface StrategyPerfHorizon {
  samples: number;
  win_rate: number | null;
  avg_ret: number | null;
  median_ret: number | null;
}

export interface StrategyMeta {
  status: "active" | "shadow" | "retired";
  /** Additive lifecycle contract. Absent on older radar.json snapshots. */
  effective_date?: string;
  rationale?: string;
  decision_ref?: string;
  version?: number;
  label: string;
  h5: StrategyPerfHorizon;
  h10: StrategyPerfHorizon;
  h20: StrategyPerfHorizon;
  sufficient_samples: boolean;
}

/** radar.json `score_list_meta`:全部是整數與一個布林,比率由讀的人自己算。 */
export interface ScoreListMeta {
  min_final: number;
  scored: number;
  missing_branch: number;
  missing_inst: number;
  withheld: boolean;
  max_final: number | null;
}

export interface RadarJson {
  data_date: string;
  generated_at: string;
  note: string;
  summary_text?: string[]; // F2: auto-generated daily brief (≤3 sentences)
  summary: { market: string; turnover: number; up: number; down: number }[];
  freshness?: Record<string, { date: string | null; stale: boolean }>; // 各資料集有效日
  sectors: SectorFlow[];
  themes?: SectorFlow[]; // 概念股資金流(成分重疊)
  concentration?: ConcentrationRow[]; // 集中度躍升榜(探索頁)
  lists: Record<ListKey, string[]>;
  /**
   * 綜合榜的資料齊全閘門(2026-09-24)。`withheld: true` 時 `lists.score` 是 []
   * 但意思是「分點/法人未到齊、刻意不排名」,不是「今天沒人達標」。缺鍵 = 舊 payload。
   */
  score_list_meta?: ScoreListMeta;
  pocket_note?: string;
  strategies?: Record<string, string[]>;
  /** Additive S4 phase lists. Existing clients may continue using strategies.S4. */
  strategy_phases?: Record<string, Partial<Record<"legacy" | "setup" | "breakout", string[]>>>;
  strategy_meta?: Record<string, StrategyMeta>;
  /**
   * 今日期貨成交量異常的契約名單(docs/38 §7.5)。**三態**:缺鍵 = 今天沒有算過
   * (期貨還沒跟上 export 日),不是「今天沒有異常」;`[]` = 算過了而且今天沒有
   * 契約舉旗;非空 = 名單本身。把前兩者塌成同一件事就是這個鍵存在要擋的錯。
   */
  futures_volume_anomalies?: FuturesVolumeAnomalyEntry[];
  /**
   * 上面那個名單的隨附事實(docs/38 §7.11)。與名單**同生共死**:名單缺鍵時
   * 這個鍵也不存在。它只為了空陣列那一態而生——那一態沒有任何 `anomaly` 區塊,
   * 而 §7.10 不准前端寫死 60,所以比較窗口的長度得由這裡供應。
   */
  futures_volume_anomalies_meta?: FuturesVolumeAnomalyMeta;
  /** 近 N 個期貨交易日的舉旗紀錄,新到舊(docs/38 §7.19)。與名單同生共死。 */
  futures_volume_anomaly_history?: FuturesAnomalyHistoryDay[];
  futures_volume_anomaly_history_meta?: FuturesAnomalyHistoryMeta;
  /**
   * 市場層級的未平倉方向計數(docs/38 §7.15)。與上面那兩個鍵**平行而不相屬**:
   * 名單只有舉旗的契約,這裡涵蓋全部約 320 個;名單會因為 R4 算不出結算窗口而
   * 整個不主張,而未平倉的方向與結算窗口無關。缺鍵 = 沒有算過(沒有期貨行情日),
   * 有鍵 = 數過了,即使四個數字全是 0——兩者不可塌成同一件事。
   */
  futures_open_interest_direction?: FuturesOpenInterestDirection;
  /**
   * 首頁「市場概況」(docs/49 §11):大盤指數,每市 ≤ data_date 的最新一列(固定 twse、tpex)。
   * 缺鍵 = 還沒匯入過指數(舊 payload),那兩格不畫。`date` 可能早於 data_date(指數晚到)。
   */
  indices?: MarketIndex[];
  /** 三大法人全市場淨額(與法人族群分頁 marketLine 同一組數字);缺鍵 = 沒有法人資料。 */
  insti_market?: InstiMarket;
  stocks: RadarStock[];
}

export interface MarketIndex {
  market: "twse" | "tpex" | "tx" | string;
  name: string;
  date: string;
  close: number;
  /** 漲跌點數(含正負);來源缺 → null */
  change: number | null;
  /** 漲跌百分比;TPEx / 台指期由 close/change 推 */
  chg_pct: number | null;
  /** 最近 ≤40 個收盤(舊→新),迷你走勢圖用;舊 payload 沒有 */
  spark?: number[];
  /** 只有台指期(market=tx):近月契約月份 YYYYMM 與當日結算價 */
  contract_month?: string | null;
  settlement?: number | null;
}

/** `market/indices_hist.json`(docs/49 §12):點開走勢圖才抓;points = [date, close, change, chg_pct](舊→新) */
export interface IndicesHistJson {
  version: number;
  as_of: string;
  generated_at: string;
  /** 台指期的 points 每列多第 5 個元素:當天的近月月份(近月連續、未調整換月價差) */
  series: Record<string, { name: string; points: [string, number, number | null, number | null, string?][]; contract_month?: string | null }>;
}

export interface InstiMarket {
  /** 法人日(可能早於 data_date) */
  date: string;
  foreign: { net_lots: number; amt_est: number };
  trust: { net_lots: number; amt_est: number };
  dealer: { net_lots: number; amt_est: number };
  total: { net_lots: number; amt_est: number };
}

/**
 * `home/head.json`(docs/44 P2)= radar.json 扣掉 `stocks` 與首頁沒讀的 `concentration` /
 * `summary_text` / `score_list_meta`;舊資料退回 radar.json 時也用這個型別(多出來的鍵不讀)。
 */
export type RadarHeadJson = Omit<RadarJson, "stocks"> & { version?: number };

/** bull_board.json 卡片上的一條事實(docs/48 §1.1)。沒有 rank/magnitude/score/position。 */
export interface BullBoardFact {
  code: string | null;
  source: string;
  section: "tech" | "chips" | "levels";
  text: string;
  segments?: { t: string; kind?: "price" | "up" | "down" | "flat" }[];
  /** 技術段的週期;日K 不輸出 */
  tf?: "W" | "M";
}

export interface BullBoardBearFact extends BullBoardFact {
  risk: boolean;
  /** 滯後資料的日期(MM/DD);當日事實沒有 */
  date?: string;
}

export interface BullBoardEntry {
  id: string;
  name: string;
  market: "twse" | "tpex";
  industry: string | null;
  close: number | null;
  chg_pct: number | null;
  turnover: number | null;
  final: number | null;
  state: RadarStock["state"] | null;
  bull_key_n: number;
  bear_key_n: number;
  bull: BullBoardFact[];
  bear: BullBoardBearFact | null;
  counts: Record<"tech" | "chips" | "levels", { bull: number; bear: number }>;
  /**
   * 族群檢視用(docs/48 §1.1,只影響顯示,不屬凍結規則):今日題材資金流上最熱的題材;
   * null = 今日沒有在榜題材(畫面改用產業)。缺鍵 = 舊 payload(畫面從 radar.json 補查)。
   */
  theme?: { name: string; vs20: number | null } | null;
}

/**
 * 首頁「多方榜」(docs/48)。**三態**:檔不存在(404)= 沒算過;`qualified 0` 且 `entries []`
 * = 算過、沒有股票入榜;非空 = 名單。entries 的順序就是排序,畫面不顯示名次。
 */
export interface BullBoardJson {
  version: string;
  data_date: string;
  generated_at: string;
  radar_generated_at: string;
  /** 紀錄(bull_board_log)最早的資料日;沒有紀錄時 null */
  log_from: string | null;
  universe: number;
  qualified: number;
  min_bull_key: number;
  inputs: {
    insti: { date: string | null; stale: boolean } | null;
    branch: { date: string | null; stale: boolean } | null;
    margin: { date: string | null; stale: boolean } | null;
    holders_week: string | null;
  };
  entries: BullBoardEntry[];
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
