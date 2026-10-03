// 個股頁籌碼日報的分點標籤(純邏輯;BranchTag.tsx 畫、branchTags.test.ts 驗)。
//
// 標籤是「事實」不是「評價」:每一個都對得回 payload 裡一個數字或一份名單,
// 點一下就看得到那個數字。沒有資料就什麼都不標——缺鍵、未判定(NULL)都不得
// 印成反面(例如「非隔日沖」)。
//
// 優先序 GEO > DT > TRACKED > LOW/HIGH > SEAT;手機一列最多顯示 2 個、md 以上 3 個,
// 其餘只在點開的說明裡。
//
// 這支檔案不 import 任何「值」:node --test 認不得 "@/" 別名,而 Next 的型別檢查
// 又不接受非測試檔用 ".ts" 結尾的 import。所以 seatKind / compactSide 由呼叫端放進
// ctx(見 BranchTag.tsx 的 makeTagContext),這裡只用型別。
import type { CampKey, CompactSide, PctileModel, SeatKind, SideNumbers } from "@/lib/branchPctile";
import type { BranchTags } from "@/lib/types";

export type TagCode = "GEO" | "DT" | "TRACKED" | "LOW" | "HIGH" | "SEAT";
export type TagTone = "geo" | "daytrade" | "tracked" | "neutral" | "seat";

export interface Tag {
  code: TagCode;
  /** pill 上的字,例如「地緣」「買低 56%」。 */
  label: string;
  /** 點開後的一行說明,帶數字。 */
  note: string;
  tone: TagTone;
}

export interface TagContext {
  /** 舊 JSON 沒有 branch_tags:null/undefined,地緣/隔日沖/追蹤一律不標。 */
  tags: BranchTags | null | undefined;
  pctile: PctileModel | null;
  seatKind: (name: string) => SeatKind;
  compactSide: (kind: "buy" | "sell", stat: SideNumbers, minKnown: number) => CompactSide;
  /** 管理員從全站追蹤名單取消的分點(Supabase branch_track_list 'mute');讀不到時為空。 */
  listMuted?: ReadonlySet<string>;
  /** 管理員加入全站追蹤名單的分點('track')。 */
  listAdded?: ReadonlySet<string>;
}

/**
 * 有效追蹤 = (系統名單 − listMuted) ∪ listAdded。與 branchTrackResolve.ts 的
 * effectiveTracked 同一條規則(這支檔案不能 import 值,所以在這裡寫一次;
 * branchTags.test.ts 會拿兩者對照)。
 */
function trackedFor(name: string, server: boolean, ctx: TagContext): boolean {
  if (ctx.listAdded?.has(name)) return true;
  if (ctx.listMuted?.has(name)) return false;
  return server;
}

export const TAG_PRIORITY: TagCode[] = ["GEO", "DT", "TRACKED", "LOW", "HIGH", "SEAT"];
/** 手機(<md)一列最多顯示幾個;md 以上幾個。 */
export const MAX_VISIBLE_PHONE = 2;
export const MAX_VISIBLE_WIDE = 3;

const CAMP_ORDER: CampKey[] = ["short", "long"];

/** 「追蹤」定義的最後一句:名單由誰維護。 */
export const TRACKED_OVERRIDE_NOTE = "追蹤名單由管理員設定，全站一致。";

function fmtInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function pctText(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function hasName(list: unknown, name: string): boolean {
  return Array.isArray(list) && list.includes(name);
}

/** YYYY-MM-DD → M/D;格式不對原樣回傳。 */
export function fmtTagDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${Number(m[2])}/${Number(m[3])}` : iso;
}

function geoNote(rule: unknown): string {
  const where = rule === "district" ? "同區" : "同縣市";
  return `地緣：分點地址與公司登記地${where}（統計推測，不是內部人）`;
}

function daytradeRow(tags: BranchTags, name: string): [number, number] | null {
  const rows = tags.daytrade && typeof tags.daytrade === "object" ? tags.daytrade.rows : null;
  if (!rows || typeof rows !== "object") return null;
  const row = (rows as Record<string, unknown>)[name];
  if (!Array.isArray(row) || row.length < 2) return null;
  const [obs, paybacks] = row;
  if (!isCount(obs) || !isCount(paybacks) || obs === 0 || paybacks > obs) return null;
  return [obs, paybacks];
}

/** 買低/賣高:分點在「買點偏低、賣點偏高」排行裡(短線派優先,其次長線派)。 */
function pctileTag(name: string, side: "buy" | "sell", ctx: TagContext): Tag | null {
  const model = ctx.pctile;
  if (!model) return null;
  for (const key of CAMP_ORDER) {
    const camp = model.camps[key];
    if (!camp || !camp.available) continue;
    const stat = camp.rows.find((row) => row.name === name);
    if (!stat) continue;
    const numbers = side === "buy" ? stat.buy : stat.sell;
    const compact = ctx.compactSide(side, numbers, model.minKnown);
    if (compact.insufficient) return null;
    const verb = side === "buy" ? "買進" : "賣出";
    const bound = side === "buy"
      ? `≤${Math.round(model.lowMax * 100)}%`
      : `≥${Math.round(model.highMin * 100)}%`;
    const amount = numbers.lotsKnown != null && numbers.lotsHit != null
      ? `${fmtInt(numbers.lotsHit)}/${fmtInt(numbers.lotsKnown)} 張`
      : `${numbers.hit}/${numbers.known} 次`;
    const window = camp.windowDays ? `近 ${camp.windowDays} 日` : "統計窗口";
    return {
      code: side === "buy" ? "LOW" : "HIGH",
      label: compact.text,
      note: `${compact.text}：${verb} ${amount}在${window}區間 ${bound}，是進出位置不是賺賠`,
      tone: "neutral",
    };
  }
  return null;
}

/**
 * 某分點在某一側名單(買超 "buy"/賣超 "sell")上的標籤,已依優先序排好。
 * 回傳全部;要顯示幾個由畫面決定(MAX_VISIBLE_*)。
 */
export function branchTags(name: string, side: "buy" | "sell", ctx: TagContext): Tag[] {
  const out: Tag[] = [];
  const tags = ctx.tags && typeof ctx.tags === "object" ? ctx.tags : null;
  if (tags) {
    const geo = tags.geo && typeof tags.geo === "object" ? tags.geo : null;
    if (geo && geo.rule && hasName(geo.names, name)) {
      out.push({ code: "GEO", label: "地緣", note: geoNote(geo.rule), tone: "geo" });
    }
    const dt = daytradeRow(tags, name);
    if (dt) {
      out.push({
        code: "DT",
        label: "隔日沖",
        note: `隔日沖：${dt[1]}/${dt[0]} 次合格買超在次日前 15 大賣超中看得到回吐（下限；每日只公布前 15 大）`,
        tone: "daytrade",
      });
    }
  }
  const server = tags ? hasName(tags.tracked, name) : false;
  if (trackedFor(name, server, ctx)) {
    out.push({
      code: "TRACKED",
      label: "追蹤",
      note: server
        ? "追蹤：在追蹤名單裡（手動加入或演算法自動入選，或分點排行高分且不是隔日沖），與口袋名單「追蹤分點同買」同一份"
        : "追蹤：管理員加入全站追蹤名單的分點",
      tone: "tracked",
    });
  }
  const pctile = pctileTag(name, side, ctx);
  if (pctile) out.push(pctile);
  const seat = ctx.seatKind(name);
  if (seat) out.push({ code: "SEAT", label: seat.label, note: `${seat.label}：${seat.note}`, tone: "seat" });
  return out.sort((a, b) => TAG_PRIORITY.indexOf(a.code) - TAG_PRIORITY.indexOf(b.code));
}

export interface TagDefinition {
  label: string;
  text: string;
}

/** 「標籤怎麼看」展開的定義;數字全部來自 payload。沒有資料的標籤不列。 */
export function tagDefinitions(ctx: TagContext): TagDefinition[] {
  const defs: TagDefinition[] = [];
  const tags = ctx.tags && typeof ctx.tags === "object" ? ctx.tags : null;
  if (tags) {
    const rule = tags.geo?.rule;
    defs.push({
      label: "地緣",
      text: rule
        ? `分點地址與公司登記地${rule === "district" ? "同區（雙北以行政區為準）" : "同縣市"}；總公司與外資席位不算。統計推測，不是內部人。`
        : "這家公司的登記地址判不出縣市，這檔不標地緣。",
    });
    const dt = tags.daytrade;
    if (dt && isCount(dt.min_obs) && typeof dt.rate === "number") {
      const payback = typeof dt.payback === "number"
        ? `（次日賣出達當日淨買 ${pctText(dt.payback)} 以上）` : "";
      defs.push({
        label: "隔日沖",
        text: `這個分點在這檔股票至少 ${dt.min_obs} 次合格買超裡，≥${pctText(dt.rate)} 在次日前 15 大賣超中看得到回吐${payback}。`
          + `次數不足 ${dt.min_obs} 次的不判定、不標；看不見的出場不算，所以是下限。`,
      });
    }
  }
  if (tags || ctx.listAdded?.size) {
    defs.push({
      label: "追蹤",
      text: "在追蹤名單裡：手動加入或演算法自動入選，或分點排行高分且不是隔日沖。與口袋名單「追蹤分點同買」同一份名單。"
        + TRACKED_OVERRIDE_NOTE,
    });
  }
  const model = ctx.pctile;
  if (model) {
    const days = model.camps.short?.windowDays;
    defs.push({
      label: "買低／賣高",
      text: `只在「買點偏低、賣點偏高」排行裡的分點才有：買進日收盤在${days ? `近 ${days} 日` : "統計窗口"}區間 ≤${Math.round(model.lowMax * 100)}%（賣出 ≥${Math.round(model.highMin * 100)}%）的佔比。`
        + "買超名單看買低、賣超名單看賣高；是進出位置，不是賺賠。",
    });
  }
  defs.push({
    label: "總公司／外資",
    text: "券商總公司或外資席位：常混著自營、權證避險或法人帳戶的量，不一定是單一主力。",
  });
  return defs;
}

/** 定義下方的資料日與涵蓋範圍說明。 */
export function tagLegendFootnote(ctx: TagContext): string {
  const asOf = ctx.tags && typeof ctx.tags.as_of === "string" ? ctx.tags.as_of : null;
  const date = asOf
    ? `標籤資料日 ${fmtTagDate(asOf)}（地緣地址每週一更新；隔日沖為全部可得歷史）。`
    : "";
  return `${date}分點資料只涵蓋每日前 15 大買賣超，沒標不代表沒有這種情形。`;
}
