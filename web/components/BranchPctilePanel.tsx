"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Search } from "lucide-react";

import {
  CAMP_KEYS,
  CAMP_NAMES,
  DEFAULT_VISIBLE,
  baseLegend,
  campDefinition,
  campShortDefinition,
  campStatus,
  campTabLabel,
  campWindowLabel,
  compactSide,
  daytradeSummary,
  normalizeBranchPctile,
  searchBranches,
  sideView,
  visibleRows,
  type CampKey,
  type CampModel,
  type CampStat,
  type CompactSide,
  type PctileModel,
  type SideView,
} from "@/lib/branchPctile";
import { branchTags as tagsFor, type Tag, type TagContext } from "@/lib/branchTags";
import { useBranchTrack } from "@/lib/branchTrackList";
import type { BranchPctileCounts, BranchTags } from "@/lib/types";
import { cn, segBtnClass } from "@/lib/utils";
import { BranchTagList, BranchTagNote, makeTagContext } from "@/components/BranchTag";
import SectionHeader from "@/components/SectionHeader";

/**
 * 個股頁：分點在這檔股票的買點／賣點價格分位紀錄(短線派 20 日、長線派 120 日)。
 *
 * 為什麼沒有徽章、沒有分數。2026-09-08 在修好還原因子的資料上重跑方向 battery,
 * 結論有兩半:**群體層級的傾向為真**(樣本外存活 pair 以 obs/exp 2.40 勝過該股自身
 * 基準,張數配對安慰劑只有 0.91);**但「這一對」這個標籤不可重現**(嚴格旗標在評估
 * 半段只有 2.0% 重新賺回來,那個比率把交易量混進了持續性)。所以這一節只呈現
 * 次數、張數與該股自身同一項比率,由讀的人判斷,不替他下結論。
 *
 * 2026-10-02 起依**張數加權、向該股基準收縮**排序(見 json_export
 * `_rank_branch_pctile_rows_by_lots`):次數把「低檔一口氣買 836 張」和「買 5 張」
 * 記成同樣一次,而原始比率讓 6/8 這種小樣本登頂。此排序方式尚未經過回測檢定,
 * 畫面上照實講。
 *
 * 顏色刻意中性(不用紅綠):這是計次與張數,不是漲跌,也不是損益。
 */

const CAMP_STORAGE_KEY = "trever.branchPctile.camp";

/** 次日回吐的定義,放進卡片的展開說明。 */
const DAYTRADE_DEFINITION =
  "合格買超日的次日，同一分點又出現在這檔股票的前 15 大賣超，"
  + "且賣出張數達當日淨買的七成以上";

function readStoredCamp(): CampKey | null {
  try {
    const value = window.localStorage.getItem(CAMP_STORAGE_KEY);
    return value === "short" || value === "long" ? value : null;
  } catch {
    return null;
  }
}

function storeCamp(value: CampKey) {
  try {
    window.localStorage.setItem(CAMP_STORAGE_KEY, value);
  } catch {
    // 私密視窗或封鎖網站資料時寫不進去:下次回到預設的短線派,不影響畫面。
  }
}

/**
 * 舊 JSON(v1)配新程式碼是常態——程式碼會早於下一次 VPS 匯出上線——所以 v1 照樣
 * 用次數畫出來;其他版本或缺鍵整節不渲染。
 */
export default function BranchPctilePanel({
  data,
  onOpenBranch,
  branchTags,
}: {
  data: BranchPctileCounts | undefined;
  onOpenBranch?: (name: string) => void;
  /** 分點標籤(地緣/隔日沖/追蹤);舊 JSON 沒有時只剩席位標籤。 */
  branchTags?: BranchTags;
}) {
  const model = useMemo(() => normalizeBranchPctile(data), [data]);
  const { muted, added } = useBranchTrack();
  const tagCtx = useMemo(
    () => makeTagContext(branchTags, data, { muted, added }),
    [branchTags, data, muted, added],
  );
  const [camp, setCamp] = useState<CampKey>("short");
  const [expanded, setExpanded] = useState(false);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");

  // 上次選的派別只在瀏覽器端讀,避免靜態輸出與水合不一致。
  useEffect(() => {
    const stored = readStoredCamp();
    if (stored) setCamp(stored);
  }, []);

  if (!model) return null;

  const hasLong = model.camps.long !== null;
  const activeKey: CampKey = hasLong ? camp : "short";
  const active = model.camps[activeKey] as CampModel;
  const windowLabel = model.windowFrom && model.asOf
    ? `${model.windowFrom} ～ ${model.asOf}${model.marketDays ? `（${model.marketDays} 個交易日）` : ""}`
    : "區間未提供（舊版資料）";
  const search = searchBranches(model, query);
  const searching = query.trim().length > 0;

  const choose = (key: CampKey) => {
    setCamp(key);
    setExpanded(false);
    setOpenRow(null);
    storeCamp(key);
  };
  const toggleSearch = () => {
    if (searchOpen) setQuery("");
    setSearchOpen((v) => !v);
  };

  return (
    <section
      aria-labelledby="branch-pctile-heading"
      className="mt-3.5 grid min-w-0 max-w-full gap-2.5 overflow-hidden rounded-[var(--r-lg)] border border-border bg-card p-3 shadow-[var(--shadow-card)]"
    >
      <SectionHeader
        family="chips"
        id="branch-pctile-heading"
        title="買點偏低、賣點偏高的分點"
        meta={<>統計窗口 {windowLabel}</>}
        right={
          <button
            type="button"
            onClick={toggleSearch}
            aria-expanded={searchOpen}
            aria-controls="branch-pctile-search"
            className={cn(segBtnClass(searchOpen), "inline-flex min-h-9 shrink-0 items-center gap-1 border border-border")}
          >
            <Search size={13} aria-hidden />
            {searchOpen ? "收起" : "搜尋"}
          </button>
        }
      />

      {hasLong && (
        <div role="tablist" aria-label="分位區間" className="grid grid-cols-2 gap-1 rounded-[var(--r-md)] bg-secondary p-1">
          {CAMP_KEYS.map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={activeKey === key}
              onClick={() => choose(key)}
              className={`min-h-11 rounded-[var(--r-sm)] px-2 py-1.5 text-[12.5px] font-semibold leading-tight transition-colors ${
                activeKey === key
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"
              }`}
            >
              <span aria-hidden="true" className="block">{CAMP_NAMES[key]}</span>
              <span aria-hidden="true" className="block text-[11px] font-normal">{campWindowLabel(model, key)}</span>
              <span className="sr-only">{campTabLabel(model, key)}</span>
            </button>
          ))}
        </div>
      )}
      <p className="text-[11.5px] leading-snug text-foreground">
        {!hasLong && <span className="font-semibold">{CAMP_NAMES.short}：</span>}
        {campShortDefinition(model, activeKey)}
      </p>

      {searchOpen && (
        <label id="branch-pctile-search" className="grid gap-1">
          <span className="sr-only">搜尋分點名稱</span>
          <input
            type="search"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜尋分點名稱（含未進排行的分點）"
            className="h-11 w-full rounded-[var(--r-md)] border border-border bg-background px-3 text-[13px] text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40"
          />
        </label>
      )}

      {searching ? (
        <SearchResults model={model} hits={search.results} total={search.total} onOpenBranch={onOpenBranch} tagCtx={tagCtx} />
      ) : (
        <CampList
          model={model}
          tagCtx={tagCtx}
          camp={active}
          expanded={expanded}
          onExpand={() => setExpanded(true)}
          openRow={openRow}
          onToggleRow={(name) => setOpenRow((cur) => (cur === name ? null : name))}
          onOpenBranch={onOpenBranch}
        />
      )}

      <HowToRead model={model} camp={activeKey} />
    </section>
  );
}

/** 「看進出明細」:開啟與其他兩節同一個分點下鑽畫面。 */
function DrillButton({ name, onOpenBranch }: { name: string; onOpenBranch?: (name: string) => void }) {
  if (!onOpenBranch) return null;
  return (
    <button
      type="button"
      onClick={() => onOpenBranch(name)}
      className="min-h-11 rounded-[var(--r-md)] border border-border bg-card px-3 text-[13px] font-semibold text-foreground hover:bg-secondary"
    >
      看進出明細
    </button>
  );
}

function CampList({
  model,
  tagCtx,
  camp,
  expanded,
  onExpand,
  openRow,
  onToggleRow,
  onOpenBranch,
}: {
  model: PctileModel;
  tagCtx: TagContext;
  camp: CampModel;
  expanded: boolean;
  onExpand: () => void;
  openRow: string | null;
  onToggleRow: (name: string) => void;
  onOpenBranch?: (name: string) => void;
}) {
  if (!camp.available) {
    return (
      <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
        {CAMP_NAMES[camp.key]}的資料尚未產生，下一次夜間計算後會出現。這是還沒算，不是沒有分點。
      </p>
    );
  }
  if (camp.rows.length === 0) {
    return (
      <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
        窗口內這檔股票沒有任何分點累積到至少 {model.minKnown} 次分位可知的買進紀錄
        {model.lotsRanked ? "" : "（舊版排序：買、賣兩側各要求）"}，
        所以沒有可以放上這把尺比較的對象。這是次數不足，不是資料載入失敗。可以用上方搜尋查任一分點。
      </p>
    );
  }
  const rows = visibleRows(camp.rows, expanded);
  return (
    <div className="grid gap-2">
      <ol className="grid gap-1.5">
        {rows.map((stat, index) => (
          <BranchRow
            key={stat.name}
            model={model}
            tags={panelTags(stat.name, tagCtx)}
            camp={camp}
            stat={stat}
            position={index + 1}
            open={openRow === stat.name}
            onToggle={() => onToggleRow(stat.name)}
            onOpenBranch={onOpenBranch}
          />
        ))}
      </ol>
      {!expanded && camp.rows.length > DEFAULT_VISIBLE && (
        <button
          type="button"
          onClick={onExpand}
          className="min-h-11 rounded-[var(--r-md)] border border-border bg-background px-3 text-[13px] font-semibold text-foreground hover:bg-secondary"
        >
          顯示全部（{camp.rows.length}）
        </button>
      )}
    </div>
  );
}

/**
 * 這一節的分點標籤:地緣/隔日沖/追蹤/席位(總公司外資只標示、不排除)。
 * 買低/賣高不重複標——每列右側本來就是那兩個數字。
 */
function panelTags(name: string, ctx: TagContext): Tag[] {
  return tagsFor(name, "buy", ctx).filter((t) => t.code !== "LOW" && t.code !== "HIGH");
}

function SideChip({ side }: { side: CompactSide }) {
  return (
    <span
      className={cn(
        "num shrink-0 whitespace-nowrap rounded-md bg-secondary px-1.5 py-0.5 text-[12px]",
        side.insufficient ? "text-muted-foreground" : "font-semibold text-foreground",
      )}
    >
      {side.text}
    </span>
  );
}

/**
 * 一行一個分點(名次 · 名稱 · 買低 · 賣高);點一下在原地展開細節——長條對此股基準、
 * 張數與次數、次日回吐,以及「看進出明細」。
 */
function BranchRow({
  model,
  tags,
  camp,
  stat,
  position,
  open,
  onToggle,
  onOpenBranch,
}: {
  model: PctileModel;
  tags: Tag[];
  camp: CampModel;
  stat: CampStat;
  position: number;
  open: boolean;
  onToggle: () => void;
  onOpenBranch?: (name: string) => void;
}) {
  const daytrade = camp.key === "short" ? daytradeSummary(model, stat) : null;
  const legend = baseLegend(camp);
  const detailId = `pctile-row-${camp.key}-${position}`;
  const [tagOpen, setTagOpen] = useState<string | null>(null);
  return (
    <li className="min-w-0 rounded-[var(--r-md)] border border-border bg-background">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={detailId}
        className="flex min-h-11 w-full min-w-0 items-center gap-1.5 px-2.5 py-1.5 text-left"
      >
        <span className="num w-4 shrink-0 text-[11.5px] text-muted-foreground">{position}</span>
        {/* 放不下時標籤換到名稱下一行,不擠掉名稱、不壓到右側數字 */}
        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1 gap-y-0.5">
          <span className="min-w-0 max-w-full truncate text-[13.5px] font-semibold text-foreground" title={stat.name}>
            {stat.name}
          </span>
          <BranchTagList tags={tags} open={tagOpen} onToggle={(key) => setTagOpen((cur) => (cur === key ? null : key))} />
        </span>
        <SideChip side={compactSide("buy", stat.buy, model.minKnown)} />
        <SideChip side={compactSide("sell", stat.sell, model.minKnown)} />
        <ChevronDown
          size={14}
          aria-hidden
          className={cn("shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      <BranchTagNote tags={tags} open={tagOpen} className="border-t border-border px-2.5 py-1.5" />
      {open && (
        <div id={detailId} className="grid gap-1.5 border-t border-border px-2.5 pt-2 pb-2.5">
          <SideRow view={sideView("buy", stat.buy, camp.base.buy, model.minKnown)} />
          <SideRow view={sideView("sell", stat.sell, camp.base.sell, model.minKnown)} />
          {legend && <p className="text-[11px] leading-snug text-muted-foreground">長條＝該分點的比率；{legend}</p>}
          {daytrade && (
            <p className="text-[11.5px] leading-snug text-muted-foreground">
              <span className="font-semibold text-foreground">次日回吐</span> {daytrade}
            </p>
          )}
          <DrillButton name={stat.name} onOpenBranch={onOpenBranch} />
        </div>
      )}
    </li>
  );
}

/** 一側:主要一行(張數)＋小字(次數)＋一條細長條,刻線是此股全體分點。 */
function SideRow({ view }: { view: SideView }) {
  return (
    <div className="grid min-w-0 gap-1" role="group" aria-label={`${view.label}${view.detail ? `，${view.detail}` : ""}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0">
        <span className={`num text-[12.5px] ${view.insufficient ? "text-muted-foreground" : "font-semibold text-foreground"}`}>
          {view.label}
        </span>
        {view.detail && <span className="num text-[11px] text-muted-foreground">{view.detail}</span>}
      </div>
      {!view.insufficient && (
        <div className="relative h-1.5 w-full rounded-full bg-secondary" aria-hidden="true">
          {view.pct != null && (
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-primary/60"
              style={{ width: `${Math.min(100, Math.max(0, view.pct))}%` }}
            />
          )}
          {view.basePct != null && (
            <div
              className="absolute -top-1 h-3.5 w-0.5 rounded-full bg-[color:var(--ink-2)]"
              style={{ left: `${Math.min(100, Math.max(0, view.basePct))}%`, transform: "translateX(-1px)" }}
            />
          )}
        </div>
      )}
    </div>
  );
}

function SearchResults({
  model,
  hits,
  total,
  onOpenBranch,
  tagCtx,
}: {
  model: PctileModel;
  hits: ReturnType<typeof searchBranches>["results"];
  total: number;
  onOpenBranch?: (name: string) => void;
  tagCtx: TagContext;
}) {
  const [tagOpen, setTagOpen] = useState<{ name: string; key: string } | null>(null);
  if (hits.length === 0) {
    return (
      <p className="rounded-[var(--r-md)] border border-border bg-secondary px-3 py-3 text-[12.5px] leading-relaxed text-muted-foreground">
        找不到符合的分點：窗口內它在這檔股票的可判讀紀錄少於 2 次（或不在可見張數前 150 名），
        沒有可比較的數字。只記錄進入當日前 15 大買賣超的分點。
      </p>
    );
  }
  return (
    <div className="grid gap-2">
      {total > hits.length && (
        <p className="text-[11px] text-muted-foreground">共 {total} 個符合，只列前 {hits.length} 個；請輸入更完整的名稱。</p>
      )}
      <ul className="grid gap-2">
        {hits.map((hit) => {
          const tags = panelTags(hit.name, tagCtx);
          const open = tagOpen?.name === hit.name ? tagOpen.key : null;
          return (
          <li key={hit.name} className="grid gap-2 rounded-[var(--r-md)] border border-border bg-background px-3 py-2">
            <h3 className="flex min-w-0 items-center gap-1 text-[13.5px] font-semibold text-foreground">
              <span className="min-w-0 truncate" title={hit.name}>{hit.name}</span>
              <BranchTagList
                tags={tags}
                open={open}
                onToggle={(key) =>
                  setTagOpen((cur) => (cur?.name === hit.name && cur.key === key ? null : { name: hit.name, key }))
                }
              />
            </h3>
            <BranchTagNote tags={tags} open={open} />
            {CAMP_KEYS.filter((key) => model.camps[key] !== null).map((key) => {
              const camp = model.camps[key] as CampModel;
              const campHit = hit.camps[key];
              return (
                <div key={key} className="grid gap-1 border-t border-border pt-1.5 first:border-t-0 first:pt-0">
                  <p className="text-[11.5px] font-semibold text-muted-foreground">{campStatus(model, key, campHit)}</p>
                  {campHit?.stat && camp.available && (
                    <>
                      <SideRow view={sideView("buy", campHit.stat.buy, camp.base.buy, model.minKnown)} />
                      <SideRow view={sideView("sell", campHit.stat.sell, camp.base.sell, model.minKnown)} />
                    </>
                  )}
                </div>
              );
            })}
            <DrillButton name={hit.name} onOpenBranch={onOpenBranch} />
          </li>
          );
        })}
      </ul>
    </div>
  );
}

/** 原本三段長說明收進一個「怎麼看」,手機上不再佔掉整個畫面。 */
function HowToRead({ model, camp }: { model: PctileModel; camp: CampKey }) {
  const k = (camp: CampModel | null) =>
    camp && camp.shrinkK.buy != null
      ? `${CAMP_NAMES[camp.key]}買側 K＝${Math.round(camp.shrinkK.buy).toLocaleString("en-US")} 張`
        + (camp.shrinkK.sell != null ? `、賣側 K＝${Math.round(camp.shrinkK.sell).toLocaleString("en-US")} 張` : "")
      : null;
  const kText = [k(model.camps.short), k(model.camps.long)].filter(Boolean).join("；");
  return (
    <details className="rounded-[var(--r-md)] border border-border bg-secondary/60 px-3 text-[11.5px] leading-relaxed text-muted-foreground">
      <summary className="cursor-pointer select-none py-2.5 text-[12px] font-semibold text-foreground">怎麼看</summary>
      <div className="grid gap-1.5 pb-2.5">
        <p>{campDefinition(model, camp)}每列右側是該分點的佔比；點一列可看長條（刻線＝此股全體分點）、張數與次數，以及它的進出明細。</p>
        <p>
          {model.lotsRanked
            ? "依張數加權排序（2026-10 起；此排序方式尚未經過回測檢定）。"
            : "依次數排序（舊版資料；下一次夜間計算後改為依張數）。"}
        </p>
        {camp === "short" && model.minDaytradeObs != null && (
          <p>次日回吐＝{DAYTRADE_DEFINITION}。出場多半落在看不見的成交裡，這個次數是下限。</p>
        )}
        <p>
          這是統計窗口內累積下來的紀錄，不是今日盤後名單；分點列在這裡是因為它在窗口內的進出，
          與它今天有沒有交易無關。
        </p>
        <p>
          資料只記錄當日進入這檔股票前 15 大買超或賣超的分點，所以次數與張數是下限，不是完整紀錄。
          持股者的出場常是前 15 大以外的小量賣出，看不見，因此賣出紀錄不足時不列比率，也不影響排序。
        </p>
        <p>
          張數＝同一段連續買進（或賣出）每天淨張數的加總；位置只看那一段的第一天收盤。
          刻線是這檔股票全體分點的同一項比率——買、賣兩側的基準本來就不同，只看單一百分比會誤讀。
        </p>
        {model.lotsRanked && (
          <p>
            排序：把每個分點的張數比率往此股整體比率拉近，張數越少拉得越多（拉力 K＝張數加權中位數（此股一半的可見張數來自至少這麼大的分點）
            {kText ? `；${kText}` : ""}），再看高出此股多少；買進紀錄至少 {model.minKnown} 次才入選，
            賣出紀錄達 {model.minKnown} 次才計入賣側，賣側依可見出場比例（賣出張數 ÷ 買進張數）計入，
            看不到出場的長抱不扣分。此排序方式尚未經過回測檢定。
          </p>
        )}
        <p>
          全部是進出場時點的價格位置與張數，買、賣兩側各自獨立計數，沒有配對成一筆交易，
          不是損益，也不代表之後會延續。
        </p>
      </div>
    </details>
  );
}
