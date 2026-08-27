/**
 * 手機版個股頁驗收腳本（Playwright）— IA-5 籌碼日報 / 分點下鑽
 * 用法：先 `npx serve out -p 3456`，再 `node scripts/verify-mobile-stock.mjs`
 */
import { chromium, devices } from "playwright";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3456";
const failures = [];

function assert(cond, msg) {
  if (!cond) failures.push(msg);
}

const iPhone = devices["iPhone 13"];
const viewportLabel = iPhone.viewport
  ? `${iPhone.viewport.width}×${iPhone.viewport.height}`
  : "iPhone 13 預設 viewport";

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ...iPhone });
const page = await context.newPage();

try {
  await page.goto(`${BASE}/stock?id=2330`, { waitUntil: "networkidle", timeout: 30000 });

  // 1) 一級分頁存在
  const chipsTab = page.getByRole("tab", { name: "籌碼日報" });
  await chipsTab.waitFor({ state: "visible", timeout: 15000 });
  await chipsTab.click();
  await page.waitForSelector("#branch", { timeout: 10000 });

  // 2) 頁面無橫向溢出
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  assert(!overflow, `頁面橫向溢出：scrollWidth > clientWidth (${await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])})`);

  // 3) 買超/賣超對半切分頁
  const buyTab = page.getByRole("tab", { name: /買方/ });
  const sellTab = page.getByRole("tab", { name: /賣方/ });
  await buyTab.waitFor({ state: "visible" });
  assert(await buyTab.getAttribute("aria-selected") === "true", "籌碼日報未預設買方分頁");
  await sellTab.click();
  assert(await sellTab.getAttribute("aria-selected") === "true", "切到賣方分頁失敗");
  await buyTab.click();

  // 4) 法人 / 基本資料 / 技術 tab 存在；基本資料是公司、題材、庫藏股的單一連續面板
  await page.getByRole("tab", { name: "法人" }).click();
  await page.getByText("法人分").first().waitFor({ state: "visible", timeout: 5000 });
  await page.getByRole("tab", { name: "基本資料" }).click();
  const basicPanel = page.getByRole("tabpanel", { name: "基本資料" });
  await basicPanel.getByRole("heading", { name: "公司資料" }).waitFor({ state: "visible", timeout: 5000 });
  assert(await basicPanel.getByRole("heading", { name: "題材" }).isVisible(), "基本資料缺少題材 section");
  assert(await basicPanel.getByRole("heading", { name: "庫藏股" }).isVisible(), "基本資料缺少庫藏股 section");
  await basicPanel.getByText("分類日").first().waitFor({ state: "visible", timeout: 5000 });
  assert(await basicPanel.getByText("來源更新").first().isVisible(), "題材 section 缺少來源更新欄位");
  const infoTabs = await page.getByRole("tab").allTextContents();
  assert(!infoTabs.includes("公司資料") && !infoTabs.includes("題材") && !infoTabs.includes("庫藏股"), "基本資料不應有公司／題材／庫藏股內部分頁");
  const basicOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  assert(!basicOverflow, "基本資料分頁造成頁面橫向溢出");
  await page.getByRole("tab", { name: "技術" }).click();
  await page.getByText("技術分").first().waitFor({ state: "visible", timeout: 5000 });
  await chipsTab.click();
  await page.waitForSelector("#branch", { timeout: 5000 });

  // 5) 點第一個分點 → 下鑽覆層（K 線 + 進出表）
  const firstBranch = page.locator("#branch button").filter({ hasText: /張$/ }).first();
  await firstBranch.click();
  const backBtn = page.getByRole("button", { name: "返回籌碼日報" });
  await backBtn.waitFor({ state: "visible", timeout: 8000 });
  const hasTable = await page.locator("th", { hasText: "淨張" }).count() > 0;
  assert(hasTable, "下鑽覆層沒有進出明細表（淨張欄）");
  await backBtn.click();
  await backBtn.waitFor({ state: "hidden", timeout: 5000 });

  console.log(`✓ 手機 viewport ${viewportLabel} 驗收通過`);
  console.log("  - 無頁面橫向溢出");
  console.log("  - 籌碼日報買方/賣方對半切可切");
  console.log("  - 法人 / 基本資料 / 技術獨立 tab；題材列含分類日與來源更新");
  console.log("  - 點分點進入下鑽並可返回");
} catch (e) {
  failures.push(`執行錯誤: ${e.message}`);
} finally {
  await browser.close();
}

if (failures.length) {
  console.error("✗ 驗收失敗:");
  failures.forEach((f) => console.error(`  - ${f}`));
  process.exit(1);
}
