"use client";

// 自選「特定分點」(docs/52)的分點組合與資料讀取。
//
// TODO(docs/52 §6):分點組合目前只存本機(localStorage),換裝置不會跟著走。綁帳號需要新的
// Supabase 表 `watched_branch_sets`,SQL 草稿在 docs/sql/20261019160000_create_watched_branch_sets.sql
// (未執行,須人類審過再貼到 Supabase SQL Editor)。表建好後比照 lib/userPrefs.tsx 的 user_ui_prefs:
// 登入時讀雲端、改動時 upsert,表不存在時退回本機。

import { useCallback, useEffect, useMemo, useState } from "react";
import { dataFetch } from "@/lib/dataFetch";
import {
  buildRows,
  normalizeSet,
  shardsFor,
  type BranchSet,
  type ComboRow,
  type WatchIndex,
  type WatchShard,
} from "@/lib/watchedBranches";

const LOCAL_KEY = "watched_branch_set_v1";

function readLocal(): BranchSet {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    return normalizeSet(raw ? JSON.parse(raw) : null);
  } catch {
    return normalizeSet(null);
  }
}

/** [組合, 更新];第一次 render 用預設值,mount 後換成本機存的。 */
export function useWatchedBranchSet(): [BranchSet, (next: BranchSet) => void] {
  const [set, setState] = useState<BranchSet>(() => normalizeSet(null));
  useEffect(() => {
    setState(readLocal());
  }, []);
  const update = useCallback((next: BranchSet) => {
    const clean = normalizeSet(next);
    setState(clean);
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify(clean));
    } catch {
      /* 私密模式等:留在記憶體 */
    }
  }, []);
  return [set, update];
}

export type WatchDataState =
  | { status: "loading" }
  | { status: "missing" }   // 還沒有這份匯出(舊資料)
  | { status: "error" }
  | { status: "ready"; index: WatchIndex; rows: ComboRow[]; loadingShards: boolean };

/** 讀 index 一次,再依組合抓需要的分片(抓過的留著,換組合不重抓)。
 *  enabled = false 時什麼都不抓(自選股分頁先畫完、閒置後才抓徽章要的資料)。 */
export function useWatchedBranchData(set: BranchSet, enabled = true): WatchDataState {
  const [index, setIndex] = useState<WatchIndex | null>(null);
  const [indexStatus, setIndexStatus] = useState<"loading" | "missing" | "error" | "ready">("loading");
  const [shards, setShards] = useState<Record<number, WatchShard>>({});
  const [pending, setPending] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    dataFetch("/data/branches/watch/index.json")
      .then((r) => {
        if (r.status === 404) return null;
        return r.ok ? r.json() : Promise.reject(r.status);
      })
      .then((d: WatchIndex | null) => {
        if (cancelled) return;
        if (!d || d.version !== 1 || !Array.isArray(d.branches)) {
          setIndexStatus("missing");
          return;
        }
        setIndex(d);
        setIndexStatus("ready");
      })
      .catch(() => { if (!cancelled) setIndexStatus("error"); });
    return () => { cancelled = true; };
  }, [enabled]);

  const need = useMemo(() => (index ? shardsFor(index, set.branches) : []), [index, set.branches]);

  useEffect(() => {
    const missing = need.filter((i) => !shards[i]);
    if (!missing.length) return;
    let cancelled = false;
    setPending((n) => n + 1);
    Promise.all(missing.map((i) =>
      dataFetch(`/data/branches/watch/s${String(i).padStart(2, "0")}.json`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((d: WatchShard) => [i, d] as const),
    ))
      .then((got) => {
        if (cancelled) return;
        setShards((prev) => {
          const next = { ...prev };
          for (const [i, d] of got) next[i] = d;
          return next;
        });
      })
      .catch(() => { if (!cancelled) setIndexStatus("error"); })
      .finally(() => setPending((n) => n - 1));
    return () => { cancelled = true; };
    // shards 只用來判斷缺哪片;抓回來後 need 不變就不會再進來
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [need]);

  const rows = useMemo(
    () => buildRows(set, need.map((i) => shards[i]).filter(Boolean)),
    [set, need, shards],
  );

  if (indexStatus !== "ready" || !index) return { status: indexStatus === "ready" ? "loading" : indexStatus };
  return { status: "ready", index, rows, loadingShards: pending > 0 || need.some((i) => !shards[i]) };
}
