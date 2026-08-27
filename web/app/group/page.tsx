"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, Building2, ExternalLink, MapPin } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { dataFetch } from "@/lib/dataFetch";
import { chgClass, fmtE8, fmtPct } from "@/lib/format";
import type { CompanyGroup, CompanyGroupsJson } from "@/lib/types";
import { cn } from "@/lib/utils";

function GroupView() {
  const id = useSearchParams().get("id");
  const [data, setData] = useState<CompanyGroupsJson | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
    dataFetch("/data/groups.json")
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then(setData)
      .catch(() => setError(true));
  }, []);

  if (!id) return <EmptyState title="網址缺少集團代號" detail="請由個股頁的集團標籤進入，或使用 ?id=walsin。" />;
  if (error) return <EmptyState title="目前無法讀取集團資料" detail="資料尚未產出或暫時無法連線；不代表集團不存在。" />;
  if (!data) return <><Skeleton className="my-4 h-16 rounded-[var(--r-lg)]" /><Skeleton className="h-72 rounded-[var(--r-lg)]" /></>;
  const group = data.groups.find((item) => item.id === id);
  if (!group) return <EmptyState title="找不到此集團資料" detail="目前只提供具官方來源、已版本控管的集團 mapping。" />;
  return <GroupDetail group={group} dataDate={data.data_date} />;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="py-12 text-center">
      <Building2 className="mx-auto mb-3 h-7 w-7 text-muted-foreground" aria-hidden="true" />
      <h1 className="text-base font-bold text-foreground">{title}</h1>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{detail}</p>
      <a href="/" className="mt-4 inline-flex min-h-11 items-center gap-1 rounded-full px-3 text-sm font-semibold text-primary transition-colors duration-200 hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft size={16} aria-hidden="true" /> 返回雷達
      </a>
    </div>
  );
}

function GroupDetail({ group, dataDate }: { group: CompanyGroup; dataDate: string }) {
  return (
    <div className="min-w-0 py-4">
      <a href="/" className="-ml-2 inline-flex min-h-11 items-center gap-1 rounded-full px-2 text-sm text-muted-foreground transition-colors duration-200 hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft size={16} aria-hidden="true" /> 返回雷達
      </a>
      <section className="mt-1 rounded-[var(--r-lg)] border border-border bg-card p-4 shadow-[var(--shadow-card)]">
        <div className="flex min-w-0 items-start gap-2">
          <Building2 className="mt-0.5 h-5 w-5 shrink-0 text-[color:var(--accent-2)]" aria-hidden="true" />
          <div className="min-w-0">
            <h1 className="truncate text-xl font-extrabold" title={group.name}>{group.name}</h1>
            <p className="mt-1 text-xs text-muted-foreground">成員股為官方頁面可核驗的版本化 mapping；不代表投資建議或共同漲跌。</p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 text-[11.5px] text-muted-foreground">
          <span>行情資料日：<span className="num text-[color:var(--ink-2)]">{dataDate}</span></span>
          <span>觀察日：<span className="num text-[color:var(--ink-2)]">{group.observed_at}</span></span>
          <span>來源資料日：<span className="num text-[color:var(--ink-2)]">{group.source_updated_at ?? "資料未提供"}</span></span>
          <a href={group.source} target="_blank" rel="noreferrer" className="inline-flex min-h-11 items-center gap-1 rounded-full px-2 font-semibold text-primary transition-colors duration-200 hover:bg-secondary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            官方來源 <ExternalLink size={13} aria-hidden="true" />
          </a>
        </div>
      </section>
      <div className="mt-3 grid gap-2.5">
        {group.members.map((member) => {
          const movement = chgClass(member.chg_pct);
          return (
            <a key={member.id} href={`/stock?id=${encodeURIComponent(member.id)}`} className="block min-h-11 rounded-[var(--r-md)] border border-border bg-card p-3.5 shadow-[var(--shadow-card)] transition-colors duration-200 hover:bg-secondary/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <div className="flex min-w-0 items-center gap-2">
                <span className="num shrink-0 text-sm font-extrabold text-[color:var(--ink-2)]">{member.id}</span>
                <span className="truncate font-bold">{member.name ?? "公司名稱資料未提供"}</span>
                <span className="ml-auto shrink-0 text-right">
                  {member.close == null ? <span className="text-xs text-muted-foreground">尚無可用報價</span> : <><span className="num text-base font-extrabold">{member.close.toLocaleString("zh-TW")}</span><span className={cn("ml-1.5 num text-xs font-bold", movement === "up" ? "text-up" : movement === "down" ? "text-down" : "text-muted-foreground")}>{fmtPct(member.chg_pct)}</span></>}
                </span>
              </div>
              <div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>{member.industry ?? "產業資料未提供"}</span>
                <span>資料日：<span className="num">{member.quote_date ?? "資料未提供"}</span></span>
                <span>成交額：<span className="num">{member.turnover == null ? "資料未提供" : fmtE8(member.turnover)}</span></span>
                {member.quote_date == null && <span className="inline-flex items-center gap-1"><MapPin size={13} aria-hidden="true" />未有可用收盤價，不代表成員資格不存在。</span>}
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}

export default function GroupPage() {
  return <Suspense fallback={<div className="py-12 text-center text-sm text-muted-foreground">載入中…</div>}><GroupView /></Suspense>;
}
