"use client";

import { Moon, Sun } from "lucide-react";
import { useUserPrefs } from "@/lib/userPrefs";

/**
 * 淺色/深色切換。預設深色；本機 localStorage + 登入後雲端帳號（docs/36）。
 * 須包在 UserPrefsProvider 內（含 AuthGate 登入頁）。
 */
export default function ThemeToggle() {
  const { theme, toggleTheme } = useUserPrefs();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={() => void toggleTheme()}
      aria-label={isDark ? "切換至淺色模式" : "切換至深色模式"}
      title="切換主題"
      className="ml-1 grid size-11 shrink-0 cursor-pointer place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {isDark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
