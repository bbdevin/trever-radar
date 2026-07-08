"use client";

import { useState } from "react";
import { signInWithGoogle, signOut, useSession } from "@/lib/useSession";

/** Google 登入/使用者選單(Supabase Auth) */
export default function AuthButton() {
  const { session, loading } = useSession();
  const [menu, setMenu] = useState(false);

  if (loading) return <span className="auth-slot" />;

  if (!session) {
    return (
      <button className="auth-btn" onClick={signInWithGoogle} title="以 Google 帳戶登入">
        <svg width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
          <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3a7.2 7.2 0 0 1-10.8-3.8H1.2v3.1A12 12 0 0 0 12 24z" />
          <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.2a12 12 0 0 0 0 10.8l4.1-3.1z" />
          <path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8L20.1 3A12 12 0 0 0 1.2 6.6l4.1 3.1A7.2 7.2 0 0 1 12 4.8z" />
        </svg>
        登入
      </button>
    );
  }

  const meta = session.user.user_metadata as { avatar_url?: string; full_name?: string };
  return (
    <div className="auth-user">
      <button className="auth-avatar" onClick={() => setMenu(!menu)} title={session.user.email ?? ""}>
        {meta.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={meta.avatar_url} alt="" referrerPolicy="no-referrer" />
        ) : (
          <span>{(meta.full_name ?? session.user.email ?? "?").slice(0, 1).toUpperCase()}</span>
        )}
      </button>
      {menu && (
        <div className="auth-menu" onMouseLeave={() => setMenu(false)}>
          <div className="auth-email">{session.user.email}</div>
          <button onClick={() => { setMenu(false); signOut(); }}>登出</button>
        </div>
      )}
    </div>
  );
}
