import type { Metadata } from "next";
import { ChevronDown, History } from "lucide-react";

import { CHANGELOG, CURRENT_VERSION, KIND_LABEL, type ChangeKind, type Release } from "@/lib/changelog";
import { cn } from "@/lib/utils";

export const metadata: Metadata = { title: "版本更新紀錄 — Trever Radar" };

// 種類徽章:只用既有 token 的 /12 淡底 + 同色字,文字本身就是訊號(不靠顏色)。
// 不用紅/綠——那是全站漲跌語意。
const KIND_CLASS: Record<ChangeKind, string> = {
  new: "bg-[color:var(--accent-2)]/12 text-[color:var(--accent-2)]",
  improve: "bg-primary/12 text-primary",
  fix: "bg-warn/12 text-warn",
};

function fmtDate(d: string) {
  const [y, m, day] = d.split("-").map(Number);
  return `${y}/${m}/${day}`;
}

function VersionChip({ version }: { version: string }) {
  return (
    <span className="num inline-flex h-6 shrink-0 items-center rounded-full bg-primary px-2.5 text-[12.5px] font-bold text-primary-foreground">
      v{version}
    </span>
  );
}

function ReleaseBody({ release }: { release: Release }) {
  return (
    <ul className="grid gap-2">
      {release.items.map((it, i) => (
        <li key={i} className="flex min-w-0 items-start gap-2 text-[14px] leading-relaxed">
          <span
            className={cn(
              "mt-[2px] inline-flex h-5 shrink-0 items-center rounded-[6px] px-1.5 text-[11px] font-semibold",
              KIND_CLASS[it.kind],
            )}
          >
            {KIND_LABEL[it.kind]}
          </span>
          <span className="min-w-0 break-words text-foreground">{it.text}</span>
        </li>
      ))}
    </ul>
  );
}

function ReleaseHead({ release, latest = false }: { release: Release; latest?: boolean }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
      <VersionChip version={release.version} />
      <span className="num text-[12.5px] text-muted-foreground">{fmtDate(release.date)}</span>
      {latest && (
        <span className="rounded-full bg-primary/12 px-2 py-0.5 text-[11px] font-semibold text-primary">最新</span>
      )}
      {release.title && <span className="min-w-0 text-[14.5px] font-bold text-foreground">{release.title}</span>}
    </div>
  );
}

/** 舊版依月份分組(新到舊)。 */
function groupByMonth(releases: Release[]) {
  const groups: { key: string; label: string; releases: Release[] }[] = [];
  for (const r of releases) {
    const key = r.date.slice(0, 7);
    let g = groups[groups.length - 1];
    if (!g || g.key !== key) {
      const [y, m] = key.split("-").map(Number);
      g = { key, label: `${y} 年 ${m} 月`, releases: [] };
      groups.push(g);
    }
    g.releases.push(r);
  }
  return groups;
}

export default function ChangelogPage() {
  const [latest, ...older] = CHANGELOG;
  const months = groupByMonth(older);
  return (
    <div className="mx-auto grid max-w-[720px] gap-4 py-4 md:py-6">
      <header className="grid gap-1.5">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-[var(--r-sm)] bg-primary/12 text-primary">
            <History size={18} strokeWidth={1.8} />
          </span>
          <h1 className="text-[20px] font-extrabold tracking-tight text-foreground">版本更新紀錄</h1>
        </div>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          目前版本 <span className="num font-bold text-primary">v{CURRENT_VERSION}</span>。版號是「主版.次版」:
          每次有看得到的更新,次版加一;整站等級的大改版才換主版。
        </p>
      </header>

      <section aria-label="最新版本" className="grid gap-3 rounded-[var(--r-lg)] border border-border bg-card p-4">
        <ReleaseHead release={latest} latest />
        <ReleaseBody release={latest} />
      </section>

      {months.map((g, gi) => (
        <details
          key={g.key}
          open={gi === 0}
          className="group rounded-[var(--r-lg)] border border-border bg-card [&_summary::-webkit-details-marker]:hidden"
        >
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-2 px-4 py-2.5 select-none">
            <span className="text-[14.5px] font-bold text-foreground">{g.label}</span>
            <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <span className="num">
                {g.releases.length > 1 && `v${g.releases[g.releases.length - 1].version}–`}v{g.releases[0].version}
              </span>
              <ChevronDown size={16} className="transition-transform duration-200 group-open:rotate-180" />
            </span>
          </summary>
          <div className="grid gap-4 border-t border-border px-4 pt-3 pb-4">
            {g.releases.map((r) => (
              <article key={r.version} className="grid gap-2">
                <ReleaseHead release={r} />
                <ReleaseBody release={r} />
              </article>
            ))}
          </div>
        </details>
      ))}
    </div>
  );
}
