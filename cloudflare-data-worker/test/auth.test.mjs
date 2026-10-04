// node --test test/auth.test.mjs — src/auth.js 單元測試(注入 fetch / 假時鐘)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  createAuthorizer,
  CACHE_MAX_ENTRIES,
  JWKS_TTL_MS,
  PROFILE_TTL_MS,
  PROFILE_FAIL_TTL_MS,
} from "../src/auth.js";
import {
  ENV,
  ISS,
  SUB,
  T0,
  b64u,
  b64uJson,
  claims,
  fakeSupabase,
  makeEcKey,
  signEs256,
  signHs256,
  signRs256,
  subtle,
} from "./_fixtures.mjs";

const KEY = await makeEcKey("kid-current");
const OTHER = await makeEcKey("kid-other"); // 不在 JWKS 內

function setup({ keys = [KEY] } = {}) {
  const sb = fakeSupabase(keys);
  const clock = { t: T0 };
  const auth = createAuthorizer({ fetch: sb.fetch, now: () => clock.t, subtle });
  const run = (token, extraHeaders = {}) => {
    const headers = { ...extraHeaders };
    if (token !== undefined) headers.Authorization = `Bearer ${token}`;
    return auth.authorize(new Request("https://radar.example/data/x.json", { headers }), ENV);
  };
  return { sb, clock, auth, run };
}

const tok = (clock, over = {}, headerOver = {}, key = KEY) =>
  signEs256(key, claims(clock.t, over), headerOver);

const LOGIN = { ok: false, status: 401, message: "login required" };
const DENIED = { ok: false, status: 403, message: "not approved" };
const FAILED = { ok: false, status: 503, message: "auth lookup failed" };

test("valid ES256 + approved → ok; REST uses same URL/headers as before; no /auth/v1/user", async () => {
  const { sb, clock, run } = setup();
  const t = await tok(clock);
  assert.deepEqual(await run(t), { ok: true });
  assert.equal(sb.calls.jwks, 1);
  assert.deepEqual(sb.calls.jwksInit[0], { cf: { cacheTtl: 600, cacheEverything: true } });
  assert.equal(sb.calls.rest, 1);
  const { url, init } = sb.calls.restReqs[0];
  assert.equal(
    url,
    `${ENV.SUPABASE_URL}/rest/v1/app_profiles?select=status&user_id=eq.${encodeURIComponent(SUB)}`,
  );
  assert.deepEqual(init.headers, {
    Authorization: `Bearer ${t}`,
    apikey: ENV.SUPABASE_PUBLISHABLE_KEY,
  });
  assert.deepEqual(sb.calls.other, []);
});

test("exp: expired, exactly now, missing, non-number → 401 (no leeway)", async () => {
  const { sb, clock, run } = setup();
  const nowS = clock.t / 1000;
  assert.deepEqual(await run(await tok(clock, { exp: nowS - 1 })), LOGIN);
  assert.deepEqual(await run(await tok(clock, { exp: nowS })), LOGIN);
  assert.deepEqual(await run(await tok(clock, { exp: undefined })), LOGIN);
  assert.deepEqual(await run(await tok(clock, { exp: String(nowS + 3600) })), LOGIN);
  assert.equal(sb.calls.rest, 0);
});

test("token expires while status is cached → 401 immediately", async () => {
  const { sb, clock, run } = setup();
  const t = await tok(clock, { exp: clock.t / 1000 + 30 });
  assert.deepEqual(await run(t), { ok: true });
  clock.t += 30_000;
  assert.deepEqual(await run(t), LOGIN);
  assert.equal(sb.calls.rest, 1);
});

test("iat / nbf: ≤ now+60s ok, beyond → 401", async () => {
  const { clock, run } = setup();
  const nowS = clock.t / 1000;
  assert.deepEqual(await run(await tok(clock, { iat: nowS + 60, nbf: nowS + 60 })), { ok: true });
  assert.deepEqual(await run(await tok(clock, { iat: nowS + 61 })), LOGIN);
  assert.deepEqual(await run(await tok(clock, { nbf: nowS + 61 })), LOGIN);
  assert.deepEqual(await run(await tok(clock, { iat: "0" })), LOGIN);
});

test("alg pinned: HS256 (public x,y as HMAC secret), none, RS256 → 401 without network", async () => {
  const { sb, clock, run } = setup();
  const payload = claims(clock.t);
  const secret = new TextEncoder().encode(KEY.jwk.x + KEY.jwk.y);
  const hs = await signHs256(secret, { alg: "HS256", kid: KEY.kid, typ: "JWT" }, payload);
  assert.deepEqual(await run(hs), LOGIN);
  const none = `${b64uJson({ alg: "none", kid: KEY.kid, typ: "JWT" })}.${b64uJson(payload)}.`;
  assert.deepEqual(await run(none), LOGIN);
  const rs = await signRs256({ alg: "RS256", kid: KEY.kid, typ: "JWT" }, payload);
  assert.deepEqual(await run(rs), LOGIN);
  assert.equal(sb.calls.jwks, 0);
  assert.equal(sb.calls.rest, 0);
});

test("header: kid missing/empty/non-string, typ other than JWT, crit present → 401", async () => {
  const { clock, run } = setup();
  assert.deepEqual(await run(await tok(clock, {}, { kid: undefined })), LOGIN);
  assert.deepEqual(await run(await tok(clock, {}, { kid: "" })), LOGIN);
  assert.deepEqual(await run(await tok(clock, {}, { kid: 1 })), LOGIN);
  assert.deepEqual(await run(await tok(clock, {}, { typ: "at+jwt" })), LOGIN);
  assert.deepEqual(await run(await tok(clock, {}, { crit: ["exp"] })), LOGIN);
  assert.deepEqual(await run(await tok(clock, {}, { typ: undefined })), { ok: true });
});

test("unknown kid → one forced refetch then 401; second unknown kid within 60s does not refetch", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock)), { ok: true }); // warm JWKS
  assert.equal(sb.calls.jwks, 1);
  clock.t += 1_000;
  assert.deepEqual(await run(await tok(clock, {}, {}, OTHER)), LOGIN);
  assert.equal(sb.calls.jwks, 2);
  clock.t += 10_000;
  assert.deepEqual(await run(await tok(clock, {}, { kid: "another-unknown" }, OTHER)), LOGIN);
  assert.equal(sb.calls.jwks, 2);
  clock.t += 50_000; // 61s since last forced
  assert.deepEqual(await run(await tok(clock, {}, {}, OTHER)), LOGIN);
  assert.equal(sb.calls.jwks, 3);
});

test("cold start with unknown kid fetches JWKS once (no immediate second fetch)", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock, {}, {}, OTHER)), LOGIN);
  assert.equal(sb.calls.jwks, 1);
});

test("key rotation: forced refetch picks up a newly published kid", async () => {
  const NEW = await makeEcKey("kid-new");
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  sb.state.jwks = () => ({ status: 200, body: { keys: [KEY.jwk, NEW.jwk] } });
  clock.t += 1_000;
  assert.deepEqual(await run(await tok(clock, {}, {}, NEW)), { ok: true });
  assert.equal(sb.calls.jwks, 2);
});

test("JWKS refresh after 10 min drops a removed kid", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  const NEW = await makeEcKey("kid-new");
  sb.state.jwks = () => ({ status: 200, body: { keys: [NEW.jwk] } });
  clock.t += JWKS_TTL_MS;
  assert.deepEqual(await run(await tok(clock)), LOGIN);
  assert.equal(sb.calls.jwks, 2);
});

test("JWKS key filtering: wrong kty/crv/alg/use ignored", async () => {
  const k = await makeEcKey("kid-bad");
  for (const bad of [
    { ...k.jwk, use: "enc" },
    { ...k.jwk, alg: "ES384" },
    { ...k.jwk, crv: "P-384" },
    { ...k.jwk, kty: "RSA" },
  ]) {
    const { sb, clock, run } = setup();
    sb.state.jwks = () => ({ status: 200, body: { keys: [KEY.jwk, bad] } });
    assert.deepEqual(await run(await tok(clock, {}, {}, k)), LOGIN, JSON.stringify(bad));
  }
  // alg / use 缺省 = 接受
  const { sb, clock, run } = setup();
  const { alg, use, ...bare } = k.jwk;
  sb.state.jwks = () => ({ status: 200, body: { keys: [bare] } });
  assert.deepEqual(await run(await tok(clock, {}, {}, k)), { ok: true });
});

test("tampering: payload char, re-encoded payload, signature byte, 63/65-byte sig → 401", async () => {
  const { sb, clock, run } = setup();
  const t = await tok(clock);
  const [h, p, s] = t.split(".");
  const mid = Math.floor(p.length / 2);
  const flipped = p.slice(0, mid) + (p[mid] === "A" ? "B" : "A") + p.slice(mid + 1);
  assert.deepEqual(await run(`${h}.${flipped}.${s}`), LOGIN);
  const forged = b64uJson({ ...claims(clock.t), sub: "00000000-0000-4000-8000-000000000000" });
  assert.deepEqual(await run(`${h}.${forged}.${s}`), LOGIN);
  const sig = Buffer.from(s, "base64url");
  const bad = Buffer.from(sig);
  bad[10] ^= 0x01;
  assert.deepEqual(await run(`${h}.${p}.${b64u(bad)}`), LOGIN);
  assert.deepEqual(await run(`${h}.${p}.${b64u(sig.subarray(0, 63))}`), LOGIN);
  assert.deepEqual(await run(`${h}.${p}.${b64u(Buffer.concat([sig, Buffer.from([0])]))}`), LOGIN);
  assert.equal(sb.calls.rest, 0);
  assert.deepEqual(await run(t), { ok: true }); // 原 token 仍有效
});

test("malformed tokens: 2 or 4 segments, bad base64url, oversize (>8KB) → 401", async () => {
  const { sb, clock, run } = setup();
  const t = await tok(clock);
  const [h, p, s] = t.split(".");
  assert.deepEqual(await run(`${h}.${p}`), LOGIN);
  assert.deepEqual(await run(`${t}.${s}`), LOGIN);
  assert.deepEqual(await run(`${h}.${p}+.${s}`), LOGIN);
  assert.deepEqual(await run(`${h}.${b64u(Buffer.from("not json"))}.${s}`), LOGIN);
  const big = await tok(clock, { pad: "x".repeat(8 * 1024) });
  assert.ok(big.length > 8 * 1024);
  assert.deepEqual(await run(big), LOGIN);
  assert.equal(sb.calls.jwks, 0);
});

test("claims: wrong iss, aud anon, role anon/service_role, non-UUID sub → 401", async () => {
  const { sb, clock, run } = setup();
  const cases = [
    { iss: `${ISS}/` },
    { iss: "https://other.supabase.co/auth/v1" },
    { iss: undefined },
    { aud: "anon" },
    { aud: ["anon"] },
    { aud: undefined },
    { role: "anon" },
    { role: "service_role" },
    { role: undefined },
    { sub: "not-a-uuid" },
    { sub: `${SUB}x` },
    { sub: undefined },
  ];
  for (const over of cases) {
    assert.deepEqual(await run(await tok(clock, over)), LOGIN, JSON.stringify(over));
  }
  assert.equal(sb.calls.rest, 0);
  assert.deepEqual(await run(await tok(clock, { aud: ["x", "authenticated"] })), { ok: true });
});

test("is_anonymous: true → 403 without REST; unsigned anonymous token → 401", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock, { is_anonymous: true })), DENIED);
  assert.equal(sb.calls.rest, 0);
  const t = await tok(clock, { is_anonymous: true });
  const [h, p] = t.split(".");
  assert.deepEqual(await run(`${h}.${p}.${b64u(new Uint8Array(64))}`), LOGIN);
  assert.deepEqual(await run(await tok(clock, { is_anonymous: false })), { ok: true });
});

test("status pending / rejected / no row / non-array → 403", async () => {
  for (const body of [[{ status: "pending" }], [{ status: "rejected" }], [], {}]) {
    const { sb, clock, run } = setup();
    sb.state.profile = () => ({ status: 200, body });
    assert.deepEqual(await run(await tok(clock)), DENIED, JSON.stringify(body));
  }
});

test("REST 500 → 401, negative-cached 45s, re-queried after", async () => {
  const { sb, clock, run } = setup();
  sb.state.profile = () => ({ status: 500, body: { message: "boom" } });
  const t = await tok(clock);
  assert.deepEqual(await run(t), LOGIN);
  assert.equal(sb.calls.rest, 1);
  sb.state.profile = () => ({ status: 200, body: [{ status: "approved" }] });
  clock.t += PROFILE_FAIL_TTL_MS - 1;
  assert.deepEqual(await run(t), LOGIN);
  assert.equal(sb.calls.rest, 1);
  clock.t += 1;
  assert.deepEqual(await run(t), { ok: true });
  assert.equal(sb.calls.rest, 2);
});

test("REST fetch throws → 503 auth lookup failed, not cached", async () => {
  const { sb, clock, run } = setup();
  sb.state.profile = () => new Error("network down");
  const t = await tok(clock);
  assert.deepEqual(await run(t), FAILED);
  sb.state.profile = () => ({ status: 200, body: [{ status: "approved" }] });
  assert.deepEqual(await run(t), { ok: true });
  assert.equal(sb.calls.rest, 2);
});

test("20 concurrent same-token requests → JWKS 1, REST 1, all ok", async () => {
  const { sb, clock, run, auth } = setup();
  sb.state.delayMs = 20;
  const t = await tok(clock);
  const results = await Promise.all(Array.from({ length: 20 }, () => run(t)));
  for (const r of results) assert.deepEqual(r, { ok: true });
  assert.equal(sb.calls.jwks, 1);
  assert.equal(sb.calls.rest, 1);
  assert.equal(auth._debug.profileInflightSize(), 0);
});

test("revocation: approved → rejected takes effect after PROFILE_TTL (5 min)", async () => {
  const { sb, clock, run } = setup();
  const t = await tok(clock);
  assert.deepEqual(await run(t), { ok: true });
  sb.state.profile = () => ({ status: 200, body: [{ status: "rejected" }] });
  clock.t += PROFILE_TTL_MS - 1;
  assert.deepEqual(await run(t), { ok: true });
  assert.equal(sb.calls.rest, 1);
  clock.t += 1;
  assert.deepEqual(await run(t), DENIED);
  assert.equal(sb.calls.rest, 2);
});

test("status cache is keyed by sub: a different user is queried separately", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  sb.state.profile = () => ({ status: 200, body: [] });
  const other = "0a0b0c0d-0e0f-4a1b-8c2d-3e4f5a6b7c8d";
  assert.deepEqual(await run(await tok(clock, { sub: other })), DENIED);
  assert.equal(sb.calls.rest, 2);
  assert.ok(sb.calls.restReqs[1].url.endsWith(`user_id=eq.${other}`));
});

test("no / non-Bearer Authorization → 401 without network; missing config → 503", async () => {
  const { sb, run, auth, clock } = setup();
  assert.deepEqual(await run(undefined), LOGIN);
  assert.deepEqual(await run(undefined, { Authorization: "Basic abc" }), LOGIN);
  assert.deepEqual(await run(""), LOGIN);
  assert.equal(sb.calls.jwks + sb.calls.rest, 0);
  const req = new Request("https://radar.example/data/x.json", {
    headers: { Authorization: `Bearer ${await tok(clock)}` },
  });
  assert.deepEqual(await auth.authorize(req, { SUPABASE_URL: ENV.SUPABASE_URL }), {
    ok: false,
    status: 503,
    message: "auth not configured",
  });
});

test("JWKS unavailable with no cached keys → 503 (fail closed)", async () => {
  for (const jwks of [
    () => new Error("down"),
    () => ({ status: 500, body: {} }),
    () => ({ status: 200, body: { keys: [] } }),
    () => ({ status: 200, body: { keys: [{ kty: "oct", k: "c2VjcmV0", kid: "kid-current" }] } }),
  ]) {
    const { sb, clock, run } = setup();
    sb.state.jwks = jwks;
    assert.deepEqual(await run(await tok(clock)), FAILED);
    assert.equal(sb.calls.rest, 0);
  }
});

test("JWKS refresh fails with cached keys → stale keys keep working, retry backs off", async () => {
  const { sb, clock, run } = setup();
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  sb.state.jwks = () => new Error("down");
  clock.t += JWKS_TTL_MS;
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  assert.equal(sb.calls.jwks, 2);
  clock.t += 30_000;
  assert.deepEqual(await run(await tok(clock)), { ok: true });
  assert.equal(sb.calls.jwks, 2); // 60 秒內不重試
});

test(`profile cache bounded: ${CACHE_MAX_ENTRIES + 1} distinct subs → size ≤ ${CACHE_MAX_ENTRIES}`, async () => {
  const { sb, clock, run, auth } = setup();
  sb.state.delayMs = 0;
  for (let i = 0; i <= CACHE_MAX_ENTRIES; i++) {
    const sub = `${String(i).padStart(8, "0")}-0000-4000-8000-000000000000`;
    assert.deepEqual(await run(await tok(clock, { sub })), { ok: true });
  }
  assert.equal(sb.calls.rest, CACHE_MAX_ENTRIES + 1);
  assert.ok(auth._debug.profileCacheSize() <= CACHE_MAX_ENTRIES);
  // 最舊的(i=0)已被淘汰 → 再查一次 REST;最新的仍在快取
  await run(await tok(clock, { sub: "00000000-0000-4000-8000-000000000000" }));
  assert.equal(sb.calls.rest, CACHE_MAX_ENTRIES + 2);
  await run(await tok(clock, { sub: `${String(CACHE_MAX_ENTRIES).padStart(8, "0")}-0000-4000-8000-000000000000` }));
  assert.equal(sb.calls.rest, CACHE_MAX_ENTRIES + 2);
});

test("source never logs (no console.* in src/)", () => {
  for (const f of ["../src/auth.js", "../src/index.js"]) {
    const src = readFileSync(new URL(f, import.meta.url), "utf8");
    assert.doesNotMatch(src, /console\./, f);
  }
});
