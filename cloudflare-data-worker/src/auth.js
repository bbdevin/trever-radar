// Supabase JWT 本地驗簽 + app_profiles 狀態快取(docs/44 P1 Worker 驗證優化;門禁真相 docs/31 WP-B7)
//
// 2026-10-04 Planner 定案(獨立資安審查通過、L1–L4 已修;使用者核准後才可上線):
//   - 只接受 ES256(釘死 alg),以 Supabase JWKS 本地驗簽,不再呼叫 /auth/v1/user。
//   - 沒有 HS256 fallback;Worker 不持有 service_role key。
//   - app_profiles 仍以使用者自己的 JWT 經 RLS 讀(URL/headers 與舊版相同),
//     結果以 sub 為鍵快取 5 分(REST 非 2xx 只快取 45 秒)。
//   - 同一 sub 同時多個請求只查一次 REST;JWKS 同時只抓一次。
//   - 驗簽(步驟 1–5)每個請求都跑:token 過期立即 401,快取只存 sub → 狀態。
//   - 絕不 log token。
//
// 本檔只放可注入依賴(fetch / now / subtle)的純函式與 createAuthorizer;
// 路由、資產、標頭、service key 比對留在 index.js。

// ---- 常數(調整前先過資安審查) -------------------------------------------
export const JWKS_TTL_MS = 10 * 60 * 1000; // isolate 記憶體內 JWKS 有效期
export const JWKS_CF_CACHE_TTL_S = 600; // fetch 的 Cloudflare 邊緣快取秒數
export const JWKS_FORCE_MIN_MS = 60 * 1000; // 未知 kid 強制重抓,每 60 秒最多一次
export const JWKS_FAIL_BACKOFF_MS = 10 * 1000; // 完全沒有金鑰時,抓取失敗後的重試退避
export const PROFILE_TTL_MS = 5 * 60 * 1000; // sub → ok/denied 快取(= 撤銷最長延遲)
export const PROFILE_FAIL_TTL_MS = 45 * 1000; // REST 非 2xx 的負快取
export const CACHE_MAX_ENTRIES = 1000; // profile 快取上限,超過淘汰最舊
export const CLOCK_SKEW_S = 60; // 只用於 iat/nbf;exp 沒有寬限
export const MAX_TOKEN_LENGTH = 8 * 1024; // token 字元上限(base64url 皆 ASCII = 位元組)

export const jwksUrl = (env) => `${env.SUPABASE_URL}/auth/v1/.well-known/jwks.json`;
export const expectedIssuer = (env) => `${env.SUPABASE_URL}/auth/v1`;
export const profileUrl = (env, sub) =>
  `${env.SUPABASE_URL}/rest/v1/app_profiles?select=status&user_id=eq.${encodeURIComponent(sub)}`;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const JWT_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const B64URL_RE = /^[A-Za-z0-9_-]*$/;

const LOGIN_REQUIRED = Object.freeze({ ok: false, status: 401, message: "login required" });
const NOT_APPROVED = Object.freeze({ ok: false, status: 403, message: "not approved" });
const LOOKUP_FAILED = Object.freeze({ ok: false, status: 503, message: "auth lookup failed" });
const NOT_CONFIGURED = Object.freeze({ ok: false, status: 503, message: "auth not configured" });
const ALLOWED = Object.freeze({ ok: true });

const utf8 = new TextEncoder();
const utf8Strict = new TextDecoder("utf-8", { fatal: true });

class JwksUnavailableError extends Error {}

// ---- 純函式 ---------------------------------------------------------------

/** 與舊版相同的 Bearer 解析;回傳 "" 代表沒有 token */
export function bearerToken(request) {
  const h = request.headers.get("Authorization") || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

/** base64url(無 padding)→ Uint8Array;格式不合回 null */
export function b64urlDecode(s) {
  if (typeof s !== "string" || !B64URL_RE.test(s) || s.length % 4 === 1) return null;
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
  let bin;
  try {
    bin = atob(b64);
  } catch {
    return null;
  }
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function decodeJsonObject(segment) {
  const bytes = b64urlDecode(segment);
  if (!bytes) return null;
  let value;
  try {
    value = JSON.parse(utf8Strict.decode(bytes));
  } catch {
    return null;
  }
  return value && typeof value === "object" && !Array.isArray(value) ? value : null;
}

/** 步驟 1:長度 ≤ 8KB、恰好三段非空 base64url、header/payload 為 JSON 物件 */
export function parseToken(token) {
  if (typeof token !== "string" || token.length === 0 || token.length > MAX_TOKEN_LENGTH) return null;
  if (!JWT_RE.test(token)) return null;
  const [h, p, s] = token.split(".");
  const header = decodeJsonObject(h);
  const payload = decodeJsonObject(p);
  const signature = b64urlDecode(s);
  if (!header || !payload || !signature) return null;
  return { header, payload, signature, signingInput: `${h}.${p}` };
}

/** 步驟 2:alg 釘死 ES256;kid 非空字串;typ 缺或 "JWT";帶 crit 一律拒(RFC 7515 §4.1.11) */
export function checkHeader(header) {
  if (header.alg !== "ES256") return false;
  if (typeof header.kid !== "string" || header.kid.length === 0) return false;
  if (header.typ !== undefined && header.typ !== "JWT") return false;
  if (header.crit !== undefined) return false;
  return true;
}

const isFiniteNumber = (v) => typeof v === "number" && Number.isFinite(v);

/**
 * 步驟 3:claims。通過回 { sub, anonymous },不通過回 null。
 * is_anonymous 只標記,403 等驗簽通過後才回(未驗簽的 token 一律 401)。
 */
export function checkClaims(payload, env, nowMs) {
  if (!isFiniteNumber(payload.exp) || payload.exp * 1000 <= nowMs) return null; // exp 無寬限
  const latest = nowMs / 1000 + CLOCK_SKEW_S;
  for (const k of ["iat", "nbf"]) {
    if (payload[k] === undefined) continue;
    if (!isFiniteNumber(payload[k]) || payload[k] > latest) return null;
  }
  if (payload.iss !== expectedIssuer(env)) return null;
  const aud = payload.aud;
  const audOk = aud === "authenticated" || (Array.isArray(aud) && aud.includes("authenticated"));
  if (!audOk) return null;
  if (payload.role !== "authenticated") return null;
  if (typeof payload.sub !== "string" || !UUID_RE.test(payload.sub)) return null;
  return { sub: payload.sub, anonymous: payload.is_anonymous === true };
}

/** 步驟 4:JWKS 中可用的金鑰 = EC / P-256 / alg 缺或 ES256 / use 缺或 sig */
export function usableJwk(k) {
  return (
    !!k &&
    typeof k === "object" &&
    k.kty === "EC" &&
    k.crv === "P-256" &&
    (k.alg === undefined || k.alg === "ES256") &&
    (k.use === undefined || k.use === "sig") &&
    typeof k.kid === "string" &&
    k.kid.length > 0 &&
    typeof k.x === "string" &&
    typeof k.y === "string"
  );
}

// ---- 有狀態的驗證器(isolate 內共用) --------------------------------------

/**
 * @param {{ fetch: typeof fetch, now: () => number, subtle?: SubtleCrypto }} deps
 */
export function createAuthorizer({ fetch: fetchFn, now, subtle }) {
  const crypto = () => subtle || globalThis.crypto.subtle;

  // JWKS:kid → CryptoKey
  let keys = null; // null = 沒有任何可用金鑰 → fail closed(503)
  // 到期即重抓:成功 = +10 分;權威回應但無可用金鑰 / 抓取失敗且無金鑰 = +10 秒;
  // 抓取失敗但有舊金鑰 = +60 秒
  let jwksRefreshAt = 0;
  let lastForcedAt = -Infinity;
  let jwksInflight = null;

  // profile:sub → { kind: "ok" | "denied" | "invalid", expiresAt }
  const profileCache = new Map();
  const profileInflight = new Map();

  /** 共用的 in-flight promise 交給 waitUntil,避免發起請求被取消後其他等待者卡住 */
  function keepAlive(ctx, p) {
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(p.then(() => {}, () => {}));
  }

  async function loadJwks(env) {
    let list;
    try {
      const res = await fetchFn(jwksUrl(env), {
        // 只有 2xx 進邊緣快取;錯誤回應不快取(review L2)
        cf: {
          cacheTtlByStatus: { "200-299": JWKS_CF_CACHE_TTL_S, "300-599": 0 },
          cacheEverything: true,
        },
      });
      if (!res.ok) throw new Error("jwks status");
      const body = await res.json();
      if (!body || !Array.isArray(body.keys)) throw new Error("jwks malformed");
      list = body.keys;
    } catch {
      // 網路錯誤 / 非 2xx / 無法解析:有舊金鑰 → 沿用,60 秒後再試;
      // 完全沒有 → 呼叫端 fail closed(503),10 秒內不再重抓(review L4)
      jwksRefreshAt = now() + (keys ? JWKS_FORCE_MIN_MS : JWKS_FAIL_BACKOFF_MS);
      return;
    }
    // 權威回應(2xx + keys 陣列):一律整組替換,即使沒有任何可用金鑰(review L1)
    const next = new Map();
    for (const jwk of list) {
      if (!usableJwk(jwk) || next.has(jwk.kid)) continue;
      try {
        const key = await crypto().importKey(
          "jwk",
          { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y },
          { name: "ECDSA", namedCurve: "P-256" },
          false,
          ["verify"],
        );
        next.set(jwk.kid, key);
      } catch {
        // 壞掉的單把金鑰略過,不影響其他金鑰
      }
    }
    if (next.size === 0) {
      keys = null; // 舊金鑰一併作廢 → 503,10 秒後再看
      jwksRefreshAt = now() + JWKS_FAIL_BACKOFF_MS;
      return;
    }
    keys = next; // 整組替換:JWKS 移除的 kid 立即失效
    jwksRefreshAt = now() + JWKS_TTL_MS;
  }

  function refreshJwks(env, ctx) {
    if (!jwksInflight) {
      const p = loadJwks(env).finally(() => {
        if (jwksInflight === p) jwksInflight = null;
      });
      jwksInflight = p;
      keepAlive(ctx, p);
    }
    return jwksInflight;
  }

  async function getKey(env, kid, ctx) {
    let justLoaded = false;
    if (now() >= jwksRefreshAt) {
      // jwksRefreshAt 初值 0 → 第一次必抓;無金鑰且在退避期內 → 不抓,直接 503
      await refreshJwks(env, ctx);
      justLoaded = true;
    }
    if (!keys) throw new JwksUnavailableError();
    if (keys.has(kid)) return keys.get(kid);
    if (justLoaded) return null; // 剛抓完仍沒有,不再重抓
    const t = now();
    if (t - lastForcedAt < JWKS_FORCE_MIN_MS) return null;
    lastForcedAt = t;
    await refreshJwks(env, ctx);
    return keys && keys.has(kid) ? keys.get(kid) : null;
  }

  function cacheSet(sub, entry) {
    profileCache.delete(sub);
    profileCache.set(sub, entry);
    while (profileCache.size > CACHE_MAX_ENTRIES) {
      profileCache.delete(profileCache.keys().next().value);
    }
  }

  async function queryProfile(env, sub, token) {
    const res = await fetchFn(profileUrl(env, sub), {
      headers: {
        Authorization: `Bearer ${token}`,
        apikey: env.SUPABASE_PUBLISHABLE_KEY,
      },
    });
    if (!res.ok) {
      cacheSet(sub, { kind: "invalid", expiresAt: now() + PROFILE_FAIL_TTL_MS });
      return "invalid";
    }
    const rows = await res.json();
    const approved = Array.isArray(rows) && rows[0] && rows[0].status === "approved";
    const kind = approved ? "ok" : "denied";
    cacheSet(sub, { kind, expiresAt: now() + PROFILE_TTL_MS });
    return kind;
  }

  function lookupStatus(env, sub, token, ctx) {
    const hit = profileCache.get(sub);
    if (hit) {
      if (hit.expiresAt > now()) return Promise.resolve(hit.kind);
      profileCache.delete(sub);
    }
    let p = profileInflight.get(sub);
    if (!p) {
      p = queryProfile(env, sub, token).finally(() => {
        if (profileInflight.get(sub) === p) profileInflight.delete(sub);
      });
      profileInflight.set(sub, p);
      keepAlive(ctx, p);
    }
    return p;
  }

  async function verifySignature(key, parsed) {
    if (parsed.signature.byteLength !== 64) return false; // ES256 raw r||s
    try {
      return await crypto().verify(
        { name: "ECDSA", hash: "SHA-256" },
        key,
        parsed.signature,
        utf8.encode(parsed.signingInput),
      );
    } catch {
      return false;
    }
  }

  /** JWT 路徑(service key 判斷在 index.js,先於本函式) */
  async function authorize(request, env, ctx) {
    const token = bearerToken(request);
    if (!token) return LOGIN_REQUIRED;
    if (!env.SUPABASE_URL || !env.SUPABASE_PUBLISHABLE_KEY) return NOT_CONFIGURED;
    try {
      const parsed = parseToken(token); // 1
      if (!parsed || !checkHeader(parsed.header)) return LOGIN_REQUIRED; // 2
      const claims = checkClaims(parsed.payload, env, now()); // 3
      if (!claims) return LOGIN_REQUIRED;
      const key = await getKey(env, parsed.header.kid, ctx); // 4
      if (!key) return LOGIN_REQUIRED;
      if (!(await verifySignature(key, parsed))) return LOGIN_REQUIRED; // 5
      if (claims.anonymous) return NOT_APPROVED;
      const kind = await lookupStatus(env, claims.sub, token, ctx); // 6
      if (kind === "ok") return ALLOWED;
      if (kind === "denied") return NOT_APPROVED;
      return LOGIN_REQUIRED;
    } catch {
      // JWKS 完全無金鑰、REST fetch 丟例外、或任何非預期錯誤 → fail closed
      return LOOKUP_FAILED;
    }
  }

  return {
    authorize,
    // 測試用唯讀觀察點
    _debug: {
      profileCacheSize: () => profileCache.size,
      profileInflightSize: () => profileInflight.size,
      jwksKeyCount: () => (keys ? keys.size : 0),
    },
  };
}
