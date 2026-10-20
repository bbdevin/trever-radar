"use client";

// 自選「特定分點」(docs/52)的分點組合與資料讀取。
//
// 組合綁帳號(docs/52 §6):本機 localStorage(watched_branch_set_v1)永遠有一份;登入且已核准時
// 讀 Supabase `watched_branch_sets` 自己那一列並依 lib/watchedBranchSync.ts 的規則合併,改動時 upsert。
// 表還沒建(SQL docs/sql/20261019160000_create_watched_branch_sets.sql 由人類執行)或請求失敗 → 安靜退回本機。
// 只用 lib/supabase.ts 的 publishable key 客戶端;一切權限由 RLS 決定。

import { useCallback, useEffect, useMemo, useState } from "react";
import { dataFetch } from "@/lib/dataFetch";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import {
  buildRows,
  normalizeSet,
  shardsFor,
  type BranchSet,
  type ComboRow,
  type WatchIndex,
  type WatchShard,
} from "@/lib/watchedBranches";
import { BranchSetSync, CLOUD_TABLE, type CloudApi, type KeyValue } from "@/lib/watchedBranchSync";

const storage: KeyValue = {
  get(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null; // 私密模式等
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      /* 私密模式等:留在記憶體 */
    }
  },
};

const cloud: CloudApi = {
  async load(uid) {
    const { data, error, status } = await supabase
      .from(CLOUD_TABLE)
      .select("branches, anchor, updated_at")
      .eq("user_id", uid)
      .maybeSingle();
    return { row: data ?? null, error: error ? { code: error.code, message: error.message, status } : null };
  },
  async save(row) {
    const { error, status } = await supabase.from(CLOUD_TABLE).upsert(row, { onConflict: "user_id" });
    return { error: error ? { code: error.code, message: error.message, status } : null };
  },
};

/** 一個頁面載入共用一個:表不存在時只試一次,站內換頁回來也不再打。 */
let shared: BranchSetSync | null = null;
function getSync(): BranchSetSync {
  shared ??= new BranchSetSync({ kv: storage, api: cloud, warn: (m) => console.warn(m) });
  return shared;
}

/** [組合, 更新];第一次 render 用預設值,mount 後換成本機存的,登入(已核准)後再依雲端合併。 */
export function useWatchedBranchSet(): [BranchSet, (next: BranchSet) => void] {
  const { session, approved, loading } = useSession();
  // 只用 user id:TOKEN_REFRESHED 換 session 物件時不重讀雲端
  const uid = !loading && approved ? session?.user?.id ?? null : null;
  const [set, setState] = useState<BranchSet>(() => normalizeSet(null));
  useEffect(() => {
    let alive = true;
    const sync = getSync();
    setState(sync.current());
    void sync.attach(uid).then((s) => {
      if (alive) setState(s);
    });
    return () => {
      alive = false;
    };
  }, [uid]);
  const update = useCallback((next: BranchSet) => {
    setState(getSync().edit(next));
  }, []);
  return [set, update];
}

const WARRANT_KEY = "watched_branch_warrants_v1";

/** 「含權證」開關(預設開;記在本機)。徽章與分頁共用同一個值。 */
export function useWatchedWarrantToggle(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(true);
  useEffect(() => {
    try {
      if (localStorage.getItem(WARRANT_KEY) === "0") setOn(false);
    } catch {
      /* 私密模式等:用預設 */
    }
  }, []);
  const update = useCallback((next: boolean) => {
    setOn(next);
    try {
      localStorage.setItem(WARRANT_KEY, next ? "1" : "0");
    } catch {
      /* 留在記憶體 */
    }
  }, []);
  return [on, update];
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
    // 權證那天不是今天(counted=false)時,權證進出只列出、不算進同買／同賣(docs/52 §8)。
    () => buildRows(set, need.map((i) => shards[i]).filter(Boolean), index?.warrant?.counted === true),
    [set, need, shards, index],
  );

  if (indexStatus !== "ready" || !index) return { status: indexStatus === "ready" ? "loading" : indexStatus };
  return { status: "ready", index, rows, loadingShards: pending > 0 || need.some((i) => !shards[i]) };
}
