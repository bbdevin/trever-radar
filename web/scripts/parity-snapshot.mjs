/**
 * 前後一致性快照(docs/44 W-P0 驗收用)。
 *
 * 用本機靜態伺服器提供一份 `next build` 的輸出(含 out/data 本機 fixture),以 Playwright
 * 傾印各頁/各分頁的 `document.body.innerText`,兩次輸出 diff 應為空。
 * 另外統計首頁載入時的 app_profiles 請求數,並檢查站內導覽是否為 client-side(無整頁重載)。
 *
 * 登入:不加任何 dev bypass。做法是在 localStorage 預放一份假 Supabase session,
 * 並以 route interception 回應 *.supabase.co(app_profiles 回 approved,其餘表回空陣列)。
 * /data/* 不驗 JWT(本機伺服器直接回檔案)。
 *
 * 用法:
 *   node scripts/parity-snapshot.mjs --out out --snap ../tmp/snap-base
 * 環境變數:
 *   PLAYWRIGHT_MODULE  playwright 或 playwright-core 的路徑(預設 "playwright")
 *   CHROMIUM_PATH      chromium 執行檔(預設 %LOCALAPPDATA%/ms-playwright/chromium_headless_shell-1234/...)
 */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, v, i, all) => (v.startsWith("--") ? [...acc, [v.slice(2), all[i + 1]]] : acc), []),
);
const OUT_DIR = path.resolve(args.out ?? "out");
const SNAP_DIR = path.resolve(args.snap ?? "parity-snap");
const PORT = Number(args.port ?? 3471);
const BASE = `http://127.0.0.1:${PORT}`;

const pwSpec = process.env.PLAYWRIGHT_MODULE ?? "playwright";
const pw = await import(fs.existsSync(pwSpec) ? pathToFileURL(path.join(pwSpec, "index.mjs")).href : pwSpec);
const chromium = pw.chromium ?? pw.default.chromium;
const executablePath =
  process.env.CHROMIUM_PATH ??
  path.join(
    process.env.LOCALAPPDATA ?? "",
    "ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-win64/chrome-headless-shell.exe",
  );

// ---------- static server (mimics Cloudflare Pages: /x → x.html) ----------
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".woff2": "font/woff2",
  ".webmanifest": "application/manifest+json",
};
function resolveFile(urlPath) {
  const p = decodeURIComponent(urlPath.split("?")[0]);
  const candidates = p.endsWith("/") ? [path.join(p, "index.html")] : [p, `${p}.html`];
  for (const c of candidates) {
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
const FIXED_NOW = new Date("2026-10-03T20:00:00+08:00");
const USER_ID = "00000000-0000-4000-8000-000000000001";
const EMAIL = "parity@example.test";
const b64url = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const exp = Math.floor(new Date("2030-01-01T00:00:00Z").getTime() / 1000);
const user = {
  id: USER_ID,
  aud: "authenticated",
  role: "authenticated",
  email: EMAIL,
  app_metadata: { provider: "google" },
  user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};
const fakeSession = {
  access_token: `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url({ sub: USER_ID, email: EMAIL, role: "authenticated", aud: "authenticated", exp })}.sig`,
  token_type: "bearer",
  expires_in: exp - Math.floor(FIXED_NOW.getTime() / 1000),
  expires_at: exp,
  refresh_token: "parity-refresh",
  user,
};
const profileRow = { user_id: USER_ID, email: EMAIL, display_name: null, avatar_url: null, role: "user", status: "approved" };

let profileRequests = 0;
async function newContext(browser, viewport, { fixedClock = true } = {}) {
  const context = await browser.newContext({
    viewport,
    serviceWorkers: "block",
    locale: "zh-TW",
    timezoneId: "Asia/Taipei",
  });
  // 快照固定時間,避免「幾天前」類相對時間跨日而 diff;導覽流程不固定(fake clock 也會蓋掉 performance)。
  if (fixedClock) await context.clock.setFixedTime(FIXED_NOW);
  await context.addInitScript(
    ([k, v]) => {
      try {
        if (!localStorage.getItem(k)) localStorage.setItem(k, v);
      } catch {}
    },
    ["sb-eroycvbgfitvyulfbbnw-auth-token", JSON.stringify(fakeSession)],
  );
  await context.route("https://eroycvbgfitvyulfbbnw.supabase.co/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname.startsWith("/auth/v1/user")) return json(user);
    if (url.pathname.startsWith("/auth/v1/token")) return json(fakeSession);
    if (url.pathname.startsWith("/auth/v1/")) return json({});
    if (url.pathname === "/rest/v1/app_profiles") {
      profileRequests += 1;
      const single = (req.headers()["accept"] ?? "").includes("vnd.pgrst.object");
      return json(single ? profileRow : [profileRow]);
    }
    if (req.method() === "GET" || req.method() === "HEAD") return json([]);
    return json([], 201);
  });
  return context;
}

async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(500);
}
const dump = (page) => page.evaluate(() => document.body.innerText);

const snapshots = {};
async function snap(name, page) {
  snapshots[name] = await dump(page);
}

async function snapTabs(page, prefix, tabLocator) {
  const count = await tabLocator.count();
  const labels = [];
  for (let i = 0; i < count; i += 1) labels.push(((await tabLocator.nth(i).innerText()) || `#${i}`).replace(/\s+/g, " ").trim());
  for (let i = 0; i < count; i += 1) {
    await tabLocator.nth(i).click();
    await settle(page);
    await snap(`${prefix} tab[${i}] ${labels[i]}`, page);
  }
}

const browser = await chromium.launch({ headless: true, executablePath });
const VIEWPORTS = [
  { width: 390, height: 844 },
  { width: 1280, height: 800 },
];
const STOCKS = ["2330", "4967", "6488"];
const navResult = {};

try {
  for (const vp of VIEWPORTS) {
    const vpLabel = `${vp.width}x${vp.height}`;
    const context = await newContext(browser, vp);
    const page = await context.newPage();

    // 首頁 + 各分頁(app_profiles 次數只算首頁初次載入)
    profileRequests = 0;
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await settle(page);
    await page.waitForTimeout(1200); // 涵蓋 700ms 的 profile 重試窗
    navResult[`${vpLabel} app_profiles on homepage load`] = profileRequests;
    await snap(`${vpLabel} / default`, page);
    await snapTabs(page, `${vpLabel} /`, page.locator("main [role=tablist]").first().locator("[role=tab]"));

    for (const id of STOCKS) {
      await page.goto(`${BASE}/stock?id=${id}`, { waitUntil: "load" });
      await settle(page);
      await snap(`${vpLabel} /stock?id=${id} default`, page);
      await snapTabs(page, `${vpLabel} /stock?id=${id}`, page.locator('[data-testid^="stock-tab-"]'));
    }
    await page.goto(`${BASE}/stock?id=4967#branch`, { waitUntil: "load" });
    await settle(page);
    await snap(`${vpLabel} /stock?id=4967#branch`, page);
    await page.goto(`${BASE}/stock?id=4967&tab=margin`, { waitUntil: "load" });
    await settle(page);
    await snap(`${vpLabel} /stock?id=4967&tab=margin`, page);

    await page.goto(`${BASE}/branch`, { waitUntil: "load" });
    await settle(page);
    await snap(`${vpLabel} /branch default`, page);
    await snapTabs(page, `${vpLabel} /branch`, page.locator("main button[role=tab][title]"));

    await page.goto(`${BASE}/watchlist`, { waitUntil: "load" });
    await settle(page);
    await snap(`${vpLabel} /watchlist`, page);
    await context.close();
  }

  // ---------- 站內導覽流程(手機) ----------
  {
    const context = await newContext(browser, VIEWPORTS[0], { fixedClock: false });
    const page = await context.newPage();
    await page.goto(`${BASE}/`, { waitUntil: "load" });
    await settle(page);
    await page.evaluate(() => {
      window.__parityMarker = "same-document";
    });
    const steps = [];
    const marker = () => page.evaluate(() => window.__parityMarker === "same-document");

    // 綜合分頁在 fixture 上可能為空;切到「市場掃描」取第一張卡(也順便驗證返回後 ?tab= 還原)。
    await page.locator("main [role=tablist]").first().locator("[role=tab]", { hasText: "市場掃描" }).click();
    await settle(page);
    const card = page.locator('main a[href^="/stock?id="]').first();
    const href = await card.getAttribute("href");
    await card.click();
    await page.waitForURL((u) => u.pathname === "/stock");
    await settle(page);
    steps.push({ step: `home → card ${href}`, url: page.url(), sameDocument: await marker(), hasStockHeader: (await page.getByTestId("stock-header").count()) > 0 });

    await page.goBack();
    await page.waitForURL((u) => u.pathname === "/");
    await settle(page);
    steps.push({
      step: "back",
      url: page.url(),
      sameDocument: await marker(),
      selectedHomeTab: (await page.locator('main [role=tablist] [role=tab][aria-selected="true"]').first().innerText()).replace(/\s+/g, " "),
    });

    await page.getByRole("button", { name: "搜尋股票" }).click();
    await page.getByPlaceholder(/輸入代號或名稱/).fill("6488");
    await page.getByRole("option").first().waitFor({ state: "visible" });
    await page.getByRole("option").first().click();
    await page.waitForURL((u) => u.pathname === "/stock" && u.searchParams.get("id") === "6488");
    await settle(page);
    steps.push({ step: "search → 6488", url: page.url(), sameDocument: await marker(), identity: await page.getByTestId("stock-identity-line").getAttribute("aria-label").catch(() => null) });

    await page.getByRole("button", { name: "搜尋股票" }).click();
    await page.getByPlaceholder(/輸入代號或名稱/).fill("4967");
    await page.getByRole("option").first().waitFor({ state: "visible" });
    await page.getByRole("option").first().click();
    await page.waitForURL((u) => u.searchParams.get("id") === "4967");
    await settle(page);
    steps.push({ step: "search on stock page → 4967", url: page.url(), sameDocument: await marker(), identity: await page.getByTestId("stock-identity-line").getAttribute("aria-label").catch(() => null), selectedTab: await page.locator('[data-testid^="stock-tab-"][aria-selected="true"]').getAttribute("data-testid").catch(() => null) });

    await page.getByRole("link", { name: "返回雷達" }).click();
    await page.waitForURL((u) => u.pathname === "/");
    await settle(page);
    steps.push({ step: "stock back arrow → /", url: page.url(), sameDocument: await marker() });

    await page.locator("nav[aria-label=主導覽]:visible a", { hasText: "分點" }).click();
    await page.waitForURL((u) => u.pathname === "/branch");
    await settle(page);
    steps.push({ step: "bottom nav → /branch", url: page.url(), sameDocument: await marker() });

    await page.locator("nav[aria-label=主導覽]:visible a", { hasText: "自選" }).click();
    await page.waitForURL((u) => u.pathname === "/watchlist");
    await settle(page);
    steps.push({ step: "bottom nav → /watchlist", url: page.url(), sameDocument: await marker() });

    const navEntries = await page.evaluate(() => performance.getEntriesByType("navigation").length);
    navResult["client nav steps"] = steps;
    navResult["performance navigation entries after flow"] = navEntries;
    await context.close();
  }
} catch (e) {
  navResult.error = String(e?.message ?? e);
  process.exitCode = 1;
} finally {
  await browser.close();
  server.close();
}

fs.mkdirSync(SNAP_DIR, { recursive: true });
const names = Object.keys(snapshots);
for (const [i, name] of names.entries()) {
  const file = `${String(i).padStart(3, "0")}_${name.replace(/[^\w.=-]+/g, "_").slice(0, 80)}.txt`;
  fs.writeFileSync(path.join(SNAP_DIR, file), `# ${name}\n${snapshots[name]}\n`);
}
fs.writeFileSync(path.join(SNAP_DIR, "_nav.json"), `${JSON.stringify(navResult, null, 2)}\n`);
console.log(`${names.length} snapshots → ${SNAP_DIR}`);
console.log(JSON.stringify(navResult, null, 2));
