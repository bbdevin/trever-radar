"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

/**
 * 淺色/深色切換。預設深色(<html class="dark">),接既有 `.dark` class 機制,不重造 token。
 * localStorage('theme') 記偏好;FOUC 由 layout <body> 開頭的 inline script 提前套用 class。
 * 未 mount 前顯示 Sun(對應預設深色),避免 hydration 前後 icon 閃動。
 */
export default function ThemeToggle() {
  const [isDark, setIsDark] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* localStorage 不可用時仍即時生效,只是不記憶 */
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={mounted ? (isDark ? "切換至淺色模式" : "切換至深色模式") : "切換主題"}
      title="切換主題"
      className="ml-2 grid size-8 shrink-0 place-items-center rounded-full border border-border bg-card text-muted-foreground transition-colors hover:text-foreground"
    >
      {mounted && !isDark ? <Moon size={16} /> : <Sun size={16} />}
    </button>
  );
}
