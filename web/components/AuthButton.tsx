"use client";

import { LogOut, ShieldCheck } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut, useSession } from "@/lib/useSession";

/** 已登入使用者選單。未登入由 AuthGate 顯示全頁登入,此處不重複放按鈕。 */
export default function AuthButton() {
  const { session, loading, isAdmin } = useSession();

  if (loading) return <span className="ml-2 size-8" />;
  if (!session) return null;

  const meta = session.user.user_metadata as { avatar_url?: string; full_name?: string };
  const initial = (meta.full_name ?? session.user.email ?? "?").slice(0, 1).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="ml-1 grid size-11 shrink-0 place-items-center overflow-hidden rounded-full border border-border bg-card text-sm font-bold text-muted-foreground transition-colors hover:text-foreground"
        title={session.user.email ?? ""}
      >
        {meta.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={meta.avatar_url} alt="" referrerPolicy="no-referrer" className="size-full object-cover" />
        ) : (
          initial
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="font-normal text-muted-foreground break-all">
            {session.user.email}
          </DropdownMenuLabel>
          {isAdmin && (
            <DropdownMenuItem onClick={() => { window.location.href = "/admin"; }}>
              <ShieldCheck />
              使用者核准
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => signOut()}>
            <LogOut />
            登出
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
