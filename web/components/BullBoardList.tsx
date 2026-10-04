import { Clock } from "lucide-react";

import BullBoardCard from "@/components/BullBoardCard";
import SectionHeader from "@/components/SectionHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { BOARD_DEFINITION, BOARD_TAB_LABEL, boardView } from "@/lib/bullBoard";
import type { BullBoardJson, RadarJson } from "@/lib/types";

const CARD = "grid min-w-0 gap-2 rounded-[var(--r-lg)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)]";
const GRID = "grid grid-cols-1 gap-2.5 pb-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

/**
 * 首頁「多方榜」分頁(docs/48):頁首卡(取代分頁下的說明卡)→ 狀態句 → 卡片格。
 * board:undefined = 還在載入;null = 檔不存在/讀取失敗(這一版沒算過)。
 * 所有句子由 lib/bullBoard.ts 的純函式產生(有測試蓋住)。
 */
export default function BullBoardList({
  board,
  radar,
}: {
  board: BullBoardJson | null | undefined;
  radar: Pick<RadarJson, "data_date" | "generated_at">;
}) {
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
        <div className={GRID}>
          {v.board.entries.map((e, i) => (
            <BullBoardCard key={e.id} e={e} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
