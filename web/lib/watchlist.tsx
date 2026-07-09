"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";

export interface WatchlistItem {
  stock_id: string;
  note: string | null;
  added_at: string;
}

interface WatchlistContextValue {
  items: WatchlistItem[];
  ids: Set<string>;
  loading: boolean;
  /** 未登入時回傳 "not_signed_in",呼叫端自行導去登入。*/
  toggle: (stockId: string) => Promise<{ error: string | null }>;
}

const WatchlistContext = createContext<WatchlistContextValue | null>(null);

/** 全站只掛一次(見 layout.tsx),避免每張卡片各自打一次 Supabase。*/
export function WatchlistProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!session) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const { data, error } = await supabase
      .from("watchlist")
      .select("stock_id, note, added_at")
      .order("added_at", { ascending: false });
    if (!error && data) setItems(data as WatchlistItem[]);
    setLoading(false);
  }, [session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = useCallback(
    async (stockId: string) => {
      if (!session) return { error: "not_signed_in" };
      const already = items.some((it) => it.stock_id === stockId);
      // 樂觀更新,失敗再回滾
      setItems((prev) =>
        already
          ? prev.filter((it) => it.stock_id !== stockId)
          : [{ stock_id: stockId, note: null, added_at: new Date().toISOString() }, ...prev],
      );
      const { error } = already
        ? await supabase.from("watchlist").delete()
            .eq("user_id", session.user.id).eq("stock_id", stockId)
        : await supabase.from("watchlist")
            .insert({ user_id: session.user.id, stock_id: stockId });
      if (error) await refresh();
      return { error: error?.message ?? null };
    },
    [session, items, refresh],
  );

  const ids = useMemo(() => new Set(items.map((it) => it.stock_id)), [items]);

  return (
    <WatchlistContext.Provider value={{ items, ids, loading, toggle }}>
      {children}
    </WatchlistContext.Provider>
  );
}

export function useWatchlist() {
  const ctx = useContext(WatchlistContext);
  if (!ctx) throw new Error("useWatchlist must be used within WatchlistProvider");
  return ctx;
}
