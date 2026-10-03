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

/** row = 查到的 profile(null = 沒有這列);ok = false 表示這次是連線/伺服器錯誤,不是確定的答案。 */
type ProfileResult = { row: AppProfile | null; ok: boolean };

async function fetchProfile(userId: string, email?: string | null): Promise<ProfileResult> {
  const { data, error } = await supabase
    .from("app_profiles")
    .select("user_id, email, display_name, avatar_url, role, status")
    .eq("user_id", userId)
    .maybeSingle();
  if (data) return { row: data as AppProfile, ok: true };
  // 表尚未建立時不鎖站,避免 SQL 還沒跑就被前端閘門擋下。表存在後走真實 RLS。
  if (error && /app_profiles|schema cache|does not exist/i.test(error.message)) {
    const isAdminEmail = (email ?? "").toLowerCase() === "a7033140327k@gmail.com";
    return {
      row: {
        user_id: userId,
        email: email ?? "",
        display_name: null,
        avatar_url: null,
        role: isAdminEmail ? "admin" : "user",
        status: "approved",
      },
      ok: true,
    };
  }
  return { row: null, ok: !error };
}

/** 查 profile;剛登入時 profile row 可能還沒被 trigger 建好,null 時等 700ms 重試一次。 */
async function fetchProfileWithRetry(s: Session): Promise<ProfileResult> {
  let res = await fetchProfile(s.user.id, s.user.email);
  if (!res.row) {
    await new Promise((r) => setTimeout(r, 700));
    res = await fetchProfile(s.user.id, s.user.email);
  }
  return res;
}

/**
 * profile 一律綁 user_id:不屬於目前 session 使用者的 profile(換人後舊查詢結果還沒換掉)
 * 視為「尚未載入」——loading=true、不核准、不給 admin,絕不拿 A 的狀態放行 B。
 */
function derive(session: Session | null, profile: AppProfile | null, loading: boolean): SessionState {
  const foreign = profile !== null && profile.user_id !== session?.user.id;
  const own = foreign ? null : profile;
  const approved = session !== null && own?.status === "approved";
  const isAdmin = approved && own?.role === "admin";
  return { session, profile: own, loading: loading || foreign, approved, isAdmin };
}

function sameProfile(a: AppProfile | null, b: AppProfile | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.user_id === b.user_id &&
    a.email === b.email &&
    a.display_name === b.display_name &&
    a.avatar_url === b.avatar_url &&
    a.role === b.role &&
    a.status === b.status
  );
}

type ProviderState = {
  session: Session | null;
  profile: AppProfile | null;
  /** 目前 profile 是替哪個 user 查的;undefined = 還沒查完(或尚未收到第一個事件),null = 未登入。 */
  profileFor: string | null | undefined;
};

/** 同一使用者在背景重新確認 profile 的事件(分頁回到前景會發 SIGNED_IN、每小時 TOKEN_REFRESHED)。 */
const REVALIDATE_EVENTS = new Set(["SIGNED_IN", "TOKEN_REFRESHED", "USER_UPDATED"]);

const SessionContext = createContext<SessionState | null>(null);

/**
 * 全站共用一份登入狀態(docs/44 W-P0)。以前每個 useSession() 呼叫點各自訂閱並各查兩次
 * app_profiles,首頁每張卡片的 ★ 都算一個,載入時打出近百次請求。
 * 只訂閱 onAuthStateChange(INITIAL_SESSION 即涵蓋初次載入)。
 * - 換人(含登出):session 與「profile 未載入」在同一次 state 更新生效,舊 profile 不會套到新 session。
 * - 同一人的 SIGNED_IN(分頁回前景)/ TOKEN_REFRESHED / USER_UPDATED:背景重查 profile,
 *   不把 loading 翻回 true(閘門不閃),回來後更新 approved/isAdmin——管理員改核准狀態在使用者
 *   回到分頁時生效。同時間只會有一個查詢在飛(去重),首頁載入仍只打一次 app_profiles。
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProviderState>({ session: null, profile: null, profileFor: undefined });
  // undefined = 還沒收到第一個事件;null = 未登入。
  const userIdRef = useRef<string | null | undefined>(undefined);
  // 每次換人/登出 +1;查詢回來時世代不同就丟掉。
  const seqRef = useRef(0);
  // 目前在飛的查詢(背景重查用來去重);換人/登出時清掉。
  const inflightRef = useRef<object | null>(null);

  useEffect(() => {
    let alive = true;

    const load = (s: Session, background: boolean) => {
      if (background && inflightRef.current) return; // 已有查詢在飛,它的結果夠新
      const token = {};
      inflightRef.current = token;
      const seq = seqRef.current;
      const uid = s.user.id;
      void fetchProfileWithRetry(s).then(({ row, ok }) => {
        if (inflightRef.current === token) inflightRef.current = null;
        if (!alive || seq !== seqRef.current) return; // 期間已換人或登出,丟掉舊結果
        // 背景重查遇到連線/伺服器錯誤時保留上次確定的結果(資料端另有 Worker 把關);
        // 首次查詢失敗仍照舊走「帳號資料尚未建立」畫面。
        if (background && !ok) return;
        setState((prev) => {
          if (prev.session?.user.id !== uid) return prev;
          if (prev.profileFor === uid && sameProfile(prev.profile, row)) return prev;
          return { ...prev, profile: row, profileFor: uid };
        });
      });
    };

    const { data: sub } = supabase.auth.onAuthStateChange((event, s) => {
      const uid = s?.user.id ?? null;
      if (uid !== userIdRef.current) {
        userIdRef.current = uid;
        seqRef.current += 1;
        inflightRef.current = null;
        // session 與 profile 綁在同一次更新:換人當下就是「未載入」,不會短暫沿用前一人的 profile。
        setState({ session: s, profile: null, profileFor: s ? undefined : null });
        if (s) load(s, false);
        return;
      }
      if (!s) return; // 重複的登出事件
      setState((prev) => (prev.session === s ? prev : { ...prev, session: s }));
      if (REVALIDATE_EVENTS.has(event)) load(s, true);
    });
    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo(() => {
    const { session, profile, profileFor } = state;
    const loading = session ? profileFor !== session.user.id : profileFor === undefined;
    return derive(session, profileFor === session?.user.id ? profile : null, loading);
  }, [state]);
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
    const { row } = await fetchProfileWithRetry(s);
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
