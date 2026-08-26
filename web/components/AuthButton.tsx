"use client";

import { ALargeSmall, LogOut, Moon, ShieldCheck, Sun } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FONT_SCALE_LABEL, useUserPrefs } from "@/lib/userPrefs";
import { signOut, useSession } from "@/lib/useSession";

/** 已登入使用者選單。字級／主題在登出上方（本機+帳號）。 */
export default function AuthButton() {
  const { session, loading, isAdmin } = useSession();
  const { fontScale, theme, cycleFontScale, toggleTheme } = useUserPrefs();

  if (loading) return <span className="ml-2 size-8" />;
  if (!session) return null;

  const meta = session.user.user_metadata as { avatar_url?: string; full_name?: string };
  const initial = (meta.full_name ?? session.user.email ?? "?").slice(0, 1).toUpperCase();
  const isDark = theme === "dark";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="ml-1 grid size-11 shrink-0 cursor-pointer place-items-center overflow-hidden rounded-full border border-border bg-card text-sm font-bold text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        title={session.user.email ?? ""}
      >
        {meta.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={meta.avatar_url} alt="" referrerPolicy="no-referrer" className="size-full object-cover" />
        ) : (
          initial
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[220px]">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal break-all text-muted-foreground">
            {session.user.email}
          </DropdownMenuLabel>
          {isAdmin && (
            <DropdownMenuItem
              className="cursor-pointer"
              onClick={() => {
                window.location.href = "/admin";
              }}
            >
              <ShieldCheck />
              使用者核准
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            className="cursor-pointer"
            onSelect={(e) => {
              e.preventDefault();
              void cycleFontScale();
            }}
          >
            <ALargeSmall />
            文字大小：{FONT_SCALE_LABEL[fontScale]}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="cursor-pointer"
            onSelect={(e) => {
              e.preventDefault();
              void toggleTheme();
            }}
          >
            {isDark ? <Sun /> : <Moon />}
            {isDark ? "切換淺色模式" : "切換深色模式"}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" className="cursor-pointer" onClick={() => signOut()}>
            <LogOut />
            登出
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
