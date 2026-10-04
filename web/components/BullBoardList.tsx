"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";

import BullBoardCard from "@/components/BullBoardCard";
import { ScrollHint } from "@/components/ScrollHint";
import SectionHeader from "@/components/SectionHeader";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BOARD_DEFINITION,
  BOARD_TAB_LABEL,
  BOARD_VIEW_LABEL,
  GROUP_SUMMARY_LABEL,
  boardView,
  groupBoardEntries,
  groupHeatText,
  groupSummary,
  groupSummaryText,
  type BoardGroup,
  type BoardViewMode,
} from "@/lib/bullBoard";
import type { BullBoardJson, RadarJson } from "@/lib/types";
import { cn, pillTabClass } from "@/lib/utils";

const CARD = "grid min-w-0 gap-2 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]";
const COLS = "grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";
const GRID = `${COLS} pb-4`;
const LS_BOARD_VIEW = "trever.home.boardView.v1";
const VIEW_MODES: BoardViewMode[] = ["facts", "group"];

type RadarCtx = Pick<RadarJson, "data_date" | "generated_at"> & Partial<Pick<RadarJson, "stocks" | "themes" | "sectors">>;

/**
 * 首頁「多方榜」分頁(docs/48):頁首卡 → 狀態句 → 族群分布 →「事實｜族群」切換 → 卡片格。
 * board:undefined = 還在載入;null = 檔不存在/讀取失敗(這一版沒算過)。
 * 所有句子由 lib/bullBoard.ts 的純函式產生(有測試蓋住)。族群只重排畫面,不改榜單順序。
 */
export default function BullBoardList({ board, radar }: { board: BullBoardJson | null | undefined; radar: RadarCtx }) {
  const [mode, setMode] = useState<BoardViewMode>("facts");
  // 點族群分布的膠囊:切到族群檢視後捲到那一組
  const [jump, setJump] = useState<string | null>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(LS_BOARD_VIEW);
      if (raw === "facts" || raw === "group") setMode(raw);
    } catch {
      /* 私密視窗或封鎖網站資料:維持預設「事實」 */
    }
  }, []);

  useEffect(() => {
    if (jump == null || mode !== "group") return;
    document.querySelector(`[data-group-key="${CSS.escape(jump)}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    setJump(null);
  }, [jump, mode]);

  const chooseMode = (next: BoardViewMode) => {
    setMode(next);
    try {
      localStorage.setItem(LS_BOARD_VIEW, next);
    } catch {
      /* 寫不進去只是下次回到預設 */
    }
  };

  if (board === undefined) {
    return (
      <div className="grid gap-2.5 pb-4">
        <Skeleton className="h-[118px] rounded-[var(--r-lg)]" />
        <div className={GRID}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-[180px] rounded-[var(--r-lg)]" />
          ))}
        </div>
      </div>
    );
  }
  const v = boardView(board, radar);
  const groups = v.kind === "ready" && !v.empty ? groupBoardEntries(v.board.entries, radar) : [];
  const chips = groupSummary(groups);
  return (
    <div data-testid="bull-board" className="grid min-w-0 gap-2.5 animate-[fadeUp_0.35s_ease_backwards]">
      <section aria-labelledby="bull-board-heading" className={CARD}>
        <SectionHeader
          family="price"
          as="h2"
          id="bull-board-heading"
          title={BOARD_TAB_LABEL}
          meta={v.kind === "ready" ? <>資料日 <span className="num">{v.dateLabel}</span></> : undefined}
        />
        <p className="text-[12.5px] leading-relaxed text-[color:var(--ink-2)]">{BOARD_DEFINITION}</p>
        {v.kind === "ready" && (
          <>
            <p data-testid="bull-board-count" className="num text-[13px] font-semibold text-foreground">
              {v.countLine}
            </p>
            <p className="num text-[11.5px] leading-snug text-muted-foreground">{v.inputsLine}</p>
            <p className="text-[11.5px] leading-snug text-muted-foreground">{v.recordLine}</p>
          </>
        )}
      </section>

      {v.kind === "ready" && v.notices.length > 0 && (
        <ul data-testid="bull-board-notices" className="grid gap-1.5 rounded-[var(--r-md)] border border-warn/30 bg-warn/5 px-3 py-2">
          {v.notices.map((n) => (
            <li key={n.key} data-notice={n.key} className="flex items-start gap-1.5 text-[12.5px] leading-snug text-foreground">
              <Clock size={13} strokeWidth={1.8} className="mt-[3px] shrink-0 text-warn" aria-hidden />
              <span>{n.text}</span>
            </li>
          ))}
        </ul>
      )}

      {v.kind === "missing" ? (
        <p data-testid="bull-board-missing" className="mx-auto max-w-md py-10 text-center text-sm leading-relaxed text-muted-foreground">
          {v.text}
        </p>
      ) : v.empty ? (
        <p data-testid="bull-board-empty" className="mx-auto max-w-md py-10 text-center text-sm leading-relaxed text-muted-foreground">
          {v.empty}
        </p>
      ) : (
        <>
          {chips.length > 0 && (
            <nav data-testid="bull-board-summary" aria-label={groupSummaryText(chips)} className="-my-1 flex min-w-0 items-center gap-2">
              <span className="shrink-0 text-[12px] text-muted-foreground">{GROUP_SUMMARY_LABEL}</span>
              <ScrollHint
                variant="plain"
                fade="background"
                peekId="bull-board-groups"
                wrapperClassName="flex-1"
                className="flex gap-1.5 overflow-x-auto"
              >
                {chips.map((c) => (
                  <button
                    key={c.key}
                    type="button"
                    data-testid="bull-board-chip"
                    aria-label={`${c.name} ${c.n} 檔`}
                    onClick={() => {
                      chooseMode("group");
                      setJump(c.target);
                    }}
                    className="group flex min-h-11 shrink-0 cursor-pointer items-center touch-manipulation"
                  >
                    <span className="flex items-center gap-1 whitespace-nowrap rounded-full border border-border bg-card px-2.5 py-1 text-[12.5px] text-foreground transition-colors group-hover:border-[color:var(--border-strong)] group-hover:bg-secondary">
                      {c.name}
                      <span className="num font-semibold text-muted-foreground">{c.n}</span>
                    </span>
                  </button>
                ))}
              </ScrollHint>
            </nav>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-muted-foreground">{"檢視"}</span>
            <div role="tablist" aria-label="多方榜檢視" className="flex gap-0.5 rounded-full border border-border bg-card p-[3px]">
              {VIEW_MODES.map((m) => (
                <button
                  key={m}
                  type="button"
                  role="tab"
                  aria-selected={mode === m}
                  data-testid={`bull-board-view-${m}`}
                  className={cn("min-h-11 cursor-pointer", pillTabClass(mode === m))}
                  onClick={() => chooseMode(m)}
                  title={m === "group" ? "依今日最熱題材分組(沒有熱門題材的依產業),一檔只出現一次" : "依多方事實條數排列"}
                >
                  {BOARD_VIEW_LABEL[m]}
                </button>
              ))}
            </div>
          </div>
          {mode === "group" ? (
            <BoardGroups groups={groups} />
          ) : (
            <div className={GRID}>
              {v.board.entries.map((e, i) => (
                <BullBoardCard key={e.id} e={e} index={i} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** 族群檢視:全部展開,每組標頭黏在頂端直到該組捲完(樣式同首頁「題材」排序的標頭,不收合)。 */
function BoardGroups({ groups }: { groups: BoardGroup[] }) {
  let cardIndex = 0;
  return (
    <div data-testid="bull-board-groups" className="grid min-w-0 gap-2.5 pb-4">
      {groups.map((g) => {
        const heat = groupHeatText(g.vs20);
        return (
          <section
            key={g.key}
            data-group-key={g.key}
            aria-label={`${g.name} ${g.items.length} 檔`}
            className="grid min-w-0 scroll-mt-[var(--header-offset)] gap-2.5"
          >
            <div
              data-testid="bull-board-group"
              className="sticky top-[var(--header-offset)] z-20 flex min-h-11 min-w-0 items-center gap-2 rounded-[var(--r-md)] border border-border bg-background/92 px-3 py-2 shadow-[var(--shadow-card)] backdrop-blur-md md:min-h-9 md:py-1.5"
            >
              <h3 className="min-w-0 truncate text-[13.5px] font-semibold text-foreground" title={g.name}>
                {g.name}
              </h3>
              {g.kind === "industry" && <span className="shrink-0 text-[11px] text-muted-foreground">{"產業"}</span>}
              {heat && <span className="num min-w-0 truncate text-[11.5px] text-muted-foreground">{heat}</span>}
              <span className="num ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
                {g.items.length}
              </span>
            </div>
            <div className={COLS}>
              {g.items.map(({ e }) => (
                <BullBoardCard key={e.id} e={e} index={cardIndex++} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
