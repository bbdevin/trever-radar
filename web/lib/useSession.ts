"use client";

import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

export type AppProfile = {
  user_id: string;
  email: string;
  display_name: string | null;
  avatar_url: string | null;
  role: "user" | "admin";
  status: "pending" | "approved" | "rejected";
};

export type SessionState = {
  session: Session | null;
  profile: AppProfile | null;
  loading: boolean;
  approved: boolean;
  isAdmin: boolean;
};

async function fetchProfile(userId: string, email?: string | null): Promise<AppProfile | null> {
  const { data, error } = await supabase
    .from("app_profiles")
    .select("user_id, email, display_name, avatar_url, role, status")
    .eq("user_id", userId)
    .maybeSingle();
  if (data) return data as AppProfile;
  // 表尚未建立時不鎖站,避免 SQL 還沒跑就被前端閘門擋下。表存在後走真實 RLS。
  if (error && /app_profiles|schema cache|does not exist/i.test(error.message)) {
    const isAdminEmail = (email ?? "").toLowerCase() === "a7033140327k@gmail.com";
    return {
      user_id: userId,
      email: email ?? "",
      display_name: null,
      avatar_url: null,
      role: isAdminEmail ? "admin" : "user",
      status: "approved",
    };
  }
  return null;
}

/** 查 profile;剛登入時 profile row 可能還沒被 trigger 建好,null 時等 700ms 重試一次。 */
async function fetchProfileWithRetry(s: Session): Promise<AppProfile | null> {
  let row = await fetchProfile(s.user.id, s.user.email);
  if (!row) {
    await new Promise((r) => setTimeout(r, 700));
    row = await fetchProfile(s.user.id, s.user.email);
  }
  return row;
}

function derive(session: Session | null, profile: AppProfile | null, loading: boolean): SessionState {
  const approved = profile?.status === "approved";
  const isAdmin = approved && profile?.role === "admin";
  return { session, profile, loading, approved, isAdmin };
}

const SessionContext = createContext<SessionState | null>(null);

/**
 * 全站共用一份登入狀態(docs/44 W-P0)。以前每個 useSession() 呼叫點各自訂閱並各查兩次
 * app_profiles,首頁每張卡片的 ★ 都算一個,載入時打出近百次請求。
 * 只訂閱 onAuthStateChange(INITIAL_SESSION 即涵蓋初次載入);只有使用者換人(含登出)
 * 才重查 profile,TOKEN_REFRESHED / 同一人的 SIGNED_IN 只更新 session 物件。
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<AppProfile | null>(null);
  const [loading, setLoading] = useState(true);
  // undefined = 還沒收到第一個事件;null = 未登入。
  const userIdRef = useRef<string | null | undefined>(undefined);
  const seqRef = useRef(0);

  useEffect(() => {
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      const uid = s?.user.id ?? null;
      if (uid === userIdRef.current) return;
      userIdRef.current = uid;
      const seq = ++seqRef.current;
      if (!s) {
        setProfile(null);
        setLoading(false);
        return;
      }
      void fetchProfileWithRetry(s).then((row) => {
        if (seq !== seqRef.current) return; // 期間已換人或登出,丟掉舊結果
        setProfile(row);
        setLoading(false);
      });
    });
    return () => sub.subscription.unsubscribe();
  }, []);

  const value = useMemo(() => derive(session, profile, loading), [session, profile, loading]);
  return createElement(SessionContext.Provider, { value }, children);
}

/** 沒有 SessionProvider 時的舊行為(每個呼叫點自己訂閱);只作安全網。 */
function useStandaloneSession(enabled: boolean): SessionState {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<AppProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (s: Session | null) => {
    setSession(s);
    if (!s) {
      setProfile(null);
      setLoading(false);
      return;
    }
    const row = await fetchProfileWithRetry(s);
    setProfile(row);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    supabase.auth.getSession().then(({ data }) => {
      void load(data.session);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      void load(s);
    });
    return () => sub.subscription.unsubscribe();
  }, [enabled, load]);

  return derive(session, profile, loading);
}

export function useSession(): SessionState {
  const shared = useContext(SessionContext);
  const standalone = useStandaloneSession(shared === null);
  return shared ?? standalone;
}

export function signInWithGoogle() {
  const redirectTo = typeof window === "undefined" ? undefined : `${window.location.origin}/`;
  void supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo },
  });
}

export function signOut() {
  void supabase.auth.signOut();
}
