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

  // 1) 手機首屏：返回／identity／收藏三欄；報價與 metadata 置於 identity 下方。
  const identity = page.getByTestId("stock-identity-line");
  const primaryRow = page.getByTestId("stock-primary-row");
  const primaryRowBox = await primaryRow.boundingBox();
  const watchlistBox = await page.getByTestId("stock-watchlist").boundingBox();
  assert(await page.evaluate(() => window.scrollY <= 1), "初次載入被 active tab 自動垂直捲離頁首");
  assert((await identity.getAttribute("aria-label"))?.trim() === "2330 台積電", "identity 應以 aria-label 呈現代號加名稱");
  assert(primaryRowBox && watchlistBox && watchlistBox.height >= 44, "收藏按鈕須達 44px touch target");
  assert(primaryRowBox && watchlistBox && watchlistBox.y <= primaryRowBox.y + 4 && watchlistBox.x > primaryRowBox.x, "收藏按鈕應位於右上方");
  const nameStyle = await page.getByTestId("stock-name").evaluate((element) => {
    const style = getComputedStyle(element);
    return { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, textOverflow: style.textOverflow, overflow: style.overflow };
  });
  assert(nameStyle.scrollWidth <= nameStyle.clientWidth + 1 && nameStyle.textOverflow !== "ellipsis" && nameStyle.overflow !== "hidden", "股票名稱應完整呈現且不被截斷");
  const primaryRowOverflow = await primaryRow.evaluate((row) => row.scrollWidth > row.clientWidth + 1);
  assert(!primaryRowOverflow, "股票名稱／報價主列發生水平溢位");
  const priceCopy = (await page.getByTestId("stock-price").textContent())?.trim() ?? "";
  assert(/^[\d,.]+[▲▼—]/.test(priceCopy) && /\((?:[+-]?\d+(?:\.\d+)?%|—)\)$/.test(priceCopy) && !/[（）]/.test(priceCopy), "報價列必須含絕對漲跌 glyph 與半形括號百分比");
  const priceOverflow = await page.getByTestId("stock-price").evaluate((element) => element.scrollWidth > element.clientWidth + 1);
  assert(!priceOverflow, "報價數字不得在 375px 溢位或換行");
  const metadataStyle = await page.getByTestId("stock-metadata").evaluate((element) => {
    const style = getComputedStyle(element);
    return { copy: element.textContent, whiteSpace: style.whiteSpace, textOverflow: style.textOverflow, overflow: style.overflow, scrollHeight: element.scrollHeight, clientHeight: element.clientHeight };
  });
  assert(!metadataStyle.copy?.includes("2330") && metadataStyle.whiteSpace !== "nowrap" && metadataStyle.textOverflow !== "ellipsis" && metadataStyle.overflow !== "hidden" && metadataStyle.scrollHeight <= metadataStyle.clientHeight + 1, "股票 metadata 應完整呈現市場／產業且不含代號");
  assert(await page.getByTestId("stock-market-label").isVisible(), "上市／上櫃標籤應清楚可見");
  const marketLabelColor = await page.getByTestId("stock-market-label").evaluate((element) => getComputedStyle(element).color);
  const industrySpan = page.getByTestId("stock-metadata").locator("span.text-muted-foreground");
  if (await industrySpan.count()) {
    const industryColor = await industrySpan.first().evaluate((element) => getComputedStyle(element).color);
    assert(marketLabelColor !== industryColor, "上市／上櫃標籤應與產業灰字區分");
  }
  assert(await page.getByTestId("stock-price").isVisible(), "股價應顯示於名稱下方");
  const priceBox = await page.getByTestId("stock-price").boundingBox();
  const nameBox = await page.getByTestId("stock-name").boundingBox();
  assert(priceBox && nameBox && priceBox.y >= nameBox.y + nameBox.height - 2, "股價列應在名稱下方");
  assert(await page.getByTestId("stock-decision").isVisible(), "評分區塊應固定顯示");
  // docs/46:標頭只剩一顆「多方 N · 空方 N ›」按鈕(切到多空分頁),不再有展開收合。
  assert(await page.getByTestId("stock-decision").getByRole("button").count() === 1, "評分區塊應只有多空連結一顆按鈕");
  assert(await page.getByTestId("stock-bullbear-link").isVisible(), "標頭缺少多空連結");
  { const order = await page.locator('[data-testid^="stock-tab-"]').evaluateAll((els) => els.slice(0, 2).map((e) => e.getAttribute("data-testid")));
    assert(order.join() === "stock-tab-chart,stock-tab-tech", `多空分頁應在 K線 右邊第二格(實際 ${order})`); }
  assert(await page.getByTestId("stock-decision").getByTestId("stock-price-targets").count() === 0, "觀察／失效應移出左側評分區");
  for (const testId of ["stock-header", "stock-context-grid"]) {
    const hasOverflow = await page.getByTestId(testId).evaluate((element) => element.scrollWidth > element.clientWidth + 1);
    assert(!hasOverflow, `${testId} 發生水平溢位`);
  }
  assert(await page.getByTestId("stock-overview").count() === 0, "不得保留重複的概況列");
  const marketBox = await page.getByTestId("stock-market-summary").boundingBox();
  const decisionBox = await page.getByTestId("stock-decision").boundingBox();
  const contextGridBox = await page.getByTestId("stock-context-grid").boundingBox();
  assert(marketBox && decisionBox && contextGridBox && decisionBox.y + decisionBox.height <= contextGridBox.y + contextGridBox.height + 2, "評分區塊不應撐破左右欄對齊");
  const chartTabBox = await page.getByTestId("stock-tab-chart").boundingBox();
  assert(primaryRowBox && marketBox && chartTabBox && watchlistBox && watchlistBox.y <= primaryRowBox.y + 4 && primaryRowBox.x < marketBox.x && marketBox.y < chartTabBox.y, "行情摘要未對齊右欄、收藏未在右上，或 tabs 順序錯誤");
  assert(await page.getByTestId("stock-market-summary").locator("dl").count() === 1, "行情摘要應為單一卡片 dl");
  for (const label of ["量", "額", "昨收", "開盤", "最高", "最低"]) {
    assert(await page.getByTestId("stock-market-summary").getByText(label, { exact: true }).isVisible(), `行情摘要缺少 ${label}`);
  }
  for (const key of ["high", "low"]) {
    const ohlc = await page.getByTestId(`stock-market-${key}`).textContent();
    assert(Boolean(ohlc && /[▲▼]/.test(ohlc)), `行情摘要 ${key} 缺少相對昨收的語意 glyph`);
  }
  const openOhlc = (await page.getByTestId("stock-market-open").textContent())?.trim() ?? "";
  assert(!openOhlc.startsWith("—"), "開盤價持平昨收時不應顯示 — 前綴");

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

  // 5) 法人 / 基本資料 / 多空 tab 存在；基本資料是公司、題材、庫藏股的單一連續面板。
  await page.getByRole("tab", { name: "法人" }).click();
  await page.getByText("法人分").first().waitFor({ state: "visible", timeout: 5000 });
  await page.getByRole("tab", { name: "基本資料" }).click();
  const basicPanel = page.getByRole("tabpanel", { name: "基本資料" });
  await basicPanel.getByRole("heading", { name: "公司資料" }).waitFor({ state: "visible", timeout: 5000 });
  assert(await basicPanel.getByRole("heading", { name: "題材" }).isVisible(), "基本資料缺少題材 section");
  assert(await basicPanel.getByRole("heading", { name: "庫藏股" }).isVisible(), "基本資料缺少庫藏股 section");
  const themeSection = basicPanel.locator('section[aria-labelledby="theme-info-heading"]');
  const themeCopy = await themeSection.textContent();
  assert(!themeCopy?.includes("狀態未提供") && !themeCopy?.includes("分類日、來源更新與來源：資料未提供"), "題材 section 不應以缺值文案重複占版");
  const themeLinks = themeSection.getByRole("link");
  const themeLinkCount = await themeLinks.count();
  for (let i = 0; i < themeLinkCount; i += 1) {
    const href = await themeLinks.nth(i).getAttribute("href");
    assert(Boolean(href && /^https?:\/\//i.test(href)), "題材來源連結必須是絕對 http/https URL");
  }
  if (themeLinkCount) {
    const sourceLinkBox = await themeLinks.first().boundingBox();
    assert(sourceLinkBox && sourceLinkBox.height >= 44, "有來源的題材名稱連結未達 44px touch target");
  }
  const infoTabs = await page.getByRole("tab").allTextContents();
  assert(!infoTabs.includes("公司資料") && !infoTabs.includes("題材") && !infoTabs.includes("庫藏股"), "基本資料不應有公司／題材／庫藏股內部分頁");
  const basicOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  assert(!basicOverflow, "基本資料分頁造成頁面橫向溢出");
  await page.getByRole("tab", { name: "多空" }).click();
  await page.getByTestId("bullbear-panel").waitFor({ state: "visible", timeout: 5000 });
  for (const sec of ["tech", "chips", "levels"]) {
    assert(await page.getByTestId(`bullbear-section-${sec}`).isVisible(), `多空分頁缺少 ${sec} 段`);
  }
  assert((await page.getByTestId("bullbear-panel").locator("[aria-expanded]").count()) === 0, "多空分頁不應有展開按鈕(全部列出)");
  assert((await page.getByTestId("bullbear-panel").locator("details").count()) === 0, "多空分頁不應有收合區(details),「怎麼算」常駐顯示");
  // docs/46 §6.8:壓力分析併入技術分析卡成小節;籌碼分析為第二張卡。
  assert((await page.getByTestId("bullbear-section-tech").getByTestId("bullbear-section-levels").count()) === 1, "壓力分析應是技術分析卡內的小節");
  { const cards = await page.getByTestId("bullbear-panel").evaluate((el) => [...el.children].map((c) => c.getAttribute("data-testid")));
    assert(cards.join() === "bullbear-overview,bullbear-section-tech,bullbear-section-chips", `多空卡片順序應為 總覽→技術→籌碼(實際 ${cards})`); }
  // docs/46 §6.7:技術指標併入技術分析段頂(指標列),不再有獨立卡片與「技術訊號原文」收合區。
  { const techSec = page.getByTestId("bullbear-section-tech");
    const metrics = techSec.getByTestId("tech-metrics");
    assert((await metrics.count()) + (await techSec.getByTestId("tech-metrics-missing").count()) === 1, "技術分析段應有指標列(或尚未產出技術指標提示)");
    if (await metrics.count()) {
      assert(await metrics.getByText("技術分", { exact: true }).isVisible(), "指標列缺少技術分");
      assert(!(await metrics.evaluate((el) => el.scrollWidth > el.clientWidth + 1)), "指標列發生水平溢位");
    }
    assert((await page.getByTestId("tech-signal-details").count()) === 0, "不應再有「技術訊號原文」收合區");
    assert((await page.getByRole("heading", { name: "技術指標" }).count()) === 0, "不應再有獨立的技術指標卡");
    assert((await techSec.locator("details").count()) === 0, "技術分析段不應有收合區(details)"); }
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
  console.log("  - 法人 / 基本資料 / 多空 / 權證獨立 tab；權證資料日與來源裁剪限制可見");
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
