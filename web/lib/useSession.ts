"use client";

import { useCallback, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

export type AppProfile = {
  user_id: string;
  email: string;
  role: "user" | "admin";
  status: "pending" | "approved" | "rejected";
};

async function fetchProfile(userId: string, email?: string | null): Promise<AppProfile | null> {
  const { data, error } = await supabase
    .from("app_profiles")
    .select("user_id, email, role, status")
    .eq("user_id", userId)
    .maybeSingle();
  if (data) return data as AppProfile;
  // 表尚未建立時不鎖站,避免 SQL 還沒跑就被前端閘門擋下。表存在後走真實 RLS。
  if (error && /app_profiles|schema cache|does not exist/i.test(error.message)) {
    const isAdminEmail = (email ?? "").toLowerCase() === "a7033140327k@gmail.com";
    return {
      user_id: userId,
      email: email ?? "",
      role: isAdminEmail ? "admin" : "user",
      status: "approved",
    };
  }
  return null;
}

export function useSession() {
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
    let row = await fetchProfile(s.user.id, s.user.email);
    if (!row) {
      await new Promise((r) => setTimeout(r, 700));
      row = await fetchProfile(s.user.id, s.user.email);
    }
    setProfile(row);
    setLoading(false);
  }, []);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      void load(data.session);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      void load(s);
    });
    return () => sub.subscription.unsubscribe();
  }, [load]);

  const approved = profile?.status === "approved";
  const isAdmin = approved && profile?.role === "admin";

  return { session, profile, loading, approved, isAdmin };
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
