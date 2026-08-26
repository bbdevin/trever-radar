"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";

export type FontScale = "md" | "lg" | "xl";

export type SearchHistoryItem = {
  stock_id: string;
  searched_at: string;
};

const FONT_SCALES: FontScale[] = ["md", "lg", "xl"];
const ZOOM: Record<FontScale, string> = { md: "1", lg: "1.125", xl: "1.25" };
const LOCAL_KEY = "font_scale";
const HISTORY_LIMIT = 20;

function isFontScale(v: unknown): v is FontScale {
  return v === "md" || v === "lg" || v === "xl";
}

function applyFontScale(scale: FontScale) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.fontScale = scale;
  document.body.style.zoom = ZOOM[scale];
}

function readLocalScale(): FontScale {
  try {
    const v = localStorage.getItem(LOCAL_KEY);
    if (isFontScale(v)) return v;
  } catch {
    /* ignore */
  }
  return "md";
}

interface UserPrefsContextValue {
  fontScale: FontScale;
  searchHistory: SearchHistoryItem[];
  loading: boolean;
  setFontScale: (scale: FontScale) => Promise<void>;
  cycleFontScale: () => Promise<void>;
  pushSearch: (stockId: string) => Promise<void>;
  clearSearchHistory: () => Promise<void>;
}

const UserPrefsContext = createContext<UserPrefsContextValue | null>(null);

/** 全站字級與搜尋歷史（登入綁帳號；未登入字級僅本機）。*/
export function UserPrefsProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const [fontScale, setFontScaleState] = useState<FontScale>("md");
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!session) {
      const local = readLocalScale();
      setFontScaleState(local);
      applyFontScale(local);
      setSearchHistory([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const uid = session.user.id;
    const [prefsRes, histRes] = await Promise.all([
      supabase.from("user_ui_prefs").select("font_scale").eq("user_id", uid).maybeSingle(),
      supabase
        .from("search_history")
        .select("stock_id, searched_at")
        .eq("user_id", uid)
        .order("searched_at", { ascending: false })
        .limit(HISTORY_LIMIT),
    ]);

    let scale: FontScale = "md";
    if (prefsRes.data && isFontScale(prefsRes.data.font_scale)) {
      scale = prefsRes.data.font_scale;
    } else if (!prefsRes.error || /does not exist|schema cache/i.test(prefsRes.error.message ?? "")) {
      // 無列或表未建：用本機，登入後稍後 upsert
      scale = readLocalScale();
    }
    setFontScaleState(scale);
    applyFontScale(scale);
    try {
      localStorage.setItem(LOCAL_KEY, scale);
    } catch {
      /* ignore */
    }

    if (!histRes.error && histRes.data) {
      setSearchHistory(histRes.data as SearchHistoryItem[]);
    } else {
      setSearchHistory([]);
    }
    setLoading(false);
  }, [session]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 首屏：未等 session 前先套本機字級，減少閃爍
  useEffect(() => {
    applyFontScale(readLocalScale());
  }, []);

  const setFontScale = useCallback(
    async (scale: FontScale) => {
      setFontScaleState(scale);
      applyFontScale(scale);
      try {
        localStorage.setItem(LOCAL_KEY, scale);
      } catch {
        /* ignore */
      }
      if (!session) return;
      const { error } = await supabase.from("user_ui_prefs").upsert(
        {
          user_id: session.user.id,
          font_scale: scale,
          updated_at: new Date().toISOString(),
        },
        { onConflict: "user_id" },
      );
      if (error && !/does not exist|schema cache/i.test(error.message)) {
        console.warn("user_ui_prefs upsert", error.message);
      }
    },
    [session],
  );

  const cycleFontScale = useCallback(async () => {
    const i = FONT_SCALES.indexOf(fontScale);
    const next = FONT_SCALES[(i + 1) % FONT_SCALES.length]!;
    await setFontScale(next);
  }, [fontScale, setFontScale]);

  const pushSearch = useCallback(
    async (stockId: string) => {
      if (!session) return;
      const id = stockId.trim();
      if (!id) return;
      const now = new Date().toISOString();
      setSearchHistory((prev) => {
        const rest = prev.filter((h) => h.stock_id !== id);
        return [{ stock_id: id, searched_at: now }, ...rest].slice(0, HISTORY_LIMIT);
      });
      const { error } = await supabase.from("search_history").upsert(
        { user_id: session.user.id, stock_id: id, searched_at: now },
        { onConflict: "user_id,stock_id" },
      );
      if (error && !/does not exist|schema cache/i.test(error.message)) {
        console.warn("search_history upsert", error.message);
        return;
      }
      // 修剪超過 20 筆
      const { data: all } = await supabase
        .from("search_history")
        .select("stock_id, searched_at")
        .eq("user_id", session.user.id)
        .order("searched_at", { ascending: false });
      if (all && all.length > HISTORY_LIMIT) {
        const drop = all.slice(HISTORY_LIMIT).map((r) => r.stock_id);
        await supabase
          .from("search_history")
          .delete()
          .eq("user_id", session.user.id)
          .in("stock_id", drop);
      }
    },
    [session],
  );

  const clearSearchHistory = useCallback(async () => {
    if (!session) {
      setSearchHistory([]);
      return;
    }
    setSearchHistory([]);
    const { error } = await supabase.from("search_history").delete().eq("user_id", session.user.id);
    if (error && !/does not exist|schema cache/i.test(error.message)) {
      console.warn("search_history clear", error.message);
      await refresh();
    }
  }, [session, refresh]);

  const value = useMemo(
    () => ({
      fontScale,
      searchHistory,
      loading,
      setFontScale,
      cycleFontScale,
      pushSearch,
      clearSearchHistory,
    }),
    [fontScale, searchHistory, loading, setFontScale, cycleFontScale, pushSearch, clearSearchHistory],
  );

  return <UserPrefsContext.Provider value={value}>{children}</UserPrefsContext.Provider>;
}

export function useUserPrefs() {
  const ctx = useContext(UserPrefsContext);
  if (!ctx) throw new Error("useUserPrefs must be used within UserPrefsProvider");
  return ctx;
}

export const FONT_SCALE_LABEL: Record<FontScale, string> = {
  md: "標準",
  lg: "較大",
  xl: "最大",
};
