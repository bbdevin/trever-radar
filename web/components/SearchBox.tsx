"use client";

import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Command, CommandDialog, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";

type IndexRow = [string, string, string, string]; // [id, name, market, industry]

const MARKET: Record<string, string> = { twse: "上市", tpex: "上櫃" };

/** 全站股票搜尋:聚焦才載入索引;代號前綴 + 名稱子字串比對 */
export default function SearchBox() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [index, setIndex] = useState<IndexRow[] | null>(null);

  useEffect(() => {
    if (!open || index) return;
    fetch("/data/stocks_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setIndex)
      .catch(() => setIndex([]));
  }, [open, index]);

  // 全域快捷鍵 "/" 開啟
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

  const results = useMemo(() => {
    if (!index || !q.trim()) return [];
    const kw = q.trim().toUpperCase();
    const byId = index.filter((r) => r[0].startsWith(kw));
    const byName = index.filter((r) => !r[0].startsWith(kw) && r[1].includes(q.trim()));
    return [...byId, ...byName].slice(0, 12);
  }, [index, q]);

  const go = (id: string) => {
    setOpen(false);
    setQ("");
    window.location.href = `/stock?id=${id}`;
  };

  return (
    <>
      <button
        className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground hover:border-foreground/20"
        onClick={() => setOpen(true)}
        aria-label="搜尋股票"
        title="搜尋(/)"
      >
        <Search size={15} strokeWidth={2} />
        <span className="hidden sm:inline">搜尋</span>
        <kbd className="hidden rounded border border-border px-1 font-mono text-[10px] text-muted-foreground sm:inline">/</kbd>
      </button>
      <CommandDialog open={open} onOpenChange={setOpen} title="搜尋股票" description="輸入代號或名稱搜尋個股">
        <Command shouldFilter={false}>
          <CommandInput value={q} onValueChange={setQ} placeholder="輸入代號或名稱,例:2330、台積電" />
          <CommandList>
            {q.trim() === "" && <CommandEmpty>輸入代號或名稱開始搜尋</CommandEmpty>}
            {q.trim() !== "" && index && results.length === 0 && <CommandEmpty>找不到「{q}」</CommandEmpty>}
            {results.map((r) => (
              <CommandItem key={r[0]} value={r[0]} onSelect={() => go(r[0])}>
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
