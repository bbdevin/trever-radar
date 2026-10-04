// node --test test/worker.test.mjs — src/index.js 整體行為(路由/標頭/service key/JWT 路徑)
// 每個測試以 ?i=N 重新載入 index.js,取得全新的 isolate 狀態;stub globalThis.fetch 與 Date.now。
import { test } from "node:test";
import assert from "node:assert/strict";

import { ENV, T0, claims, fakeSupabase, makeEcKey, signEs256 } from "./_fixtures.mjs";

const KEY = await makeEcKey("kid-current");
const SERVICE_KEY = "a3f9c0d2e1b4a5968778695a4b3c2d1e0f9e8d7c6b5a49382716051423324150";

let loadSeq = 0;
async function setup(t) {
  const sb = fakeSupabase([KEY]);
  const clock = { t: T0 };
  const realFetch = globalThis.fetch;
  const realNow = Date.now;
  globalThis.fetch = sb.fetch;
  Date.now = () => clock.t;
  t.after(() => {
    globalThis.fetch = realFetch;
    Date.now = realNow;
  });
  const worker = (await import(`../src/index.js?i=${++loadSeq}`)).default;
  const assetCalls = [];
  const env = {
    ...ENV,
    RADAR_SERVICE_KEY: SERVICE_KEY,
    ASSETS: {
      fetch: async (req) => {
        assetCalls.push(req);
        if (new URL(req.url).pathname === "/missing.json") {
          return new Response("nope", { status: 404 });
        }
        return new Response('{"ok":1}', {
          status: 200,
          headers: { "content-type": "application/json", "cache-control": "public, max-age=31536000" },
        });
      },
    },
  };
  const waited = [];
  const ctx = { waitUntil: (p) => waited.push(p) };
  const call = (path, { method = "GET", headers = {} } = {}) =>
    worker.fetch(new Request(`https://radar.example${path}`, { method, headers }), env, ctx);
  const token = (over = {}) => signEs256(KEY, claims(clock.t, over));
  return { sb, clock, env, assetCalls, call, token, waited };
}

async function assertJsonError(res, status, message) {
  assert.equal(res.status, status);
  assert.equal(res.headers.get("cache-control"), "no-store");
  assert.equal(res.headers.get("content-type"), "application/json; charset=utf-8");
  assert.deepEqual(await res.json(), { error: message });
}

test("valid + approved JWT → 200, ASSETS.fetch once, private max-age=60, vary unchanged", async (t) => {
  const { call, token, assetCalls, sb } = await setup(t);
  const res = await call("/data/stocks/2330.json", {
    headers: { Authorization: `Bearer ${await token()}` },
  });
  assert.equal(res.status, 200);
  assert.equal(await res.text(), '{"ok":1}');
  assert.equal(assetCalls.length, 1);
  assert.equal(new URL(assetCalls[0].url).pathname, "/stocks/2330.json");
  assert.equal(res.headers.get("cache-control"), "private, max-age=60");
  assert.equal(res.headers.get("vary"), "Authorization, X-Radar-Service-Key");
  assert.equal(sb.calls.jwks, 1);
  assert.equal(sb.calls.rest, 1);
  assert.deepEqual(sb.calls.other, []);
});

test("radar.json / meta.json → private, no-store", async (t) => {
  const { call, token } = await setup(t);
  const auth = { Authorization: `Bearer ${await token()}` };
  for (const p of ["/data/radar.json", "/data/meta.json", "/data-preview/radar.json"]) {
    const res = await call(p, { headers: auth });
    assert.equal(res.status, 200, p);
    assert.equal(res.headers.get("cache-control"), "private, no-store", p);
  }
});

test("no Authorization → 401 JSON, no assets, no network", async (t) => {
  const { call, assetCalls, sb } = await setup(t);
  await assertJsonError(await call("/data/radar.json"), 401, "login required");
  await assertJsonError(await call("/data-preview/radar.json"), 401, "login required");
  assert.equal(assetCalls.length, 0);
  assert.equal(sb.calls.jwks + sb.calls.rest + sb.calls.other.length, 0);
});

test("correct service key → 200 with zero fetches (precedence over a bad bearer)", async (t) => {
  const { call, assetCalls, sb } = await setup(t);
  const res = await call("/data/radar.json", {
    headers: { "X-Radar-Service-Key": SERVICE_KEY, Authorization: "Bearer garbage" },
  });
  assert.equal(res.status, 200);
  assert.equal(assetCalls.length, 1);
  assert.equal(sb.calls.jwks + sb.calls.rest + sb.calls.other.length, 0);
});

test("service key wrong by one char → falls through to JWT path → 401 (or 200 with valid JWT)", async (t) => {
  const { call, token, sb } = await setup(t);
  const wrong = SERVICE_KEY.slice(0, -1) + (SERVICE_KEY.endsWith("0") ? "1" : "0");
  await assertJsonError(
    await call("/data/radar.json", { headers: { "X-Radar-Service-Key": wrong } }),
    401,
    "login required",
  );
  assert.equal(sb.calls.jwks + sb.calls.rest, 0);
  const res = await call("/data/radar.json", {
    headers: { "X-Radar-Service-Key": wrong, Authorization: `Bearer ${await token()}` },
  });
  assert.equal(res.status, 200);
});

test("JWT failures map to the same JSON shapes", async (t) => {
  const { call, token, sb, clock } = await setup(t);
  await assertJsonError(
    await call("/data/x.json", { headers: { Authorization: `Bearer ${await token({ exp: clock.t / 1000 - 1 })}` } }),
    401,
    "login required",
  );
  await assertJsonError(
    await call("/data/x.json", { headers: { Authorization: `Bearer ${await token({ is_anonymous: true })}` } }),
    403,
    "not approved",
  );
  sb.state.profile = () => ({ status: 200, body: [{ status: "pending" }] });
  await assertJsonError(
    await call("/data/x.json", { headers: { Authorization: `Bearer ${await token()}` } }),
    403,
    "not approved",
  );
});

test("JWKS failure: no cache → 503; with cache → 200", async (t) => {
  const { call, token, sb, clock } = await setup(t);
  sb.state.jwks = () => new Error("down");
  const auth = { Authorization: `Bearer ${await token()}` };
  await assertJsonError(await call("/data/x.json", { headers: auth }), 503, "auth lookup failed");
  sb.state.jwks = () => ({ status: 200, body: { keys: [KEY.jwk] } });
  // 無金鑰時失敗後退避 10 秒:退避期內仍 503,過後恢復
  await assertJsonError(await call("/data/x.json", { headers: auth }), 503, "auth lookup failed");
  assert.equal(sb.calls.jwks, 1);
  clock.t += 10_000;
  assert.equal((await call("/data/x.json", { headers: auth })).status, 200);
  sb.state.jwks = () => new Error("down again");
  clock.t += 11 * 60 * 1000;
  const res = await call("/data/x.json", { headers: { Authorization: `Bearer ${await token()}` } });
  assert.equal(res.status, 200);
});

test("REST fetch throws → 503 auth lookup failed", async (t) => {
  const { call, token, sb } = await setup(t);
  sb.state.profile = () => new Error("down");
  await assertJsonError(
    await call("/data/x.json", { headers: { Authorization: `Bearer ${await token()}` } }),
    503,
    "auth lookup failed",
  );
});

test("concurrent page load: 20 requests → JWKS 1, REST 1, shared fetches handed to waitUntil", async (t) => {
  const { call, token, sb, waited } = await setup(t);
  sb.state.delayMs = 20;
  const auth = { Authorization: `Bearer ${await token()}` };
  const res = await Promise.all(Array.from({ length: 20 }, (_, i) => call(`/data/s/${i}.json`, { headers: auth })));
  for (const r of res) assert.equal(r.status, 200);
  assert.equal(sb.calls.jwks, 1);
  assert.equal(sb.calls.rest, 1);
  assert.equal(waited.length, 2);
});

test("regression: 405 / 404 / 400 / HEAD / asset 404", async (t) => {
  const { call, token, assetCalls } = await setup(t);
  const auth = { Authorization: `Bearer ${await token()}` };
  for (const method of ["POST", "PUT", "DELETE", "OPTIONS"]) {
    const res = await call("/data/radar.json", { method, headers: auth });
    assert.equal(res.status, 405, method);
    assert.equal(await res.text(), "method not allowed");
  }
  for (const p of ["/x", "/data", "/data/", "/datax/a.json", "/"]) {
    const res = await call(p, { headers: auth });
    assert.equal(res.status, 404, p);
    assert.equal(await res.text(), "not found");
  }
  // WHATWG URL 會先把 /data/../a 正規化成 /a(→ 404,一樣不會讀到資產);
  // 進得了路由的 `..` / `//` 由 400 擋下(未驗身分前就擋)
  assert.equal((await call("/data/../a")).status, 404);
  for (const p of ["/data/..%2fa.json", "/data/a..b.json", "/data/a//b.json", "/data-preview/x/..%2f..%2fy"]) {
    const res = await call(p);
    assert.equal(res.status, 400, p);
    assert.equal(await res.text(), "bad request");
  }
  assert.equal(assetCalls.length, 0);
  const head = await call("/data/stocks/1.json", { method: "HEAD", headers: auth });
  assert.equal(head.status, 200);
  const missing = await call("/data/missing.json", { headers: auth });
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), "not found");
});
