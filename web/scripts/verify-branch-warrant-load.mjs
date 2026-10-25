/**
 * /branch「權證分點異動」載入狀態 smoke(docs/51 §3.5),手機 390px。
 *
 * 2026-10-25 使用者回報「權證分點近 1、2 日都沒有資訊」:舊頁面一進站就抓 21.6 MB 的
 * branches/warrant_branches.json(cache: no-store),抓完之前與抓失敗時都顯示
 * 「此區間內無淨買賣超 500 萬以上之權證大戶」。本腳本用**正式機那份真檔**重現並驗證修正:
 *   A. 不限速:第一張卡出現的時間、下載量。
 *   B. 限速(預設 Fast 3G 1.6 Mbps / 150 ms):第 2 秒畫面上是「載入中」還是「無資料」;資料到後切 近 2 日。
 *   C. 抓檔失敗(500):要顯示錯誤＋重試,不是「無資料」;重試成功後出卡。
 *   D. 真的沒有資料(1d 空陣列):才顯示「此區間內無…」。
 *   E. 點一列展開逐檔權證明細(新版明細改抓 warrant-stock-details/{id}.breakdown.json)。
 *
 * 靜態伺服器:out/ 走 Cloudflare Pages 風格(/x → x.html);/data/* 讀 --data 目錄,
 * 支援 gzip(與正式 Workers 資產一樣壓縮傳輸,限速才量得準)。*.supabase.co 以 route
 * interception 回假的已核准 session,不碰真的 Supabase、不加 dev bypass。
 *
 * 用法:node scripts/verify-branch-warrant-load.mjs --out out --data <dir 內含 branches/…>
 *        [--shots ../docs/evidence/51_warrant_positions] [--prefix branch-390] [--expect-fix 1]
 * --expect-fix 0 = 只觀察(修正前的建置),不判 PASS/FAIL。
 * 環境變數:PLAYWRIGHT_MODULE(playwright 或 playwright-core 的路徑)、CHROMIUM_PATH。
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { pathToFileURL } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => (v.startsWith("--") ? [...acc, [v.slice(2), all[i + 1]]] : acc), []),
);
const OUT_DIR = path.resolve(args.out ?? "out");
const DATA_DIR = path.resolve(args.data ?? "data");
const SHOTS_DIR = args.shots ? path.resolve(args.shots) : null;
const PREFIX = args.prefix ?? "branch-390";
const EXPECT_FIX = (args["expect-fix"] ?? "1") !== "0";
const PORT = Number(args.port ?? 3473);
const BASE = `http://127.0.0.1:${PORT}`;
const SUPA = "https://eroycvbgfitvyulfbbnw.supabase.co";
const EMPTY_COPY = "此區間內無淨買賣超 500 萬以上之權證大戶";

const pwSpec = process.env.PLAYWRIGHT_MODULE ?? "playwright";
const pw = await import(fs.existsSync(pwSpec) ? pathToFileURL(path.join(pwSpec, "index.mjs")).href : pwSpec);
const chromium = pw.chromium ?? pw.default.chromium;
const executablePath =
  process.env.CHROMIUM_PATH ??
  path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-win64/chrome-headless-shell.exe");

// ---------- 合成的其他 /data 檔(只為讓分點頁走到權證分頁) ----------
const FIXTURES = {
  "/data/radar.json": { concentration: [] },
  "/data/branches/rankings.json": { rankings: [], daytrade: [] },
  "/data/branches/today.json": { version: 1, as_of: "2026-10-22", movements: {} },
  "/data/branches/track/index.json": [],
};

// ---------- 伺服器 ----------
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css", ".json": "application/json", ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".webmanifest": "application/manifest+json" };
/** 測試情境改這裡:fail = 這些 /data 路徑回 500;override = 路徑 → 改回的 body。 */
const ctl = { fail: null, notFound: null, override: new Map(), hits: [] };
const gzCache = new Map();
function resolveFile(root, urlPath) {
  const p = decodeURIComponent(urlPath.split("?")[0]);
  for (const c of p.endsWith("/") ? [path.join(p, "index.html")] : [p, `${p}.html`]) {
    const f = path.join(root, c);
    if (f.startsWith(root) && fs.existsSync(f) && fs.statSync(f).isFile()) return f;
  }
  return null;
}
function sendJson(req, res, buf) {
  const gz = /\bgzip\b/.test(req.headers["accept-encoding"] ?? "");
  const headers = { "content-type": "application/json" };
  let body = buf;
  if (gz) {
    body = gzCache.get(buf) ?? zlib.gzipSync(buf, { level: 6 });
    gzCache.set(buf, body);
    headers["content-encoding"] = "gzip";
  }
  headers["content-length"] = body.length;
  res.writeHead(200, headers);
  res.end(body);
}
const fileBufs = new Map();
const server = http.createServer((req, res) => {
  const p = decodeURIComponent((req.url ?? "/").split("?")[0]);
  if (p.startsWith("/data/")) {
    ctl.hits.push(p);
    if (ctl.fail && ctl.fail.test(p)) {
      res.writeHead(500, { "content-type": "text/plain" });
      res.end("boom");
      return;
    }
    if (ctl.notFound && ctl.notFound.test(p)) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    if (ctl.override.has(p)) return sendJson(req, res, Buffer.from(JSON.stringify(ctl.override.get(p))));
    if (FIXTURES[p]) return sendJson(req, res, Buffer.from(JSON.stringify(FIXTURES[p])));
    const f = resolveFile(DATA_DIR, p.slice("/data".length));
    if (!f) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
      return;
    }
    let buf = fileBufs.get(f);
    if (!buf) {
      buf = fs.readFileSync(f);
      fileBufs.set(f, buf);
    }
    return sendJson(req, res, buf);
  }
  const f = resolveFile(OUT_DIR, p);
  if (!f) {
    res.writeHead(404, { "content-type": TYPES[".html"] });
    res.end(fs.readFileSync(path.join(OUT_DIR, "404.html")));
    return;
  }
  res.writeHead(200, { "content-type": TYPES[path.extname(f)] ?? "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
});
await new Promise((r) => server.listen(PORT, "127.0.0.1", r));

// ---------- 假登入 ----------
const USER_ID = "00000000-0000-4000-8000-0000000000bb";
const EMAIL = "warrant@example.test";
const b64url = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const exp = Math.floor(new Date("2030-01-01T00:00:00Z").getTime() / 1000);
const user = { id: USER_ID, aud: "authenticated", role: "authenticated", email: EMAIL, app_metadata: { provider: "google" }, user_metadata: {}, created_at: "2026-01-01T00:00:00Z" };
const fakeSession = {
  access_token: `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url({ sub: USER_ID, email: EMAIL, role: "authenticated", aud: "authenticated", exp })}.sig`,
  token_type: "bearer", expires_in: 3600, expires_at: exp, refresh_token: "warrant-refresh", user,
};
const profileRow = { user_id: USER_ID, email: EMAIL, display_name: null, avatar_url: null, role: "user", status: "approved" };

async function newContext(browser, { theme = "dark" } = {}) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: "block", locale: "zh-TW", timezoneId: "Asia/Taipei", colorScheme: theme });
  await context.addInitScript(([k, v, theme]) => {
    try {
      if (!localStorage.getItem(k)) localStorage.setItem(k, v);
      localStorage.setItem("theme", theme);
    } catch {}
  }, ["sb-eroycvbgfitvyulfbbnw-auth-token", JSON.stringify(fakeSession), theme]);
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
    if (req.method() === "GET" || req.method() === "HEAD") return json([]);
    return json([], 201);
  });
  return context;
}

/** Chrome DevTools 的 Fast 3G 預設值(1.6 Mbps 下行、150 ms RTT 的近似;× 0.9 同 DevTools)。 */
async function throttle(page, kbps = 1600, latency = 150) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false, latency, downloadThroughput: (kbps * 1024 / 8) * 0.9, uploadThroughput: (750 * 1024 / 8) * 0.9,
  });
  return cdp;
}

const cards = (page) => page.locator('[data-testid="warrant-split-columns"]');
async function screenState(page) {
  return page.evaluate((emptyCopy) => {
    const txt = document.body.innerText;
    return {
      cards: document.querySelectorAll('[data-testid="warrant-split-columns"]').length,
      empty: txt.includes(emptyCopy),
      loading: !!document.querySelector('[data-testid="warrant-tf-loading"]'),
      error: !!document.querySelector('[data-testid="warrant-tf-error"]'),
    };
  }, EMPTY_COPY);
}
async function shot(page, name) {
  if (!SHOTS_DIR) return;
  fs.mkdirSync(SHOTS_DIR, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS_DIR, `${PREFIX}-${name}.png`), fullPage: false });
}
const noHorizontalOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
const tfButton = (page, label) => page.getByRole("button", { name: label, exact: true });

/** 這一輪 /data/branches 下載的權證分點檔 → 解壓後位元組(看真正下了哪些檔)。 */
function warrantFilesHit() {
  return [...new Set(ctl.hits.filter((p) => /warrant_branches|warrant-stock-details/.test(p)))];
}

const results = [];
const check = (name, ok, detail) => {
  if (!EXPECT_FIX) {
    console.log(`OBSERVE ${name}  ${JSON.stringify(detail ?? ok)}`);
    return;
  }
  results.push({ name, ok, ...(ok ? {} : { detail }) });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${ok ? "" : `  ${JSON.stringify(detail)}`}`);
};
const note = (name, detail) => console.log(`INFO ${name}  ${JSON.stringify(detail)}`);
const URL_WARRANT = `${BASE}/branch?tab=warrant`;

const browser = await chromium.launch({ headless: true, executablePath });
try {
  // ---------- A. 不限速 ----------
  for (const theme of ["dark", "light"]) {
    const context = await newContext(browser, { theme });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    ctl.hits = [];
    const t0 = Date.now();
    await page.goto(URL_WARRANT, { waitUntil: "load" });
    await cards(page).first().waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
    const tFirst = Date.now() - t0;
    const s = await screenState(page);
    note(`A(${theme}): first card after ms`, tFirst);
    check(`A(${theme}): 1d renders cards with the real file`, s.cards > 0 && !s.empty, s);
    note(`A(${theme}): warrant files fetched`, warrantFilesHit());
    if (EXPECT_FIX) check(`A(${theme}): does not download the 21.6 MB legacy file`, !warrantFilesHit().includes("/data/branches/warrant_branches.json"), warrantFilesHit());
    await page.waitForTimeout(300);
    await shot(page, `${theme}-warrant-1d`);
    check(`A(${theme}): no horizontal overflow`, await noHorizontalOverflow(page), null);
    if (theme === "dark") {
      // E. 點買超第一列 → 逐檔權證明細
      const firstRow = page.locator('[data-testid="warrant-split-columns"]').first().locator("li button").first();
      await firstRow.click();
      const detail = page.locator("text=的權證明細").first();
      await detail.waitFor({ state: "visible", timeout: 30_000 }).catch(() => {});
      check("E: expanding a row shows its per-warrant breakdown", await detail.isVisible(), warrantFilesHit());
      await page.waitForTimeout(200);
      await shot(page, `${theme}-warrant-1d-expanded`);
      // 切 近 2 日
      await tfButton(page, "近 2 日").click();
      await cards(page).first().waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
      const s2 = await screenState(page);
      check("A: 2d renders cards", s2.cards > 0 && !s2.empty, s2);
    }
    check(`A(${theme}): no page errors`, errors.length === 0, errors);
    await context.close();
  }

  // ---------- B. 限速 Fast 3G ----------
  {
    const context = await newContext(browser, { theme: "dark" });
    const page = await context.newPage();
    await throttle(page);
    ctl.hits = [];
    const t0 = Date.now();
    await page.goto(URL_WARRANT, { waitUntil: "domcontentloaded" });
    // 等分點頁本身(其他四個小檔)出來,再看權證分頁此刻顯示什麼。
    await page.getByRole("button", { name: "近 1 日", exact: true }).waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
    const sEarly = await screenState(page);
    note("B: ms until tab bar visible", Date.now() - t0);
    note("B: state when tab bar first visible", sEarly);
    check("B: never shows the empty copy while 1d is still loading", !(sEarly.cards === 0 && sEarly.empty), sEarly);
    if (sEarly.cards === 0) check("B: shows a loading state instead", sEarly.loading, sEarly);
    if (EXPECT_FIX && sEarly.loading) await shot(page, "dark-warrant-loading");
    await tfButton(page, "近 2 日").click();
    const s2early = await screenState(page);
    note("B: 2d right after click (before data)", s2early);
    check("B: 2d click while loading is not 'no data'", !(s2early.cards === 0 && s2early.empty), s2early);
    await cards(page).first().waitFor({ state: "visible", timeout: 180_000 }).catch(() => {});
    note("B: ms until first 2d card (Fast 3G)", Date.now() - t0);
    const sLate = await screenState(page);
    check("B: 2d cards eventually render", sLate.cards > 0, sLate);
    note("B: warrant files fetched", warrantFilesHit());
    await context.close();
  }

  // ---------- C. 抓檔失敗 → 錯誤＋重試 ----------
  for (const theme of ["dark", "light"]) {
    const context = await newContext(browser, { theme });
    const page = await context.newPage();
    ctl.fail = /warrant_branches/;
    await page.goto(URL_WARRANT, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const s = await screenState(page);
    check(`C(${theme}): fetch failure is not shown as 'no data'`, !s.empty, s);
    check(`C(${theme}): fetch failure shows an error with retry`, s.error, s);
    await shot(page, `${theme}-warrant-error`);
    ctl.fail = null;
    if (s.error) {
      await page.locator('[data-testid="warrant-tf-error"]').getByRole("button", { name: "重試" }).click();
      await cards(page).first().waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
      const s2 = await screenState(page);
      check(`C(${theme}): retry recovers`, s2.cards > 0 && !s2.error, s2);
    }
    {
      // 載入中截圖:讓權證分點檔一直不回(route 卡住)。
      const ctx2 = await newContext(browser, { theme });
      const p2 = await ctx2.newPage();
      await p2.route(/warrant_branches/, () => new Promise(() => {}));
      await p2.goto(URL_WARRANT, { waitUntil: "load" });
      await p2.waitForTimeout(1200);
      const sl = await screenState(p2);
      check(`C(${theme}): stalled fetch shows loading`, sl.loading && !sl.empty, sl);
      await shot(p2, `${theme}-warrant-loading`);
      await ctx2.close();
    }
    await context.close();
  }

  // ---------- F. 程式碼先於匯出上線:區間檔 404 → 退回舊全市場檔,明細內嵌 ----------
  if (EXPECT_FIX) {
    const context = await newContext(browser, { theme: "dark" });
    const page = await context.newPage();
    ctl.notFound = /warrant_branches_(1d|2d|5d|30d|120d)\.json$/;
    ctl.hits = [];
    await page.goto(URL_WARRANT, { waitUntil: "load" });
    await cards(page).first().waitFor({ state: "visible", timeout: 60_000 }).catch(() => {});
    const s = await screenState(page);
    check("F: 404 on per-timeframe file falls back to the legacy file", s.cards > 0 && !s.error, s);
    await tfButton(page, "近 5 日").click();
    await page.waitForTimeout(300);
    const s5 = await screenState(page);
    check("F: legacy fills every timeframe (no second legacy download)", s5.cards > 0 && ctl.hits.filter((p) => p === "/data/branches/warrant_branches.json").length === 1, { s5, hits: warrantFilesHit() });
    await page.locator('[data-testid="warrant-split-columns"]').first().locator("li button").first().click();
    const detail = page.locator("text=的權證明細").first();
    await detail.waitFor({ state: "visible", timeout: 10_000 }).catch(() => {});
    check("F: inline breakdown expands without fetching a breakdown file", await detail.isVisible() && !ctl.hits.some((p) => p.includes(".breakdown.json")), warrantFilesHit());
    ctl.notFound = null;
    await context.close();
  }

  // ---------- D. 真的沒有資料 ----------
  {
    const context = await newContext(browser, { theme: "dark" });
    const page = await context.newPage();
    const emptyTf = { version: 1, threshold: 5_000_000, data_date: "2026-10-22", timeframe: "1d", rows: [] };
    ctl.override.set("/data/branches/warrant_branches_1d.json", emptyTf);
    await page.goto(URL_WARRANT, { waitUntil: "load" });
    await page.waitForTimeout(1500);
    const s = await screenState(page);
    check("D: genuinely empty 1d shows the empty copy", s.empty && !s.loading && !s.error, s);
    ctl.override.clear();
    await context.close();
  }
} catch (e) {
  results.push({ name: "script error", ok: false });
  console.log(`FAIL script error  ${String(e?.stack ?? e)}`);
} finally {
  await browser.close();
  server.close();
}
const failed = results.filter((r) => !r.ok);
if (EXPECT_FIX) console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exitCode = failed.length ? 1 : 0;
