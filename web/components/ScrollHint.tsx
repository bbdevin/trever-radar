"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type HTMLAttributes, type ReactNode } from "react";

import { scrollEdges, scrollTargetForItem, type ScrollEdges } from "@/lib/scrollHint";
import { cn } from "@/lib/utils";

/**
 * 手機橫滑列的「右邊還有」提示(使用者 2026-10-04:首頁/個股分頁在手機上要看得出可以往右滑)。
 *
 * 包住原本的捲動容器:`role`/`aria-*`/className 都直接落在同一個捲動元素上(tablist 語意不變),
 * 外層只多一個 relative 定位框放邊緣漸層與箭頭鈕。沒有溢出(桌機多半如此)時什麼都不畫。
 *
 * - 漸層從透明漸到容器底色(`fade`:pill 列是 card、直接放在頁面上的列是 background),兩主題都跟 token 走。
 * - 箭頭鈕用主色(docs/19 規則 10:不可只有灰),點一下捲約 70% 寬;按鈕只佔漸層區,其餘照常可點。
 * - `activeKey` 改變時把選中項(aria-selected/aria-pressed/data-active)捲進可視範圍——只捲這個容器,
 *   不用 scrollIntoView(會連頁面一起垂直捲,個股分頁列是 sticky)。
 * - `peekId`:每列第一次出現時輕推 28px 再回來一次(localStorage 記住;減少動態偏好時不做)。
 * - `variant="table"`(2026-10-04):橫向可捲的資料表。漸層鋪滿整個表高,箭頭鈕起始對齊表頭列,
 *   表格比畫面高時以 sticky 停在視窗垂直中線、跟著表捲到底;保留原生捲軸(桌機滑鼠仍可拖)。
 *   捲動容器自帶 1px 邊框與圓角時傳 `edgeRadius`(如 `var(--r-lg)`),提示層內縮 1px 並跟著圓角。
 */

type Fade = "card" | "background";

const FADE_VAR: Record<Fade, string> = {
  card: "var(--card)",
  background: "var(--background)",
};

/** 漸層寬度;選中項自動捲動時也讓開這麼寬,免得被箭頭蓋住。 */
const HINT_WIDTH = 44;
const PEEK_PX = 28;
const PEEK_PREFIX = "trever.scrollHint.peek.";

type Props = HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  /** 外層定位框的 class:原本放在捲動容器上的「外部版面」class(寬度、shrink、margin)搬到這裡。 */
  wrapperClassName?: string;
  fade?: Fade;
  /** pill:容器有 1px 邊框與全圓角,提示層內縮 1px 並跟著圓角;plain:無邊框直角;table:見上。 */
  variant?: "pill" | "plain" | "table";
  /** 僅 table:捲動容器的圓角(有 1px 邊框時才傳)。 */
  edgeRadius?: string;
  activeKey?: unknown;
  peekId?: string;
};

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** 選中項相對捲動內容的左緣(捲動容器本身是 relative,所以是 offsetParent)。 */
function offsetWithin(el: HTMLElement, container: HTMLElement) {
  let left = 0;
  let node: HTMLElement | null = el;
  while (node && node !== container) {
    left += node.offsetLeft;
    node = node.offsetParent as HTMLElement | null;
  }
  return left;
}

export function ScrollHint({
  children,
  wrapperClassName,
  className,
  fade = "card",
  variant = "pill",
  edgeRadius,
  activeKey,
  peekId,
  ...rest
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState<ScrollEdges>({ left: false, right: false });
  const firstAlign = useRef(true);

  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const next = scrollEdges(el.scrollLeft, el.clientWidth, el.scrollWidth);
    setEdges((prev) => (prev.left === next.left && prev.right === next.right ? prev : next));
  }, []);

  // 捲動(rAF 節流)+ 尺寸:容器與每個子項都觀察——字級偏好、資料載入後多出分頁,都會讓內容變寬但容器不變。
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    };
    el.addEventListener("scroll", schedule, { passive: true });
    let ro: ResizeObserver | null = null;
    let mo: MutationObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(schedule);
      const observeAll = () => {
        ro!.disconnect();
        ro!.observe(el);
        for (const child of Array.from(el.children)) ro!.observe(child);
      };
      observeAll();
      mo = new MutationObserver(() => {
        observeAll();
        schedule();
      });
      mo.observe(el, { childList: true });
    } else {
      window.addEventListener("resize", schedule);
    }
    measure();
    return () => {
      if (frame) cancelAnimationFrame(frame);
      el.removeEventListener("scroll", schedule);
      ro?.disconnect();
      mo?.disconnect();
      window.removeEventListener("resize", schedule);
    };
  }, [measure]);

  // 選中項捲進可視範圍(首次瞬間定位,之後平滑)。
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const active = el.querySelector<HTMLElement>('[aria-selected="true"], [aria-pressed="true"], [data-active="true"]');
    const instant = firstAlign.current || prefersReducedMotion();
    firstAlign.current = false;
    if (!active) return;
    const target = scrollTargetForItem(
      offsetWithin(active, el),
      active.offsetWidth,
      el.scrollLeft,
      el.clientWidth,
      el.scrollWidth,
      HINT_WIDTH,
    );
    if (target != null) el.scrollTo({ left: target, behavior: instant ? "auto" : "smooth" });
  }, [activeKey]);

  // 第一次看到這列且確實可以往右滑:輕推一下示意。使用者一碰就取消。
  // 計時器掛在 ref 上、只在卸載時清:推出去之後左側提示出現會改 edges,不能因此把「推回來」取消掉。
  const peek = useRef<{ started: boolean; timers: number[]; cancel?: () => void }>({ started: false, timers: [] });
  useEffect(() => {
    const p = peek.current;
    return () => {
      p.timers.forEach((t) => window.clearTimeout(t));
      p.cancel?.();
    };
  }, []);
  useEffect(() => {
    const p = peek.current;
    if (!peekId || p.started || !edges.right || edges.left) return;
    p.started = true;
    const key = PEEK_PREFIX + peekId;
    try {
      if (localStorage.getItem(key)) return;
    } catch {
      return; // 讀不到偏好就不推,寧可不做也不要每次都推
    }
    if (prefersReducedMotion()) return;
    const el = ref.current;
    if (!el) return;
    const cancel = () => {
      p.timers.forEach((t) => window.clearTimeout(t));
      p.timers = [];
      el.removeEventListener("pointerdown", cancel);
    };
    p.cancel = cancel;
    el.addEventListener("pointerdown", cancel, { passive: true });
    p.timers.push(
      window.setTimeout(() => {
        try {
          localStorage.setItem(key, "1");
        } catch {
          /* 寫不進去:下次還會推一次,無害 */
        }
        if (el.scrollLeft > 0) return cancel();
        el.scrollTo({ left: PEEK_PX, behavior: "smooth" });
        p.timers.push(
          window.setTimeout(() => {
            if (Math.abs(el.scrollLeft - PEEK_PX) <= 2) el.scrollTo({ left: 0, behavior: "smooth" });
            cancel();
          }, 420),
        );
      }, 700),
    );
  }, [peekId, edges.right, edges.left]);

  const nudge = (dir: 1 | -1) => {
    const el = ref.current;
    if (!el) return;
    el.scrollBy({ left: dir * Math.max(80, el.clientWidth * 0.7), behavior: prefersReducedMotion() ? "auto" : "smooth" });
  };

  const style = { "--sh-fade": FADE_VAR[fade] } as CSSProperties;
  const edgeProps = { variant, edgeRadius };

  return (
    <div className={cn("relative min-w-0 max-w-full", wrapperClassName)} style={style}>
      <div ref={ref} className={cn("relative", variant !== "table" && "scrollbar-hide", className)} {...rest}>
        {children}
      </div>
      {edges.left && (
        <HintEdge side="left" {...edgeProps} onClick={() => nudge(-1)} />
      )}
      {edges.right && (
        <HintEdge side="right" {...edgeProps} onClick={() => nudge(1)} />
      )}
    </div>
  );
}

function HintEdge({
  side,
  variant,
  edgeRadius,
  onClick,
}: {
  side: "left" | "right";
  variant: NonNullable<Props["variant"]>;
  edgeRadius?: string;
  onClick: () => void;
}) {
  const right = side === "right";
  const Icon = right ? ChevronRight : ChevronLeft;
  const pill = variant === "pill";
  const table = variant === "table";
  // 有邊框(pill 或帶 edgeRadius 的表)就內縮 1px,邊框線不被漸層蓋掉。
  const inset = pill || (table && edgeRadius != null);
  const radius = table && edgeRadius != null ? `calc(${edgeRadius} - 1px)` : undefined;
  const button = (
    <button
      type="button"
      aria-label={right ? "往右看更多" : "往左看更多"}
      onClick={onClick}
      className={cn(
        "pointer-events-auto flex h-full max-h-11 w-9 shrink-0 cursor-pointer items-center justify-center",
        "rounded-full focus-visible:outline-offset-0",
      )}
    >
      <span
        aria-hidden
        className="flex h-7 w-7 items-center justify-center rounded-full border border-primary/40 text-primary shadow-[var(--shadow-card)] transition-colors duration-200"
        style={{ background: "color-mix(in srgb, var(--primary) 16%, var(--sh-fade))" }}
      >
        <Icon size={16} strokeWidth={2.2} />
      </span>
    </button>
  );
  return (
    <div
      className={cn(
        "pointer-events-none absolute z-1 flex",
        table ? "flex-col" : "items-center",
        inset ? "inset-y-px" : "inset-y-0",
        right
          ? cn(table ? "items-end" : "justify-end", inset ? "right-px" : "right-0", pill && "rounded-r-full")
          : cn(table ? "items-start" : "justify-start", inset ? "left-px" : "left-0", pill && "rounded-l-full"),
      )}
      style={{
        width: HINT_WIDTH,
        background: `linear-gradient(to ${right ? "left" : "right"}, var(--sh-fade) 42%, transparent)`,
        ...(radius && (right
          ? { borderTopRightRadius: radius, borderBottomRightRadius: radius }
          : { borderTopLeftRadius: radius, borderBottomLeftRadius: radius })),
      }}
    >
      {table ? (
        // 起點=表頭列;表比視窗高時停在視窗垂直中線(sticky 只在本提示層的高度內移動)。
        <div className="sticky flex h-11 items-center" style={{ top: "calc(50vh - 22px)" }}>
          {button}
        </div>
      ) : (
        button
      )}
    </div>
  );
}
