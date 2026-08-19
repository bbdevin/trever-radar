"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useSession } from "@/lib/useSession";
import type { AppProfile } from "@/lib/useSession";
import { cn } from "@/lib/utils";

type ProfileRow = AppProfile & {
  created_at: string;
  approved_at: string | null;
};

export default function AdminPage() {
  const { isAdmin, loading, session } = useSession();
  const [rows, setRows] = useState<ProfileRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tab, setTab] = useState<"pending" | "all">("pending");

  const refresh = useCallback(async () => {
    const { data, error: qErr } = await supabase
      .from("app_profiles")
      .select("user_id, email, display_name, avatar_url, role, status, created_at, approved_at")
      .order("created_at", { ascending: false });
    if (qErr) {
      setError(qErr.message);
      return;
    }
    setError(null);
    setRows((data ?? []) as ProfileRow[]);
  }, []);

  useEffect(() => {
    if (isAdmin) void refresh();
  }, [isAdmin, refresh]);

  const setStatus = async (userId: string, status: "approved" | "rejected" | "pending") => {
    if (!session) return;
    setBusy(userId);
    const patch: Record<string, unknown> = { status };
    if (status === "approved") {
      patch.approved_at = new Date().toISOString();
      patch.approved_by = session.user.id;
    } else {
      patch.approved_at = null;
      patch.approved_by = null;
    }
    const { error: uErr } = await supabase.from("app_profiles").update(patch).eq("user_id", userId);
    setBusy(null);
    if (uErr) {
      setError(uErr.message);
      return;
    }
    await refresh();
  };

  if (loading) return <div className="py-16 text-center text-sm text-muted-foreground">載入中…</div>;
  if (!isAdmin) {
    return (
      <div className="py-16 text-center text-sm text-muted-foreground">
        這頁只有管理員可以進入。
      </div>
    );
  }

  const shown = tab === "pending" ? rows.filter((r) => r.status === "pending") : rows;

  return (
    <div className="py-4">
      <h1 className="mb-1 text-[18px] font-extrabold">使用者核准</h1>
      <p className="mb-4 text-[12.5px] text-muted-foreground">
        新 Google 登入預設為等待核准。既有帳號已自動核准;可在此放行或拒絕。
      </p>
      {error && <p className="mb-3 text-[13px] text-destructive">{error}</p>}
      <div className="mb-3 flex gap-1 rounded-full border border-border bg-card p-[3px] w-fit">
        <button
          type="button"
          className={cn(
            "rounded-full px-3.5 py-1.5 text-[13px] font-semibold",
            tab === "pending" ? "bg-muted text-foreground" : "text-muted-foreground",
          )}
          onClick={() => setTab("pending")}
        >
          待核准 ({rows.filter((r) => r.status === "pending").length})
        </button>
        <button
          type="button"
          className={cn(
            "rounded-full px-3.5 py-1.5 text-[13px] font-semibold",
            tab === "all" ? "bg-muted text-foreground" : "text-muted-foreground",
          )}
          onClick={() => setTab("all")}
        >
          全部 ({rows.length})
        </button>
      </div>
      {shown.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          {tab === "pending" ? "目前沒有等待核准的帳號。" : "尚無使用者資料。"}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((r) => (
            <li
              key={r.user_id}
              className="flex min-w-0 flex-col gap-2 rounded-[var(--r-md)] border border-border bg-card px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 items-center gap-3">
                {r.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={r.avatar_url}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="size-10 shrink-0 rounded-full border border-border object-cover"
                  />
                ) : (
                  <span className="grid size-10 shrink-0 place-items-center rounded-full border border-border bg-muted text-[13px] font-bold text-muted-foreground">
                    {(r.display_name ?? r.email).slice(0, 1).toUpperCase()}
                  </span>
                )}
                <div className="min-w-0">
                  <div className="truncate font-semibold text-foreground">{r.display_name || r.email}</div>
                  {r.display_name ? (
                    <div className="truncate text-[12px] text-muted-foreground">{r.email}</div>
                  ) : null}
                  <div className="mt-0.5 text-[11.5px] text-muted-foreground">
                    {r.role === "admin" ? "管理員" : "使用者"} · {statusLabel(r.status)} · {r.created_at.slice(0, 10)}
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {r.status !== "approved" && (
                  <button
                    type="button"
                    disabled={busy === r.user_id}
                    onClick={() => setStatus(r.user_id, "approved")}
                    className="min-h-9 cursor-pointer rounded-md bg-secondary px-3 text-[12.5px] font-semibold text-foreground hover:bg-muted disabled:opacity-50"
                  >
                    核准
                  </button>
                )}
                {r.status !== "rejected" && r.role !== "admin" && (
                  <button
                    type="button"
                    disabled={busy === r.user_id}
                    onClick={() => setStatus(r.user_id, "rejected")}
                    className="min-h-9 cursor-pointer rounded-md border border-border px-3 text-[12.5px] font-semibold text-muted-foreground hover:text-foreground disabled:opacity-50"
                  >
                    拒絕
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function statusLabel(status: AppProfile["status"]) {
  if (status === "approved") return "已核准";
  if (status === "rejected") return "已拒絕";
  return "待核准";
}
