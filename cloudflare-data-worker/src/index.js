// trever-radar-data worker(docs/31 §3.2 + WP-B7)
// /data/* 與 /data-preview/* → 靜態 JSON 資產。
// 2026-08-19:必須驗身分。通過條件二擇一:
//   1. X-Radar-Service-Key 對上 wrangler secret RADAR_SERVICE_KEY(盤中 worker)
//   2. Authorization: Bearer <Supabase JWT>,且 app_profiles.status = approved
// 未通過一律 401/403,不得回 JSON。Access 拆除前這層已生效 = 雙鎖;拆除後這層是唯一門鎖。
// 2026-10-04(docs/44 P1):JWT 改 ES256 + JWKS 本地驗簽、profile 以 sub 快取 5 分,邏輯在 auth.js。

import { createAuthorizer } from "./auth.js";

const NO_STORE = new Set(["radar.json", "meta.json"]);
const CACHE_TTL_SECONDS = 60;

/** isolate 內共用:JWKS 金鑰與 sub → app_profiles 狀態快取 */
const jwtAuth = createAuthorizer({
  fetch: (input, init) => fetch(input, init),
  now: () => Date.now(),
});

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

async function authorize(request, env, ctx) {
  const serviceKey = env.RADAR_SERVICE_KEY || "";
  const presented = request.headers.get("X-Radar-Service-Key") || "";
  if (serviceKey && presented && timingSafeEqual(presented, serviceKey)) {
    return { ok: true };
  }

  // 401 login required / 403 not approved / 503 auth not configured|auth lookup failed
  return jwtAuth.authorize(request, env, ctx);
}

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed", { status: 405 });
    }

    const url = new URL(request.url);
    const m = url.pathname.match(/^\/(data|data-preview)\/(.+)$/);
    if (!m) return new Response("not found", { status: 404 });

    if (m[2].includes("..") || m[2].includes("//") || m[2].includes("\\")) {
      return new Response("bad request", { status: 400 });
    }

    const gate = await authorize(request, env, ctx);
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
