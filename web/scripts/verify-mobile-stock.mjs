/**
 * 手機版個股頁驗收腳本（Playwright）
 * 用法：先 `npx serve out -p 3456`，再 `node scripts/verify-mobile-stock.mjs`
 */
import { chromium, devices } from "playwright";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3456";
const failures = [];

function assert(cond, msg) {
  if (!cond) failures.push(msg);
}

const iPhone = devices["iPhone 13"];

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ ...iPhone });
const page = await context.newPage();

try {
  await page.goto(`${BASE}/stock?id=2330`, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForSelector("#branch", { timeout: 15000 });

  // 1) 頁面無橫向溢出
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth > doc.clientWidth + 1;
  });
  assert(!overflow, `頁面橫向溢出：scrollWidth > clientWidth (${await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])})`);

  // 2) 展開第一個買超分點 → 明細柱狀圖可見
  const firstBranchBtn = page.locator("#branch button[aria-expanded]").first();
  await firstBranchBtn.click();
  await page.waitForTimeout(300);
  const chartRegion = page.locator('[role="region"][aria-label*="淨買賣明細"]').first();
  await chartRegion.waitFor({ state: "visible", timeout: 5000 });
  const barCount = await chartRegion.locator(".bg-up, .bg-down").count();
  assert(barCount > 0, `分點明細柱狀圖無渲染（bar count = ${barCount}）`);

  // 3) 勾選分點 → K 線工具列「分點」pane 可切換
  const checkbox = page.locator('#branch input[type="checkbox"]').first();
  await checkbox.check();
  await page.waitForTimeout(500);
  const selBtn = page.locator("#stock-kchart button", { hasText: "分點" });
  await selBtn.waitFor({ state: "visible" });
  const selPressed = await selBtn.evaluate((el) =>
    el.className.includes("border-[color:var(--border-strong)]") || el.className.includes("bg-muted"),
  );
  assert(selPressed, "勾選分點後未自動切換到 K 線「分點」子 pane");

  // 4) 多日資料時明細區可橫向捲動；少日資料填滿即可
  const scrollInfo = await chartRegion.evaluate((el) => ({
    scrollW: el.scrollWidth,
    clientW: el.clientWidth,
    canScroll: el.scrollWidth > el.clientWidth,
  }));
  const needsScroll = barCount * 6 > scrollInfo.clientW;
  if (needsScroll) {
    assert(scrollInfo.canScroll, `分點明細應可橫向捲動（scroll=${scrollInfo.scrollW}, client=${scrollInfo.clientW}）`);
  }

  console.log("✓ 手機 viewport 375×812 驗收通過");
  console.log(`  - 無頁面橫向溢出`);
  console.log(`  - 分點明細柱狀圖 ${barCount} 根`);
  console.log(`  - 勾選分點後 K 線自動切換分點 pane`);
  console.log(`  - 明細區${needsScroll ? "可橫向捲動" : "完整顯示"} (${scrollInfo.scrollW}px)`);
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
