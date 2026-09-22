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
  technical: TechnicalSummary | null;
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
   * 重現」,所以讀取端只能呈現次數與該股自身的同側比率,不得做成徽章。
   * 舊版 JSON 沒有這個鍵;缺鍵時整節不渲染。
   */
  branch_pctile_counts?: BranchPctileCounts;
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
}

export interface FuturesContract {
  code: string;
  is_futures: boolean;
  is_option: boolean;
  is_weekly_option: boolean;
  /** 當日沒有列時整個省略,不可補 0——0 代表「沒人交易」,省略代表「還沒公布」。
   *  注意:這裡的 `volume` 是**一般 + 盤後**兩時段之和,與只算一般時段的
   *  `anomaly.today` 是**不同的數字**,不得當成同一個顯示(docs/38 §7.6)。 */
  daily?: {
    date: string;
    volume: number | null;
    open_interest: number | null;
    session_volume: Record<string, number>;
  };
  /**
   * 成交量異常旗標(docs/38 §1)。**沒有這個鍵有三種意思**——被 §2 否決、規則看過
   * 但沒創高、期貨還沒匯進來——而且刻意不可分辨,三者都不是一個異常。
   * **不得把任何一種標成「正常」**(§7.7)。
   */
  anomaly?: FuturesAnomaly;
  /** 與 `anomaly` 同生共死;沒有旗標就沒有這兩個鍵(§7.3)。 */
  reasons?: ReasonItem[];
  risks?: ReasonItem[];
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
  anomaly: FuturesAnomaly;
  reasons: ReasonItem[];
  risks: ReasonItem[];
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
}

/** 個股頁的分位計數 payload;`branches` 可能是空陣列(誠實的空,不是錯誤)。 */
export interface BranchPctileCounts {
  version: number;
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
  chg5_pct?: number | null;
  volume_ratio: number | null; // 今日量 / 20 日均量
  turnover: number;
  volume_lots: number;
  transactions: number | null;
  foreign_net_lots: number | null;
  trust_net_lots: number | null;
  margin_chg_lots: number | null;
  warrant: WarrantSummary | null;
  technical: TechnicalSummary | null;
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
