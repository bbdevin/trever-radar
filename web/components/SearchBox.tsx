"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type IndexRow = [string, string, string, string]; // [id, name, market, industry]

const MARKET: Record<string, string> = { twse: "上市", tpex: "上櫃" };

/** 全站股票搜尋:聚焦才載入索引;代號前綴 + 名稱子字串比對 */
export default function SearchBox() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [index, setIndex] = useState<IndexRow[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || index) return;
    fetch("/data/stocks_index.json")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setIndex)
      .catch(() => setIndex([]));
  }, [open, index]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // 全域快捷鍵 "/" 開啟
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !open && !(e.target as HTMLElement)?.closest?.("input,textarea")) {
        e.preventDefault();
        setOpen(true);
      }
      if (e.key === "Escape") setOpen(false);
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

  useEffect(() => setCursor(0), [q]);

  const go = (id: string) => {
    setOpen(false);
    setQ("");
    window.location.href = `/stock?id=${id}`;
  };

  return (
    <>
      <button className="search-trigger" onClick={() => setOpen(true)} aria-label="搜尋股票" title="搜尋(/)">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <span className="st-label">搜尋</span>
        <kbd>/</kbd>
      </button>
      {open && (
        <div className="search-overlay" onClick={() => setOpen(false)}>
          <div className="search-panel" onClick={(e) => e.stopPropagation()}>
            <input
              ref={inputRef}
              value={q}
              placeholder="輸入代號或名稱,例:2330、台積電"
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, results.length - 1));
                else if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
                else if (e.key === "Enter" && results[cursor]) go(results[cursor][0]);
              }}
            />
            <div className="search-results">
              {q.trim() === "" && <div className="sr-empty">輸入代號或名稱開始搜尋</div>}
              {q.trim() !== "" && index && results.length === 0 && (
                <div className="sr-empty">找不到「{q}」</div>
              )}
              {results.map((r, i) => (
                <button
                  key={r[0]}
                  className={`sr-item ${i === cursor ? "active" : ""}`}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => go(r[0])}
                >
                  <span className="sr-id">{r[0]}</span>
                  <span className="sr-name">{r[1]}</span>
                  <span className="sr-meta">
                    {MARKET[r[2]] ?? r[2]}
                    {r[3] ? ` · ${r[3]}` : ""}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
