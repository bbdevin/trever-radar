"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import { effectiveTracked, nextAction } from "@/lib/branchTrackResolve";

// 全站追蹤名單的管理員覆寫(Supabase `branch_track_list`,一份名單、全站一致)。
// 登入的使用者都讀得到;只有管理員(app_profiles.role = 'admin')能寫(RLS 守)。
// 系統名單照舊由 VPS 匯出;這裡存「相對系統名單的差異」,規則見 branchTrackResolve.ts。
// VPS 夜間會把這張表併回系統名單;在那之前由這層疊加讓畫面先一致。
// 檔名不叫 branchTrack.tsx:lib/branchTrack.ts(追蹤明細的純函式)已佔用那個模組名。

interface ListRow {
  branch_name: string;
  state: "track" | "mute";
}

interface BranchTrackContextValue {
  muted: Set<string>;
  added: Set<string>;
  loading: boolean;
  /** 管理員、且資料表讀得到:才顯示 ★ 按鈕。 */
  canEdit: boolean;
  /** 非管理員回傳 "forbidden"。 */
  toggle: (name: string, serverTracked: boolean) => Promise<{ error: string | null }>;
  isTracked: (name: string, serverTracked: boolean) => boolean;
}

const BranchTrackContext = createContext<BranchTrackContextValue | null>(null);

/** 全站只掛一次(見 layout.tsx),和 WatchlistProvider 同一個模式。 */
export function BranchTrackProvider({ children }: { children: ReactNode }) {
  const { session, isAdmin } = useSession();
  const userId = session?.user?.id ?? null;
  const [rows, setRows] = useState<ListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [available, setAvailable] = useState(false);

  const refresh = useCallback(async () => {
    if (!userId) {
      setRows([]);
      setAvailable(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    const { data, error } = await supabase
      .from("branch_track_list")
      .select("branch_name, state");
    // 表還沒建(42P01 / PGRST205)或任何讀取錯誤:當作沒有覆寫,按鈕不出現,畫面照系統名單。
    if (error || !data) {
      setRows([]);
      setAvailable(false);
    } else {
      setRows((data as ListRow[]).filter((r) => r.state === "track" || r.state === "mute"));
      setAvailable(true);
    }
    setLoading(false);
  }, [userId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const muted = useMemo(() => new Set(rows.filter((r) => r.state === "mute").map((r) => r.branch_name)), [rows]);
  const added = useMemo(() => new Set(rows.filter((r) => r.state === "track").map((r) => r.branch_name)), [rows]);
  const canEdit = Boolean(userId) && isAdmin && available;

  const toggle = useCallback(
    async (name: string, serverTracked: boolean) => {
      if (!userId || !canEdit) return { error: "forbidden" };
      const action = nextAction(name, serverTracked, muted, added);
      // 樂觀更新,失敗再重拉
      setRows((prev) => {
        const rest = prev.filter((r) => r.branch_name !== name);
        return action.kind === "delete" ? rest : [...rest, { branch_name: name, state: action.state }];
      });
      const { error } = action.kind === "delete"
        ? await supabase.from("branch_track_list").delete().eq("branch_name", name)
        : await supabase.from("branch_track_list").upsert(
            { branch_name: name, state: action.state, updated_by: userId, updated_at: new Date().toISOString() },
            { onConflict: "branch_name" },
          );
      if (error) await refresh();
      return { error: error?.message ?? null };
    },
    [userId, canEdit, muted, added, refresh],
  );

  const isTracked = useCallback(
    (name: string, serverTracked: boolean) => effectiveTracked(name, serverTracked, muted, added),
    [muted, added],
  );

  const value = useMemo(
    () => ({ muted, added, loading, canEdit, toggle, isTracked }),
    [muted, added, loading, canEdit, toggle, isTracked],
  );

  return <BranchTrackContext.Provider value={value}>{children}</BranchTrackContext.Provider>;
}

export function useBranchTrack() {
  const ctx = useContext(BranchTrackContext);
  if (!ctx) throw new Error("useBranchTrack must be used within BranchTrackProvider");
  return ctx;
}
