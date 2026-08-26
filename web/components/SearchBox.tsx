"use client";

import { History, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { dataFetch } from "@/lib/dataFetch";
import { useSession } from "@/lib/useSession";
import { useUserPrefs } from "@/lib/userPrefs";

type IndexRow = [string, string, string, string]; // [id, name, market, industry]

const MARKET: Record<string, string> = { twse: "上市", tpex: "上櫃" };

/** 全站股票搜尋:聚焦才載入索引;代號前綴 + 名稱子字串比對;登入後記錄歷史 */
export default function SearchBox() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [index, setIndex] = useState<IndexRow[] | null>(null);
  const { session } = useSession();
  const { searchHistory, pushSearch, clearSearchHistory } = useUserPrefs();

  useEffect(() => {
    if (!open || index) return;
    dataFetch("/data/stocks_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setIndex)
      .catch(() => setIndex([]));
  }, [open, index]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !open && !(e.target as HTMLElement)?.closest?.("input,textarea")) {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const nameById = useMemo(() => {
    const m = new Map<string, IndexRow>();
    if (index) for (const r of index) m.set(r[0], r);
    return m;
  }, [index]);

  const results = useMemo(() => {
    if (!index || !q.trim()) return [];
    const kw = q.trim().toUpperCase();
    const byId = index.filter((r) => r[0].startsWith(kw));
    const byName = index.filter((r) => !r[0].startsWith(kw) && r[1].includes(q.trim()));
    return [...byId, ...byName].slice(0, 12);
  }, [index, q]);

  const go = async (id: string) => {
    // 必須等寫入完成再換頁,否則 hard navigate 會取消 upsert,歷史永遠空白
    try {
      await pushSearch(id);
    } catch {
      /* 仍導向個股 */
    }
    setOpen(false);
    setQ("");
    window.location.href = `/stock?id=${id}`;
  };

  const showHistory = q.trim() === "";

  return (
    <>
      <button
        type="button"
        className="inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1.5 rounded-full border border-border bg-card px-3 text-xs text-muted-foreground transition-colors duration-200 hover:border-foreground/20 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={() => setOpen(true)}
        aria-label="搜尋股票"
        title="搜尋(/)"
      >
        <Search size={15} strokeWidth={2} aria-hidden />
        <span className="hidden sm:inline">搜尋</span>
        <kbd className="hidden rounded border border-border px-1 font-mono text-[10px] text-muted-foreground sm:inline">
          /
        </kbd>
      </button>
      <CommandDialog open={open} onOpenChange={setOpen} title="搜尋股票" description="輸入代號或名稱搜尋個股">
        <Command shouldFilter={false}>
          <CommandInput value={q} onValueChange={setQ} placeholder="輸入代號或名稱,例:2330、台積電" />
          <CommandList>
            {showHistory && (
              <>
                <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-2">
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <History size={12} strokeWidth={2} aria-hidden className="opacity-70" />
                    最近搜尋
                  </span>
                  {session && searchHistory.length > 0 && (
                    <button
                      type="button"
                      className="cursor-pointer rounded text-[11px] font-medium text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      onClick={() => void clearSearchHistory()}
                    >
                      清除歷史
                    </button>
                  )}
                </div>
                {!session && (
                  <div className="px-3 py-3 text-xs text-muted-foreground">登入後可記錄搜尋</div>
                )}
                {session && searchHistory.length === 0 && (
                  <div className="px-3 py-3 text-xs text-muted-foreground">
                    尚無搜尋紀錄，選一檔個股後會出現在這裡
                  </div>
                )}
                {session &&
                  searchHistory.map((h) => {
                    const row = nameById.get(h.stock_id);
                    return (
                      <CommandItem
                        key={h.stock_id}
                        value={`hist-${h.stock_id}`}
                        onSelect={() => {
                          void go(h.stock_id);
                        }}
                        className="min-h-11 cursor-pointer"
                      >
                        <span className="min-w-[52px] font-mono font-bold">{h.stock_id}</span>
                        <span className="font-semibold">{row?.[1] ?? "—"}</span>
                        {row && (
                          <span className="ml-auto text-xs text-muted-foreground">
                            {MARKET[row[2]] ?? row[2]}
                            {row[3] ? ` · ${row[3]}` : ""}
                          </span>
                        )}
                      </CommandItem>
                    );
                  })}
              </>
            )}
            {!showHistory && index && results.length === 0 && <CommandEmpty>找不到「{q}」</CommandEmpty>}
            {!showHistory &&
              results.map((r) => (
                <CommandItem key={r[0]} value={r[0]} onSelect={() => void go(r[0])} className="min-h-11 cursor-pointer">
                  <span className="min-w-[52px] font-mono font-bold">{r[0]}</span>
                  <span className="font-semibold">{r[1]}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {MARKET[r[2]] ?? r[2]}
                    {r[3] ? ` · ${r[3]}` : ""}
                  </span>
                </CommandItem>
              ))}
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}
