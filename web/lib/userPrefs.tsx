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
export type ThemeMode = "dark" | "light";

export type SearchHistoryItem = {
  stock_id: string;
  searched_at: string;
};

const FONT_SCALES: FontScale[] = ["md", "lg", "xl"];
const ZOOM: Record<FontScale, string> = { md: "1", lg: "1.125", xl: "1.25" };
const LOCAL_FONT = "font_scale";
const LOCAL_THEME = "theme";
const HISTORY_LIMIT = 20;

function isFontScale(v: unknown): v is FontScale {
  return v === "md" || v === "lg" || v === "xl";
}

function isThemeMode(v: unknown): v is ThemeMode {
  return v === "dark" || v === "light";
}

function applyFontScale(scale: FontScale) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.fontScale = scale;
  document.body.style.zoom = ZOOM[scale];
}

function applyTheme(mode: ThemeMode) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", mode === "dark");
}

function readLocalScale(): FontScale {
  try {
    const v = localStorage.getItem(LOCAL_FONT);
    if (isFontScale(v)) return v;
  } catch {
    /* ignore */
  }
  return "md";
}

/** 預設深色；僅本機明確存 light 才淺色。*/
function readLocalTheme(): ThemeMode {
  try {
    const v = localStorage.getItem(LOCAL_THEME);
    if (isThemeMode(v)) return v;
  } catch {
    /* ignore */
  }
  return "dark";
}

interface UserPrefsContextValue {
  fontScale: FontScale;
  theme: ThemeMode;
  searchHistory: SearchHistoryItem[];
  loading: boolean;
  setFontScale: (scale: FontScale) => Promise<void>;
  cycleFontScale: () => Promise<void>;
  setTheme: (mode: ThemeMode) => Promise<void>;
  toggleTheme: () => Promise<void>;
  pushSearch: (stockId: string) => Promise<void>;
  clearSearchHistory: () => Promise<void>;
}

const UserPrefsContext = createContext<UserPrefsContextValue | null>(null);

/** 字級／主題／搜尋歷史：本機 + 登入後雲端帳號。預設深色。*/
export function UserPrefsProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const [fontScale, setFontScaleState] = useState<FontScale>("md");
  const [theme, setThemeState] = useState<ThemeMode>("dark");
  const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);

  const persistCloud = useCallback(
    async (next: { font_scale: FontScale; theme: ThemeMode }) => {
      if (!session) return;
      const { error } = await supabase.from("user_ui_prefs").upsert(
        {
          user_id: session.user.id,
          font_scale: next.font_scale,
          theme: next.theme,
          updated_at: new Date().toISOString(),
        },
        { onConflict: "user_id" },
      );
      if (error && !/does not exist|schema cache|column.*theme/i.test(error.message)) {
        console.warn("user_ui_prefs upsert", error.message);
      }
    },
    [session],
  );

  const refresh = useCallback(async () => {
    if (!session) {
      const localScale = readLocalScale();
      const localTheme = readLocalTheme();
      setFontScaleState(localScale);
      setThemeState(localTheme);
      applyFontScale(localScale);
      applyTheme(localTheme);
      setSearchHistory([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const uid = session.user.id;
    const [prefsRes, histRes] = await Promise.all([
      supabase.from("user_ui_prefs").select("font_scale, theme").eq("user_id", uid).maybeSingle(),
      supabase
        .from("search_history")
        .select("stock_id, searched_at")
        .eq("user_id", uid)
        .order("searched_at", { ascending: false })
        .limit(HISTORY_LIMIT),
    ]);

    let scale = readLocalScale();
    let mode = readLocalTheme();
    if (prefsRes.data) {
      if (isFontScale(prefsRes.data.font_scale)) scale = prefsRes.data.font_scale;
      if (isThemeMode(prefsRes.data.theme)) mode = prefsRes.data.theme;
    }

    setFontScaleState(scale);
    setThemeState(mode);
    applyFontScale(scale);
    applyTheme(mode);
    try {
      localStorage.setItem(LOCAL_FONT, scale);
      localStorage.setItem(LOCAL_THEME, mode);
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

  useEffect(() => {
    applyFontScale(readLocalScale());
    applyTheme(readLocalTheme());
  }, []);

  const setFontScale = useCallback(
    async (scale: FontScale) => {
      setFontScaleState(scale);
      applyFontScale(scale);
      try {
        localStorage.setItem(LOCAL_FONT, scale);
      } catch {
        /* ignore */
      }
      await persistCloud({ font_scale: scale, theme });
    },
    [persistCloud, theme],
  );

  const cycleFontScale = useCallback(async () => {
    const i = FONT_SCALES.indexOf(fontScale);
    const next = FONT_SCALES[(i + 1) % FONT_SCALES.length]!;
    await setFontScale(next);
  }, [fontScale, setFontScale]);

  const setTheme = useCallback(
    async (mode: ThemeMode) => {
      setThemeState(mode);
      applyTheme(mode);
      try {
        localStorage.setItem(LOCAL_THEME, mode);
      } catch {
        /* ignore */
      }
      await persistCloud({ font_scale: fontScale, theme: mode });
    },
    [persistCloud, fontScale],
  );

  const toggleTheme = useCallback(async () => {
    await setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

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
      if (error) {
        console.warn("search_history upsert", error.message, error);
        return;
      }
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
      theme,
      searchHistory,
      loading,
      setFontScale,
      cycleFontScale,
      setTheme,
      toggleTheme,
      pushSearch,
      clearSearchHistory,
    }),
    [
      fontScale,
      theme,
      searchHistory,
      loading,
      setFontScale,
      cycleFontScale,
      setTheme,
      toggleTheme,
      pushSearch,
      clearSearchHistory,
    ],
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
