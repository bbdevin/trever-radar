// 測試共用:自簽 ES256 token、假 Supabase fetch、假時鐘。只用 Node 內建(≥18)。
import { webcrypto } from "node:crypto";

export const subtle = (globalThis.crypto && globalThis.crypto.subtle) || webcrypto.subtle;

export const SUPABASE_URL = "https://example-project.supabase.co";
export const ENV = Object.freeze({
  SUPABASE_URL,
  SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test_key",
});
export const ISS = `${SUPABASE_URL}/auth/v1`;
export const JWKS = `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`;
export const SUB = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b";
export const T0 = 1_800_000_000_000; // 假時鐘起點(ms)

const enc = new TextEncoder();
export const b64u = (bytes) => Buffer.from(bytes).toString("base64url");
export const b64uJson = (obj) => b64u(Buffer.from(JSON.stringify(obj)));

export async function makeEcKey(kid) {
  const kp = await subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, [
    "sign",
    "verify",
  ]);
  const pub = await subtle.exportKey("jwk", kp.publicKey);
  return {
    kid,
    privateKey: kp.privateKey,
    jwk: { kty: "EC", crv: "P-256", x: pub.x, y: pub.y, kid, alg: "ES256", use: "sig" },
  };
}

export function claims(nowMs, over = {}) {
  return {
    iss: ISS,
    aud: "authenticated",
    role: "authenticated",
    sub: SUB,
    exp: Math.floor(nowMs / 1000) + 3600,
    iat: Math.floor(nowMs / 1000),
    ...over,
  };
}

export async function signEs256(key, payload, headerOver = {}) {
  const header = { alg: "ES256", kid: key.kid, typ: "JWT", ...headerOver };
  const h = b64uJson(header);
  const p = b64uJson(payload);
  const sig = await subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    key.privateKey,
    enc.encode(`${h}.${p}`),
  );
  return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
}

export async function signHs256(secretBytes, header, payload) {
  const h = b64uJson(header);
  const p = b64uJson(payload);
  const k = await subtle.importKey("raw", secretBytes, { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
  ]);
  const sig = await subtle.sign("HMAC", k, enc.encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
}

export async function signRs256(header, payload) {
  const kp = await subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const h = b64uJson(header);
  const p = b64uJson(payload);
  const sig = await subtle.sign("RSASSA-PKCS1-v1_5", kp.privateKey, enc.encode(`${h}.${p}`));
  return `${h}.${p}.${b64u(new Uint8Array(sig))}`;
}

/**
 * 假 Supabase:JWKS 與 app_profiles REST。其他 URL(含 /auth/v1/user)一律記錄並丟例外。
 * state.jwks / state.profile 可在測試中替換;回傳 Error 物件 = fetch 丟例外。
 */
export function fakeSupabase(keys) {
  const calls = { jwks: 0, rest: 0, other: [], jwksInit: [], restReqs: [] };
  const state = {
    jwks: () => ({ status: 200, body: { keys: keys.map((k) => k.jwk) } }),
    profile: () => ({ status: 200, body: [{ status: "approved" }] }),
    delayMs: 2,
  };
  const fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (state.delayMs) await new Promise((r) => setTimeout(r, state.delayMs));
    if (url === JWKS) {
      calls.jwks++;
      calls.jwksInit.push(init);
      if (state.rawJwks !== undefined) return new Response(state.rawJwks, { status: 200 });
      const r = state.jwks();
      if (r instanceof Error) throw r;
      return new Response(JSON.stringify(r.body), { status: r.status });
    }
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/app_profiles?`)) {
      calls.rest++;
      calls.restReqs.push({ url, init });
      const r = state.profile();
      if (r instanceof Error) throw r;
      return new Response(JSON.stringify(r.body), { status: r.status });
    }
    calls.other.push(url);
    throw new Error(`unexpected fetch ${url}`);
  };
  return { fetch, calls, state };
}
