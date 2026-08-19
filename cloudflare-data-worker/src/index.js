// trever-radar-data worker(docs/31 §3.2 + WP-B7)
// /data/* 與 /data-preview/* → 靜態 JSON 資產。
// 2026-08-19:必須驗身分。通過條件二擇一:
//   1. X-Radar-Service-Key 對上 wrangler secret RADAR_SERVICE_KEY(盤中 worker)
//   2. Authorization: Bearer <Supabase JWT>,且 app_profiles.status = approved
// 未通過一律 401/403,不得回 JSON。Access 拆除前這層已生效 = 雙鎖;拆除後這層是唯一門鎖。

const NO_STORE = new Set(["radar.json", "meta.json"]);
const CACHE_TTL_SECONDS = 60;
const AUTH_CACHE_TTL_MS = 45_000;

/** isolate 內短快取,同一頁連抓多個 JSON 時少打 Supabase */
const authCache = new Map();

function jsonError(status, message) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const encoder = new TextEncoder();
  const aa = encoder.encode(a);
  const bb = encoder.encode(b);
  if (aa.byteLength !== bb.byteLength) return false;
  let out = 0;
  for (let i = 0; i < aa.byteLength; i++) out |= aa[i] ^ bb[i];
  return out === 0;
}

function bearerToken(request) {
  const h = request.headers.get("Authorization") || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

async function lookupUser(token, env) {
  const now = Date.now();
  const hit = authCache.get(token);
  if (hit && hit.exp > now) return hit;

  const miss = { kind: "invalid", exp: now + AUTH_CACHE_TTL_MS };
  const userRes = await fetch(`${env.SUPABASE_URL}/auth/v1/user`, {
    headers: {
      Authorization: `Bearer ${token}`,
      apikey: env.SUPABASE_PUBLISHABLE_KEY,
    },
  });
  if (!userRes.ok) {
    authCache.set(token, miss);
    return miss;
  }
  const user = await userRes.json();
  const uid = user && user.id;
  if (!uid) {
    authCache.set(token, miss);
    return miss;
  }

  const profileRes = await fetch(
    `${env.SUPABASE_URL}/rest/v1/app_profiles?select=status&user_id=eq.${encodeURIComponent(uid)}`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
        apikey: env.SUPABASE_PUBLISHABLE_KEY,
      },
    },
  );
  if (!profileRes.ok) {
    authCache.set(token, miss);
    return miss;
  }
  const rows = await profileRes.json();
  const approved = Array.isArray(rows) && rows[0] && rows[0].status === "approved";
  const result = { kind: approved ? "ok" : "denied", exp: now + AUTH_CACHE_TTL_MS };
  authCache.set(token, result);
  return result;
}

async function authorize(request, env) {
  const serviceKey = env.RADAR_SERVICE_KEY || "";
  const presented = request.headers.get("X-Radar-Service-Key") || "";
  if (serviceKey && presented && timingSafeEqual(presented, serviceKey)) {
    return { ok: true };
  }

  const token = bearerToken(request);
  if (!token) return { ok: false, status: 401, message: "login required" };
  if (!env.SUPABASE_URL || !env.SUPABASE_PUBLISHABLE_KEY) {
    return { ok: false, status: 503, message: "auth not configured" };
  }
  try {
    const looked = await lookupUser(token, env);
    if (looked.kind === "ok") return { ok: true };
    if (looked.kind === "denied") return { ok: false, status: 403, message: "not approved" };
    return { ok: false, status: 401, message: "login required" };
  } catch {
    return { ok: false, status: 503, message: "auth lookup failed" };
  }
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const m = url.pathname.match(/^\/(data|data-preview)\/(.+)$/);
    if (!m) return new Response("not found", { status: 404 });

    if (m[2].includes("..") || m[2].includes("//") || m[2].includes("\\")) {
      return new Response("bad request", { status: 400 });
    }

    const gate = await authorize(request, env);
    if (!gate.ok) return jsonError(gate.status, gate.message);

    const assetReq = new Request(new URL(`/${m[2]}`, url.origin), {
      method: request.method,
      headers: request.headers,
    });
    const resp = await env.ASSETS.fetch(assetReq);
    if (resp.status === 404) return new Response("not found", { status: 404 });

    const headers = new Headers(resp.headers);
    const basename = m[2].split("/").pop();
    headers.set(
      "cache-control",
      NO_STORE.has(basename) ? "private, no-store" : `private, max-age=${CACHE_TTL_SECONDS}`,
    );
    headers.set("vary", "Authorization, X-Radar-Service-Key");
    return new Response(resp.body, { status: resp.status, headers });
  },
};
