"use client";

import { supabase } from "@/lib/supabase";

/** 讀 `/data/*` 時帶上 Supabase JWT。Worker 驗簽 + 核准狀態後才回 JSON。
 *  cache: no-store — 行情不得走瀏覽器 HTTP cache；SW 也不攔截 /data。 */
export async function dataFetch(path: string, init?: RequestInit): Promise<Response> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(path, { ...init, cache: "no-store", headers });
}
