/**
 * 首頁「多方榜」(docs/48,版本 bull-board-v2):選股規則、payload 組裝與畫面句子。
 *
 * 純函式,不 import 任何執行期的 "@/" 模組:VPS 上的建置器(web/scripts/build-bull-board.mjs)
 * 用 Node 直接跑這份 TS,首頁也用同一份產生狀態句。
 *
 * v2(2026-10-10,docs/48 §8):規則與 rank 表一字未改,改的是**輸入**——分點日史從每天 |淨額| 前 12 列
 * 改成來源完整的買超前 15 + 賣超前 15(docs/44 §3.4),分點事實(C_TOP15_FLOW_*、囤貨/出貨、強分點…)
 * 的計算基礎因此不同,評估時鐘從第一個以新資料建置的資料日重新起算;v1 的紀錄行原樣保留。
 *
 * 規則(docs/48 §1,凍結;改任何一條 = 下一版):
 * - 母體:個股 JSON 有評分(scores != null)且最後一根 K 棒 == radar.data_date。
 * - K_bull / K_bear:summary.bull / bear 中技術、籌碼兩段、rank ≥4、不是滯後資料(沒有 date/dataDate)的項。
 * - 排除 E:summary.bear 中技術、籌碼兩段、rank == 5、不是滯後資料的項;有任何一條就不入榜。壓力段不計也不排除。
 * - 入榜:|K_bull| ≥ 3 且 E 為空。排序:|K_bull| 多 → K_bull 不同來源數多 → |K_bear| 少 → 成交金額大 → 代號。
 *   上限 40 檔,不湊數。payload 不輸出名次、rank、magnitude、分數。
 */
import {
  SECTION_ORDER,
  keyItems,
  topOfSide,
  type BullBearItem,
  type BullBearSummary,
  type Section,
} from "./bullBear.ts";
import { UPDATE_SCHEDULE } from "./freshness.ts";
import { hottestListedTheme } from "./themeGroups.ts";
import type { BullBoardBearFact, BullBoardEntry, BullBoardFact, BullBoardJson } from "./types.ts";

export const BULL_BOARD_VERSION = "bull-board-v2";
/**
 * v2 評估期的第一個可用資料日(docs/48 §2、§8):程式改動日 2026-10-10 之後的資料日才算。
 * 2026-10-10 當晚 VPS 第一輪 v2 export 的資料日是 10/08(改動前的市場日),那一行 version 已是 v2
 * 但不進評估、也不是 `log_from`;建置器與日後的 battery 都以這個常數為準。
 */
export const BULL_BOARD_EVAL_FROM = "2026-10-11";
export const MIN_BULL_KEY = 3;
export const BOARD_CAP = 40;
/** 入榜與排除只看這兩段;壓力段(levels)不計也不排除。 */
export const BOARD_SECTIONS: readonly Section[] = ["tech", "chips"];
/** 卡片上的多方條數 */
export const CARD_BULL_MAX = 3;

export const BOARD_TAB_LABEL = "多方榜";
export const BOARD_DEFINITION =
  "依今日影響最大的多方事實數量排列;出現重大空方事件的股票不列。多方＝對股價有利的已發生事實。只整理資料,不下判斷。";
export const BOARD_NO_BEAR = "今日沒有空方事實";
export const BOARD_MISSING = "這一版還沒有多方榜(下一輪資料更新後出現)。";

const lagged = (it: BullBearItem) => !!(it.date || it.dataDate);
const onBoard = (it: BullBearItem) => BOARD_SECTIONS.includes(it.section) && !lagged(it);

export interface BoardKeys {
  bull: BullBearItem[];
  bear: BullBearItem[];
  /** 重大空方事件(rank 5);非空即不入榜 */
  excl: BullBearItem[];
}

export function boardKeys(s: BullBearSummary): BoardKeys {
  return {
    bull: s.bull.filter((it) => onBoard(it) && it.rank >= 4),
    bear: s.bear.filter((it) => onBoard(it) && it.rank >= 4),
    excl: s.bear.filter((it) => onBoard(it) && it.rank === 5),
  };
}

export function qualifies(k: BoardKeys): boolean {
  return k.bull.length >= MIN_BULL_KEY && k.excl.length === 0;
}

/** 建置器讀進來的一檔(radar.json 的欄位優先,缺的由個股 JSON 補)。 */
export interface BoardCandidate {
  id: string;
  name: string;
  market: "twse" | "tpex";
  industry: string | null;
  close: number | null;
  chg_pct: number | null;
  turnover: number | null;
  final: number | null;
  state: BullBoardEntry["state"];
  /** 個股 JSON 的 scores != null */
  scored: boolean;
  /** 最後一根 K 棒的日期 */
  lastT: string;
  summary: BullBearSummary;
  /** 族群檢視用(只影響顯示,不參與入榜/排序/紀錄);建置器以 hottestListedTheme 算 */
  theme?: { name: string; vs20: number | null } | null;
}

export function inUniverse(c: Pick<BoardCandidate, "scored" | "lastT">, dataDate: string): boolean {
  return c.scored && c.lastT === dataDate;
}

const distinctSources = (items: BullBearItem[]) => new Set(items.map((x) => x.source)).size;

interface Scored {
  c: BoardCandidate;
  k: BoardKeys;
}

function compareBoard(a: Scored, b: Scored): number {
  return (
    b.k.bull.length - a.k.bull.length ||
    distinctSources(b.k.bull) - distinctSources(a.k.bull) ||
    a.k.bear.length - b.k.bear.length ||
    (b.c.turnover ?? 0) - (a.c.turnover ?? 0) ||
    (a.c.id < b.c.id ? -1 : a.c.id > b.c.id ? 1 : 0)
  );
}

export interface BoardSelection {
  universeIds: string[];
  /** 全部入榜者(已排序,未截斷) */
  qualified: Scored[];
  /** |K_bull| ≥ 3 但被重大空方事件排除者(紀錄用) */
  excluded: Scored[];
}

export function selectBoard(cands: BoardCandidate[], dataDate: string): BoardSelection {
  const universeIds: string[] = [];
  const qualified: Scored[] = [];
  const excluded: Scored[] = [];
  for (const c of cands) {
    if (!inUniverse(c, dataDate)) continue;
    universeIds.push(c.id);
    const k = boardKeys(c.summary);
    if (qualifies(k)) qualified.push({ c, k });
    else if (k.bull.length >= MIN_BULL_KEY) excluded.push({ c, k });
  }
  qualified.sort(compareBoard);
  universeIds.sort();
  excluded.sort((a, b) => (a.c.id < b.c.id ? -1 : 1));
  return { universeIds, qualified, excluded };
}

function fact(it: BullBearItem): BullBoardFact {
  return {
    code: it.code,
    source: it.source,
    section: it.section,
    text: it.text,
    ...(it.segments ? { segments: it.segments } : {}),
    // 週K/月K 的事實要帶著週期小膠囊(日K 不帶)
    ...(it.tf && it.tf !== "D" ? { tf: it.tf } : {}),
  };
}

function bearFact(it: BullBearItem): BullBoardBearFact {
  const date = it.date ?? it.dataDate;
  return { ...fact(it), risk: it.risk, ...(date ? { date } : {}) };
}

export function toEntry({ c, k }: Scored): BullBoardEntry {
  const top = topOfSide(c.summary, "bear");
  const counts = Object.fromEntries(
    SECTION_ORDER.map((sec) => [sec, { bull: c.summary.sections[sec].bull.length, bear: c.summary.sections[sec].bear.length }]),
  ) as BullBoardEntry["counts"];
  return {
    id: c.id,
    name: c.name,
    market: c.market,
    industry: c.industry,
    close: c.close,
    chg_pct: c.chg_pct,
    turnover: c.turnover,
    final: c.final,
    state: c.state ?? null,
    bull_key_n: k.bull.length,
    bear_key_n: k.bear.length,
    bull: keyItems(k.bull).slice(0, CARD_BULL_MAX).map(fact),
    bear: top ? bearFact(top) : null,
    counts,
    theme: c.theme ?? null,
  };
}

type Fresh = { date: string | null; stale: boolean } | undefined | null;

export interface RadarInfo {
  data_date: string;
  generated_at: string;
  freshness?: Record<string, Fresh>;
}

const pickFresh = (f: Fresh) => (f ? { date: f.date ?? null, stale: !!f.stale } : null);

export function buildBullBoard(
  radar: RadarInfo,
  sel: BoardSelection,
  opts: { generatedAt: string; logFrom: string | null; holdersWeek: string | null },
): BullBoardJson {
  return {
    version: BULL_BOARD_VERSION,
    data_date: radar.data_date,
    generated_at: opts.generatedAt,
    radar_generated_at: radar.generated_at,
    log_from: opts.logFrom,
    universe: sel.universeIds.length,
    qualified: sel.qualified.length,
    min_bull_key: MIN_BULL_KEY,
    inputs: {
      insti: pickFresh(radar.freshness?.insti),
      branch: pickFresh(radar.freshness?.branch),
      margin: pickFresh(radar.freshness?.margin),
      holders_week: opts.holdersWeek,
    },
    entries: sel.qualified.slice(0, BOARD_CAP).map(toEntry),
  };
}

/** bull_board_log 的一行(docs/48 §1.1):往後檢定的唯一資料來源,只追加。 */
export function boardLogLine(board: BullBoardJson, sel: BoardSelection) {
  const codes = (items: BullBearItem[]) => items.map((x) => x.code ?? x.text);
  return {
    version: board.version,
    data_date: board.data_date,
    generated_at: board.generated_at,
    radar_generated_at: board.radar_generated_at,
    universe: board.universe,
    qualified: board.qualified,
    universe_ids: sel.universeIds,
    entries: sel.qualified.map(({ c, k }) => ({ id: c.id, bull_key_n: k.bull.length, bear_key_n: k.bear.length, bull_codes: codes(k.bull) })),
    excluded: sel.excluded.map(({ c, k }) => ({ id: c.id, bull_key_n: k.bull.length, codes: codes(k.excl) })),
    inputs: board.inputs,
  };
}

// ---------------------------------------------------------------------------
// 畫面句子(首頁)。全部在這裡,禁詞由 bullBoard.test.ts 把關。
// ---------------------------------------------------------------------------

/** 2026-10-02 → 10/02 */
export function mmddSlash(date: string | null | undefined): string {
  return date && /^\d{4}-\d{2}-\d{2}/.test(date) ? `${date.slice(5, 7)}/${date.slice(8, 10)}` : "—";
}

/** ISO 時間 → 台北「MM-DD HH:MM」 */
export function taipeiStamp(iso: string): string {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return iso;
  const s = new Date(ms + 8 * 3600_000).toISOString();
  return `${s.slice(5, 10)} ${s.slice(11, 16)}`;
}

const scheduleTime = (key: string) => UPDATE_SCHEDULE.find((r) => r.key === key)?.short.match(/\d{1,2}:\d{2}/)?.[0] ?? "";

export function countLine(b: BullBoardJson): string {
  const extra = b.qualified > b.entries.length ? `,列出 ${b.entries.length} 檔` : "";
  return `檢視 ${b.universe} 檔 → 入榜 ${b.qualified} 檔${extra}`;
}

export function inputsLine(b: BullBoardJson): string {
  const i = b.inputs;
  return `資料:法人 ${mmddSlash(i.insti?.date)}、分點 ${mmddSlash(i.branch?.date)}、資券 ${mmddSlash(i.margin?.date)}、大戶(集保)${mmddSlash(i.holders_week)}`;
}

export function recordLine(b: BullBoardJson): string {
  return `名單自 ${mmddSlash(b.log_from ?? b.data_date)} 起每日留存;往後表現須累積 60 個交易日並通過事前登記的檢定,才會以次數顯示。`;
}

export function emptyText(b: BullBoardJson): string {
  return `今日檢視 ${b.universe} 檔,沒有股票同時有 ${b.min_bull_key} 條以上多方重點事實且無重大空方事件。`;
}

/** 停在上一版:資料日不同,或建置時間比 radar.json 舊 1 小時以上。 */
export function staleText(b: BullBoardJson, radar: Pick<RadarInfo, "data_date" | "generated_at">): string | null {
  const behind = Date.parse(radar.generated_at) - Date.parse(b.generated_at);
  if (b.data_date === radar.data_date && !(behind > 3600_000)) return null;
  return `多方榜停在 ${taipeiStamp(b.generated_at)} 那一版,其他資料已更新;下一輪會跟上。`;
}

/** 這一版建置時法人/分點還沒到齊(盤中版)。 */
export function incompleteText(b: BullBoardJson): string | null {
  const insti = !!b.inputs.insti?.stale;
  const branch = !!b.inputs.branch?.stale;
  if (!insti && !branch) return null;
  const ti = scheduleTime("insti");
  const tb = scheduleTime("branch");
  if (insti && branch) {
    return `法人、分點尚未到齊:目前只有技術面與價格事實;法人 ${ti} 起、分點 ${tb} 起到齊後重算。`;
  }
  return insti
    ? `法人尚未到齊:目前的籌碼事實不含法人;法人 ${ti} 起到齊後重算。`
    : `分點尚未到齊:目前的籌碼事實不含分點;分點 ${tb} 起到齊後重算。`;
}

export type BoardView =
  | { kind: "missing"; text: string }
  | {
      kind: "ready";
      board: BullBoardJson;
      dateLabel: string;
      countLine: string;
      inputsLine: string;
      recordLine: string;
      notices: { key: "stale" | "incomplete"; text: string }[];
      /** qualified 0 時的句子;有名單時 null */
      empty: string | null;
    };

/** board:null = 檔不存在/404/讀取失敗(沒算過);undefined = 還在載入,不呼叫。 */
export function boardView(board: BullBoardJson | null, radar: Pick<RadarInfo, "data_date" | "generated_at">): BoardView {
  if (!board || !Array.isArray(board.entries)) return { kind: "missing", text: BOARD_MISSING };
  const notices: { key: "stale" | "incomplete"; text: string }[] = [];
  const st = staleText(board, radar);
  if (st) notices.push({ key: "stale", text: st });
  const inc = incompleteText(board);
  if (inc) notices.push({ key: "incomplete", text: inc });
  return {
    kind: "ready",
    board,
    dateLabel: mmddSlash(board.data_date),
    countLine: countLine(board),
    inputsLine: inputsLine(board),
    recordLine: recordLine(board),
    notices,
    empty: board.entries.length === 0 ? emptyText(board) : null,
  };
}

/** 卡片底列:「技術 ▲3 ▼1」 */
export const COUNT_SECTIONS: readonly Section[] = ["tech", "chips", "levels"];

// ---------------------------------------------------------------------------
// 族群檢視(docs/48 §1.1):只重排畫面,不改入榜、排序或紀錄。
// ---------------------------------------------------------------------------

export type BoardViewMode = "facts" | "group";
export const BOARD_VIEW_LABEL: Record<BoardViewMode, string> = { facts: "事實", group: "族群" };
export const BOARD_OTHER_GROUP = "其他";

export interface BoardGroup {
  /** `${kind}:${name}`:題材與產業同名時仍是兩組 */
  key: string;
  name: string;
  kind: "theme" | "industry" | "other";
  /** 今日成交金額 / 近 20 日均;不知道時 null */
  vs20: number | null;
  /** 原榜單順序;i = 在 entries 中的位置 */
  items: { e: BullBoardEntry; i: number }[];
}

/** 舊 payload(entries 沒有 theme 鍵)時,從 radar.json 補查用。 */
export interface BoardGroupContext {
  stocks?: { id: string; themes?: string[] }[];
  themes?: { name: string; vs20: number | null }[];
  sectors?: { name: string; vs20: number | null }[];
}

/**
 * 每檔只歸一個族群:今日最熱的在榜題材 → 產業 → 「其他」。
 * 族群依檔數多 → 族群內最前面那檔的原順序;「其他」永遠最後。族群內維持原榜單順序。
 */
export function groupBoardEntries(entries: BullBoardEntry[], ctx: BoardGroupContext = {}): BoardGroup[] {
  const themesById = new Map((ctx.stocks ?? []).map((s) => [s.id, s.themes]));
  const sectorVs20 = new Map((ctx.sectors ?? []).map((s) => [s.name, s.vs20]));
  const groups = new Map<string, BoardGroup>();
  entries.forEach((e, i) => {
    const theme = e.theme !== undefined ? e.theme : hottestListedTheme(themesById.get(e.id), ctx.themes);
    const themeName = theme?.name.trim() || null;
    // 產業字面就是「其他」(約 136 檔)等於沒有產業:併進同一個「其他」,不另開一組
    const ind = e.industry?.trim() || null;
    const industry = ind && ind !== BOARD_OTHER_GROUP ? ind : null;
    const kind: BoardGroup["kind"] = themeName ? "theme" : industry ? "industry" : "other";
    const name = themeName ?? industry ?? BOARD_OTHER_GROUP;
    const vs20 = themeName ? (theme?.vs20 ?? null) : industry ? (sectorVs20.get(industry) ?? null) : null;
    const key = `${kind}:${name}`;
    const g = groups.get(key);
    if (g) {
      g.items.push({ e, i });
      if (g.vs20 == null) g.vs20 = vs20;
    } else groups.set(key, { key, name, kind, vs20, items: [{ e, i }] });
  });
  return [...groups.values()].sort(
    (a, b) =>
      Number(a.kind === "other") - Number(b.kind === "other") ||
      b.items.length - a.items.length ||
      a.items[0].i - b.items[0].i,
  );
}

export const GROUP_SUMMARY_LABEL = "多方集中";
export const GROUP_SUMMARY_MAX = 6;

export interface GroupChip {
  /** 唯一鍵(React key) */
  key: string;
  name: string;
  n: number;
  /** 點下去要捲到的族群 key(「其他」= 前幾名之後的第一個族群) */
  target: string;
}

/**
 * 頁首的族群分布(兩種檢視都顯示):與 groupBoardEntries 同一個分組與順序,
 * 取前 max 個有名字的族群,其餘(含沒有題材也沒有產業的)併成「其他」放最後。
 */
export function groupSummary(groups: BoardGroup[], max = GROUP_SUMMARY_MAX): GroupChip[] {
  const top = groups.filter((g) => g.kind !== "other").slice(0, max);
  const rest = groups.filter((g) => !top.includes(g));
  const chips: GroupChip[] = top.map((g) => ({ key: g.key, name: g.name, n: g.items.length, target: g.key }));
  const restN = rest.reduce((n, g) => n + g.items.length, 0);
  if (restN > 0) chips.push({ key: `other:${BOARD_OTHER_GROUP}`, name: BOARD_OTHER_GROUP, n: restN, target: rest[0].key });
  return chips;
}

/** 讀屏用的一句:「多方集中:MLCC 8 檔、IC製造 5 檔、其他 12 檔」 */
export function groupSummaryText(chips: GroupChip[]): string {
  return `${GROUP_SUMMARY_LABEL}:${chips.map((c) => `${c.name} ${c.n} 檔`).join("、")}`;
}

/** 族群標頭的熱度:「成交為20日均 1.3 倍」 */
export function groupHeatText(vs20: number | null): string | null {
  return vs20 != null && Number.isFinite(vs20) ? `成交為20日均 ${vs20.toFixed(1)} 倍` : null;
}
