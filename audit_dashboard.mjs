import { chromium } from 'playwright';

const OUT = 'C:/Users/edupo/Desktop/ContentEngine/screenshots';
const errors = [];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Capture ALL console errors
page.on('console', msg => {
  if (msg.type() === 'error') errors.push(`CONSOLE ERROR: ${msg.text()}`);
});
page.on('pageerror', e => errors.push(`PAGE ERROR: ${e.message}`));
page.on('requestfailed', req => errors.push(`NETWORK FAIL: ${req.url()} — ${req.failure()?.errorText}`));

// ── Overview tab ──────────────────────────────────────────────────────────────
await page.goto('http://localhost:8000/dashboard');
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/tab_overview.png` });
console.log('Overview tab captured');

// ── Clips tab ────────────────────────────────────────────────────────────────
await page.click('text=Clips');
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/tab_clips.png` });
console.log('Clips tab captured');

// ── Jobs tab ─────────────────────────────────────────────────────────────────
await page.click('text=Jobs');
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/tab_jobs.png` });
console.log('Jobs tab captured');

// ── New Job tab ───────────────────────────────────────────────────────────────
await page.click('text=+ New Job');
await page.waitForTimeout(1000);
await page.screenshot({ path: `${OUT}/tab_newjob.png` });
console.log('New Job tab captured');

// ── Analytics tab ─────────────────────────────────────────────────────────────
await page.click('text=Analytics');
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/tab_analytics.png` });
console.log('Analytics tab captured');

// ── Library + Position tab ───────────────────────────────────────────────────
await page.click('text=Library');
await page.waitForTimeout(1500);
const playBtn = page.locator('button:has-text("▶")').first();
await playBtn.click();
await page.waitForTimeout(2000);
const tabs = page.locator('.cap-tab');
const count = await tabs.count();
console.log(`Caption tabs found: ${count}`);
if (count >= 3) {
  await tabs.nth(2).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/tab_position.png` });
  console.log('Position tab captured');
}

// ── Mobile view ───────────────────────────────────────────────────────────────
await browser.close();

const browser2 = await chromium.launch({ headless: true });
const mctx = await browser2.newContext({ viewport: { width: 390, height: 844 } });
const mpage = await mctx.newPage();
mpage.on('console', msg => { if (msg.type() === 'error') errors.push(`MOBILE ERROR: ${msg.text()}`); });
await mpage.goto('http://localhost:8000/dashboard');
await mpage.waitForTimeout(2000);
await mpage.screenshot({ path: `${OUT}/mobile_view.png`, fullPage: false });
console.log('Mobile view captured');
await browser2.close();

console.log('\n=== ERRORS FOUND ===');
if (errors.length === 0) {
  console.log('No console errors!');
} else {
  errors.forEach(e => console.log(e));
}
console.log(`Total errors: ${errors.length}`);
