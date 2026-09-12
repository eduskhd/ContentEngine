import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'fs';

const OUT = 'C:/Users/edupo/Desktop/ContentEngine/screenshots';
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true });
const ctx    = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page   = await ctx.newPage();

// ── 1. Library tab ──────────────────────────────────────────────────────────
await page.goto('http://localhost:8000/dashboard');
await page.waitForSelector('text=Library', { timeout: 10000 });
await page.click('text=Library');
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/01_library.png`, fullPage: false });
console.log('Screenshot 1: Library');

// ── 2. Open a clip player ───────────────────────────────────────────────────
// Click the first play button in the Library
const playBtn = page.locator('button:has-text("▶")').first();
await playBtn.click();
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/02_player_open.png`, fullPage: false });
console.log('Screenshot 2: Clip player open');

// ── 3. Scrub video to show captions ────────────────────────────────────────
// Set video currentTime to somewhere in the middle where captions appear
await page.evaluate(() => {
  const v = document.getElementById('modal-video');
  if (v) { v.currentTime = 3; }
});
await page.waitForTimeout(800);
await page.screenshot({ path: `${OUT}/03_captions_visible.png`, fullPage: false });
console.log('Screenshot 3: Caption canvas at t=3s');

// ── 4. Style tab ───────────────────────────────────────────────────────────
const styleBtns = page.locator('.cap-tab');
const count = await styleBtns.count();
if (count > 0) {
  await styleBtns.first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/04_style_tab.png`, fullPage: false });
  console.log('Screenshot 4: Style tab');
}

// ── 5. Words tab ────────────────────────────────────────────────────────────
if (count > 1) {
  await styleBtns.nth(1).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/05_words_tab.png`, fullPage: false });
  console.log('Screenshot 5: Words tab');
}

await browser.close();
console.log('Done — screenshots in', OUT);
