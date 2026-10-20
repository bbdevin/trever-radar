/**
 * 自選「特定分點」組合綁帳號 smoke(docs/52 §6),手機 390px。
 *
 * 用本機靜態伺服器提供 `next build` 的輸出;/data/branches/watch/* 回合成的 index/分片,
 * *.supabase.co 以 route interception 回應:假的已核准 session(app_profiles approved),
 * /rest/v1/watched_branch_sets 依情境:
 *   A. 表不存在(404 PGRST205)→ 只存本機、照常可改、重新整理後仍保留;每次載入只打一次 GET、從不 POST,
 *      我們的程式不寫任何 console 訊息。
 *   B. 表存在(記憶體假表)→ 登入後載入雲端那一列;改主分點／移除分點 → upsert(POST on_conflict=user_id,
 *      merge-duplicates,body 只有本人 user_id＋組合),重新整理後仍是雲端版本。
 *   C. 表存在、本機有較新的離線改動 → 載入時本機勝並上傳。
 * 不加任何 dev bypass,不碰真的 Supabase。
 *
 * 用法:node scripts/verify-watched-branch-sync.mjs --out out [--shots ../docs/evidence/52_watched_branches]
 * 環境變數:PLAYWRIGHT_MODULE(playwright 或 playwright-core 的路徑)、CHROMIUM_PATH。
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => (v.startsWith("--") ? [...acc, [v.slice(2), all[i + 1]]] : acc), []),
);
const OUT_DIR = path.resolve(args.out ?? "out");
const SHOTS_DIR = args.shots ? path.resolve(args.shots) : null;
const PORT = Number(args.port ?? 3472);
const BASE = `http://127.0.0.1:${PORT}`;
const SUPA = "https://eroycvbgfitvyulfbbnw.supabase.co";

const pwSpec = process.env.PLAYWRIGHT_MODULE ?? "playwright";
const pw = await import(fs.existsSync(pwSpec) ? pathToFileURL(path.join(pwSpec, "index.mjs")).href : pwSpec);
const chromium = pw.chromium ?? pw.default.chromium;
const executablePath =
  process.env.CHROMIUM_PATH ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-win64/chrome-headless-shell.exe");

// ---------- static server (Cloudflare Pages 風格:/x → x.html) ----------
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json" };
function resolveFile(urlPath) {
  const p = decodeURIComponent(urlPath.split("?")[0]);
  for (const c of p.endsWith("/") ? [path.join(p, "index.html")] : [p, `${p}.html`]) {
    const f = path.join(OUT_DIR, c);
    if (f.startsWith(OUT_DIR) && fs.existsSync(f) && fs.statSync(f).isFile()) return f;
  }
  return null;
}
const server = http.createServer((req, res) => {
  const f = resolveFile(req.url ?? "/");
  if (!f) {
    res.writeHead(404, { "content-type": TYPES[".html"] });
    res.end(fs.readFileSync(path.join(OUT_DIR, "404.html")));
    return;
  }
  res.writeHead(200, { "content-type": TYPES[path.extname(f)] ?? "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

// ---------- fake auth ----------
const USER_ID = "00000000-0000-4000-8000-0000000000aa";
const EMAIL = "sync@example.test";
const b64url = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const exp = Math.floor(new Date("2030-01-01T00:00:00Z").getTime() / 1000);
const user = { id: USER_ID, aud: "authenticated", role: "authenticated", email: EMAIL, app_metadata: { provider: "google" }, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" };
const fakeSession = {
  access_token: `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url({ sub: USER_ID, email: EMAIL, role: "authenticated", aud: "authenticated", exp })}.sig`,
  token_type: "bearer",
  expires_in: 3600,
  expires_at: exp,
  refresh_token: "sync-refresh",
  user,
};
const profileRow = { user_id: USER_ID, email: EMAIL, display_name: null, avatar_url: null, role: "user", status: "approved" };

// ---------- synthetic watch export ----------
const A = "富邦-新店", B = "永豐金-內湖", C = "元大-松江", D = "凱基-台北";
const watchIndex = {
  version: 1, as_of: "2026-10-19", window_days: 60, window_from: "2026-07-21", shards: 64, hold_min: 100, hold_floor: 20, hold_top: 60,
  coverage: null, warrant: null,
  branches: [[A, 0, 1, 0, 0, 0], [B, 0, 1, 0, 0, 0], [C, 0, 0, 1, 0, 0], [D, 0, 1, 0, 0, 0]],
};
const shard0 = {
  version: 1, as_of: "2026-10-19", window_days: 60, window_from: "2026-07-21", shard: 0,
  branches: {
    [A]: [["2330", 120, 20, 100, 300, "2026-10-02", 3, 100, "2026-10-19", 1000.5]],
    [B]: [["2330", 80, 0, 80, 150, "2026-10-10", 2, 80, "2026-10-19", 1010]],
    [C]: [["2330", 0, 60, -60, 0, null, 1, -60, "2026-10-19", null]],
    [D]: [["2330", 50, 0, 50, 50, "2026-10-19", 1, 50, "2026-10-19", 1020]],
  },
  stocks: { "2330": ["台積電", 1025, 0.5, 30000, 1] },
};

/** mode: "missing" | "present";cloud = 假表那一列(present 時) */
async function newContext(browser, { mode, cloudRow = null, localValue = null }) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: "block", locale: "zh-TW", timezoneId: "Asia/Taipei", colorScheme: "dark" });
  const state = { mode, row: cloudRow, gets: [], posts: [], other: [] };
  await context.addInitScript(([k, v, lk, lv]) => {
    try {
      if (!localStorage.getItem(k)) localStorage.setItem(k, v);
      if (lv && !sessionStorage.getItem("__seeded")) { localStorage.setItem(lk, lv); sessionStorage.setItem("__seeded", "1"); }
    } catch {}
  }, ["sb-eroycvbgfitvyulfbbnw-auth-token", JSON.stringify(fakeSession), "watched_branch_set_v1", localValue]);
  await context.route(`${BASE}/data/**`, async (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (b) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    if (p === "/data/branches/watch/index.json") return json(watchIndex);
    if (p === "/data/branches/watch/s00.json") return json(shard0);
    return route.fulfill({ status: 404, body: "" });
  });
  await context.route(`${SUPA}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.startsWith("/auth/v1/user")) return json(user);
    if (url.pathname.startsWith("/auth/v1/token")) return json(fakeSession);
    if (url.pathname.startsWith("/auth/v1/")) return json({});
    if (url.pathname === "/rest/v1/app_profiles") {
      const single = (req.headers()["accept"] ?? "").includes("vnd.pgrst.object");
      return json(single ? profileRow : [profileRow]);
    }
    if (url.pathname === "/rest/v1/watched_branch_sets") {
      const entry = { method: req.method(), search: url.search, params: Object.fromEntries(url.searchParams), headers: req.headers(), body: req.postData() };
      if (req.method() === "GET") state.gets.push(entry);
      else state.posts.push(entry);
      if (state.mode === "missing") {
        return json({ code: "PGRST205", details: null, hint: null, message: "Could not find the table 'public.watched_branch_sets' in the schema cache" }, 404);
      }
      if (req.method() === "GET") {
        const single = (req.headers()["accept"] ?? "").includes("vnd.pgrst.object");
        // maybeSingle 送 object accept;沒列時 PostgREST 回 406 PGRST116,supabase-js 轉成 data=null
        if (single && !state.row) return json({ code: "PGRST116", details: "The result contains 0 rows", hint: null, message: "JSON object requested, multiple (or no) rows returned" }, 406);
        return json(single ? state.row : state.row ? [state.row] : []);
      }
      if (req.method() === "POST") {
        const body = JSON.parse(req.postData() ?? "{}");
        state.row = { branches: body.branches, anchor: body.anchor, updated_at: body.updated_at };
        return route.fulfill({ status: 201, body: "" });
      }
      return json({ message: "unexpected" }, 405);
    }
    state.other.push(`${req.method()} ${url.pathname}`);
    if (req.method() === "GET" || req.method() === "HEAD") return json([]);
    return json([], 201);
  });
  return { context, state };
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(400);
}
async function chips(page) {
  const sec = page.locator('section[aria-label="我的特定分點"]');
  await sec.waitFor({ state: "visible" });
  const names = await sec.locator("li button[aria-pressed]").evaluateAll((els) =>
    els.map((e) => ({ name: e.querySelector("span")?.textContent ?? "", anchor: e.getAttribute("aria-pressed") === "true" })));
  return { branches: names.map((n) => n.name), anchor: names.find((n) => n.anchor)?.name ?? null };
}
const readLocal = (page) => page.evaluate(() => { try { return JSON.parse(localStorage.getItem("watched_branch_set_v1") ?? "null"); } catch { return null; } });
async function shot(page, name) {
  if (!SHOTS_DIR) return;
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS_DIR, `${name}.png`), fullPage: false });
}
async function noHorizontalOverflow(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

const results = [];
const check = (name, ok, detail) => {
  results.push({ name, ok, ...(ok ? {} : { detail }) });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : `  ${JSON.stringify(detail)}`}`);
};

const browser = await chromium.launch({ headless: true, executablePath });
try {
  // ---------- A. 表不存在 ----------
  {
    const { context, state } = await newContext(browser, { mode: "missing" });
    const page = await context.newPage();
    const consoleMsgs = [];
    page.on("console", (m) => consoleMsgs.push({ type: m.type(), text: m.text() }));
    await page.goto(`${BASE}/watchlist?tab=branches`, { waitUntil: "load" });
    await settle(page);
    let c = await chips(page);
    check("A: default set shown when table missing", JSON.stringify(c) === JSON.stringify({ branches: [A, B, C], anchor: A }), c);
    await page.getByRole("button", { name: `移除 ${C}` }).click();
    await page.locator('section[aria-label="我的特定分點"] li button[aria-pressed]', { hasText: B }).click();
    await settle(page);
    c = await chips(page);
    check("A: local edit applied", JSON.stringify(c) === JSON.stringify({ branches: [A, B], anchor: B }), c);
    await shot(page, "watchlist-390-dark-sync-table-missing");
    check("A: no horizontal overflow", await noHorizontalOverflow(page), null);
    const local = await readLocal(page);
    check("A: saved locally, marked dirty (uploads once table exists)", local?.dirty === true && local?.anchor === B && local?.uid === USER_ID, local);
    await page.reload({ waitUntil: "load" });
    await settle(page);
    c = await chips(page);
    check("A: survives reload", JSON.stringify(c) === JSON.stringify({ branches: [A, B], anchor: B }), c);
    check("A: one GET per page load, never POST", state.gets.length === 2 && state.posts.length === 0, { gets: state.gets.length, posts: state.posts.length });
    const ours = consoleMsgs.filter((m) => /watched_branch|branch_sets/i.test(m.text) && !/Failed to load resource/i.test(m.text));
    const net404 = consoleMsgs.filter((m) => /Failed to load resource/i.test(m.text));
    check("A: no console messages from our code", ours.length === 0, ours);
    check("A: at most one browser 404 line per load", net404.length <= 2, net404);
    await context.close();
  }

  // ---------- B. 表存在,雲端有一列 ----------
  {
    const cloudRow = { branches: [B, D], anchor: D, updated_at: "2026-10-20T01:00:00+00:00" };
    const { context, state } = await newContext(browser, { mode: "present", cloudRow });
    const page = await context.newPage();
    const consoleMsgs = [];
    page.on("console", (m) => {
      if ((m.type() === "warning" || m.type() === "error") && !/Service Worker registration blocked by Playwright/.test(m.text())) consoleMsgs.push(m.text());
    });
    await page.goto(`${BASE}/watchlist?tab=branches`, { waitUntil: "load" });
    await settle(page);
    let c = await chips(page);
    check("B: cloud set loaded on login", JSON.stringify(c) === JSON.stringify({ branches: [B, D], anchor: D }), c);
    const g = state.gets[0];
    check("B: GET filters own row and selects only needed columns",
      g && g.params.user_id === `eq.${USER_ID}` && g.params.select === "branches,anchor,updated_at" && (g.headers.authorization ?? "").startsWith("Bearer "),
      g && { params: g.params, auth: Boolean(g.headers.authorization) });
    check("B: GET uses publishable key only", g && /^sb_publishable_/.test(g.headers.apikey ?? ""), g && g.headers.apikey);
    check("B: no POST just from loading", state.posts.length === 0, state.posts.length);
    await shot(page, "watchlist-390-dark-sync-cloud-loaded");

    await page.locator('section[aria-label="我的特定分點"] li button[aria-pressed]', { hasText: B }).click();
    await settle(page);
    const p = state.posts.at(-1);
    const body = p ? JSON.parse(p.body) : null;
    check("B: edit upserts (POST on_conflict=user_id, merge-duplicates)",
      p && p.params.on_conflict === "user_id" && /resolution=merge-duplicates/.test(p.headers.prefer ?? ""), p && { params: p.params, prefer: p.headers.prefer });
    check("B: upsert body is exactly own user_id + set + updated_at",
      body && JSON.stringify(Object.keys(body).sort()) === JSON.stringify(["anchor", "branches", "updated_at", "user_id"]) &&
        body.user_id === USER_ID && JSON.stringify(body.branches) === JSON.stringify([B, D]) && body.anchor === B && !Number.isNaN(Date.parse(body.updated_at)),
      body);
    check("B: upsert uses publishable key only", p && /^sb_publishable_/.test(p.headers.apikey ?? ""), p && p.headers.apikey);

    await page.getByRole("button", { name: `移除 ${D}` }).click();
    await settle(page);
    const body2 = JSON.parse(state.posts.at(-1)?.body ?? "{}");
    check("B: second edit upserts latest set", JSON.stringify(body2.branches) === JSON.stringify([B]) && body2.anchor === B, body2);
    const local = await readLocal(page);
    check("B: local copy clean after successful upsert", local?.dirty === false && local?.uid === USER_ID, local);
    await shot(page, "watchlist-390-dark-sync-after-edit");
    check("B: no horizontal overflow", await noHorizontalOverflow(page), null);

    // 別台裝置:清掉本機,只靠雲端
    await page.evaluate(() => localStorage.removeItem("watched_branch_set_v1"));
    await page.reload({ waitUntil: "load" });
    await settle(page);
    c = await chips(page);
    check("B: another device (empty local) gets the cloud set", JSON.stringify(c) === JSON.stringify({ branches: [B], anchor: B }), c);
    check("B: no warnings/errors in console", consoleMsgs.length === 0, consoleMsgs);
    await context.close();
  }

  // ---------- C. 本機有較新的離線改動 ----------
  {
    const cloudRow = { branches: [C], anchor: C, updated_at: "2026-10-01T00:00:00+00:00" };
    const offline = JSON.stringify({ branches: [A, D], anchor: D, edited_at: Date.parse("2026-10-20T00:00:00Z"), dirty: true, uid: USER_ID });
    const { context, state } = await newContext(browser, { mode: "present", cloudRow, localValue: offline });
    const page = await context.newPage();
    await page.goto(`${BASE}/watchlist?tab=branches`, { waitUntil: "load" });
    await settle(page);
    const c = await chips(page);
    check("C: newer offline local edit kept", JSON.stringify(c) === JSON.stringify({ branches: [A, D], anchor: D }), c);
    const body = JSON.parse(state.posts.at(-1)?.body ?? "{}");
    check("C: offline edit uploaded on load", JSON.stringify(body.branches) === JSON.stringify([A, D]) && body.anchor === D && body.user_id === USER_ID && body.updated_at === "2026-10-20T00:00:00.000Z", body);
    await context.close();
  }
} catch (e) {
  check("script error", false, String(e?.stack ?? e));
} finally {
  await browser.close();
  server.close();
}
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exitCode = failed.length ? 1 : 0;
