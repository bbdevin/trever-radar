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
const mobileViewport = { width: 375, height: 812 };
const viewportLabel = `${mobileViewport.width}×${mobileViewport.height}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ...iPhone, viewport: mobileViewport });
const page = await context.newPage();

try {
  await page.goto(`${BASE}/stock?id=2330`, { waitUntil: "networkidle", timeout: 30000 });

  // 1) 手機首屏資訊順序：名稱與報價同行，Decision 首要判讀、行情摘要、概況、tabs 依序可達。
  const nameBox = await page.getByTestId("stock-name").boundingBox();
  const priceBox = await page.getByTestId("stock-price").boundingBox();
  assert(await page.evaluate(() => window.scrollY <= 1), "初次載入被 active tab 自動垂直捲離頁首");
  assert(nameBox && priceBox && Math.abs(nameBox.y - priceBox.y) < 20, "股票名稱與股價／漲跌未在同一主列");
  assert(nameBox && priceBox && nameBox.x + nameBox.width <= priceBox.x + 1, "股票名稱與報價區互相重疊");
  const primaryRowOverflow = await page.getByTestId("stock-primary-row").evaluate((row) => row.scrollWidth > row.clientWidth + 1);
  assert(!primaryRowOverflow, "股票名稱／報價主列發生水平溢位");
  assert(await page.getByTestId("stock-primary-judgment").isVisible(), "Decision Header 缺少首要判讀");
  const decisionBox = await page.getByTestId("stock-decision").boundingBox();
  const marketBox = await page.getByTestId("stock-market-summary").boundingBox();
  const overviewBox = await page.getByTestId("stock-overview").boundingBox();
  const chartTabBox = await page.getByTestId("stock-tab-chart").boundingBox();
  assert(decisionBox && marketBox && overviewBox && chartTabBox && decisionBox.y < marketBox.y && marketBox.y < overviewBox.y && overviewBox.y < chartTabBox.y, "首屏順序不是 Decision → 行情摘要 → 概況 → tabs");
  assert(await page.getByTestId("stock-market-summary").locator("dl").count() === 1, "行情摘要應為單一卡片 dl");
  assert(await page.getByTestId("stock-decision").getByRole("button").getAttribute("aria-expanded") === "false", "Decision Header 初始應收合以保留首屏空間");
  await page.getByTestId("stock-decision").getByRole("button").click();
  assert(await page.getByTestId("stock-decision").getByRole("button").getAttribute("aria-expanded") === "true", "Decision Header 無法展開");
  await page.getByTestId("stock-decision").getByRole("button").click();
  assert(await page.getByTestId("stock-primary-judgment").isVisible(), "收合後首要判讀不應消失");

  // 2) 一級分頁存在
  const chipsTab = page.getByRole("tab", { name: "籌碼日報" });
  await chipsTab.waitFor({ state: "visible", timeout: 15000 });
  await chipsTab.click();
  await page.waitForSelector("#branch", { timeout: 10000 });

  // 3) 頁面無橫向溢出
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  assert(!overflow, `頁面橫向溢出：scrollWidth > clientWidth (${await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])})`);

  // 4) 買超/賣超對半切分頁
  const buyTab = page.getByRole("tab", { name: /買方/ });
  const sellTab = page.getByRole("tab", { name: /賣方/ });
  await buyTab.waitFor({ state: "visible" });
  assert(await buyTab.getAttribute("aria-selected") === "true", "籌碼日報未預設買方分頁");
  await sellTab.click();
  assert(await sellTab.getAttribute("aria-selected") === "true", "切到賣方分頁失敗");
  await buyTab.click();

  // 5) 法人 / 基本資料 / 技術 tab 存在；概況可點入基本資料；基本資料是公司、題材、庫藏股的單一連續面板
  await page.getByRole("tab", { name: "法人" }).click();
  await page.getByText("法人分").first().waitFor({ state: "visible", timeout: 5000 });
  await page.getByTestId("stock-overview").click();
  assert(await page.getByRole("tab", { name: "基本資料" }).getAttribute("aria-selected") === "true", "點概況未切至基本資料");
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
  await page.getByRole("tab", { name: "權證" }).click();
  await page.getByRole("heading", { name: "權證分點動向" }).waitFor({ state: "visible", timeout: 5000 });
  assert(await page.getByText(/熱門上市權證/).first().isVisible(), "權證分點沒有揭露熱門上市權證與前15大分點的裁剪限制");
  assert(await page.getByText(/權證資料日/).first().isVisible(), "權證摘要沒有標示資料日或舊版資料 fallback");
  const warrantOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  assert(!warrantOverflow, "權證分頁造成頁面橫向溢出");
  await chipsTab.click();
  await page.waitForSelector("#branch", { timeout: 5000 });

  // 6) 點第一個分點 → 下鑽覆層（K 線 + 進出表）
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
  console.log("  - 法人 / 基本資料 / 技術 / 權證獨立 tab；權證資料日與來源裁剪限制可見");
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
