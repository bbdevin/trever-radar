"use client";

import type { ReactNode } from "react";
import { signInWithGoogle, signOut, useSession } from "@/lib/useSession";
import ThemeToggle from "@/components/ThemeToggle";
import { Skeleton } from "@/components/ui/skeleton";

const GoogleIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
    <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3a7.2 7.2 0 0 1-10.8-3.8H1.2v3.1A12 12 0 0 0 12 24z" />
    <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.2a12 12 0 0 0 0 10.8l4.1-3.1z" />
    <path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8L20.1 3A12 12 0 0 0 1.2 6.6l4.1 3.1A7.2 7.2 0 0 1 12 4.8z" />
  </svg>
);

function GateShell({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-[100dvh] flex-col items-center justify-center bg-background px-5">
      <div className="absolute right-3 top-[calc(0.75rem+env(safe-area-inset-top))]">
        <ThemeToggle />
      </div>
      <div className="flex w-full max-w-[380px] flex-col items-center">
        <img
          src="/icons/trever-radar-mark.svg"
          alt=""
          aria-hidden="true"
          className="mb-4 size-14 rounded-[14px] shadow-[0_2px_10px_rgba(57,135,229,0.35)]"
        />
        <h1 className="text-[22px] font-extrabold tracking-tight text-foreground">Trever Radar</h1>
        <p className="mt-1 mb-7 text-[13.5px] text-muted-foreground">盤後找籌碼,盤中看發動</p>
        {children}
      </div>
    </div>
  );
}

function LoginScreen() {
  return (
    <GateShell>
      <div className="w-full rounded-[var(--r-lg)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <button
          type="button"
          onClick={signInWithGoogle}
          className="flex min-h-11 w-full cursor-pointer items-center justify-center gap-2 rounded-[10px] bg-secondary px-4 text-[14.5px] font-semibold text-foreground transition-colors hover:bg-muted"
        >
          <GoogleIcon />
          使用 Google 登入
        </button>
        <p className="mt-3 text-center text-[12px] text-muted-foreground">僅限受邀使用者。登入後需管理員核准。</p>
      </div>
    </GateShell>
  );
}

function PendingScreen({ status }: { status: "pending" | "rejected" | "missing" }) {
  const copy =
    status === "rejected"
      ? "這組帳號尚未通過核准,請聯絡管理員。"
      : status === "missing"
        ? "帳號資料尚未建立。若剛登入請稍候再重整;若持續出現,請聯絡管理員確認已執行核准表 SQL。"
        : "已送出申請,等待管理員核准後即可使用。";
  return (
    <GateShell>
      <div className="w-full rounded-[var(--r-lg)] border border-border bg-card p-5 shadow-[var(--shadow-card)]">
        <p className="text-center text-[14px] leading-relaxed text-foreground">{copy}</p>
        <button
          type="button"
          onClick={signOut}
          className="mt-4 flex min-h-11 w-full cursor-pointer items-center justify-center rounded-[10px] border border-border bg-background text-[14px] font-semibold text-muted-foreground transition-colors hover:text-foreground"
        >
          登出
        </button>
      </div>
    </GateShell>
  );
}

/** 未登入顯示登入頁;已登入但未核准顯示等待頁;核准後才渲染站內內容。 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const { session, profile, loading, approved } = useSession();

  if (loading) {
    return (
      <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-3">
        <Skeleton className="size-14 rounded-[14px]" />
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24 w-[min(100%,380px)] rounded-[var(--r-lg)]" />
      </div>
    );
  }

  if (!session) return <LoginScreen />;
  if (!approved) {
    const status = !profile ? "missing" : profile.status === "rejected" ? "rejected" : "pending";
    return <PendingScreen status={status} />;
  }
  return <>{children}</>;
}
