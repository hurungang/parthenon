// Smoke-test the modularised UX prototype from file:// with Playwright.
// Usage: node tmp/smoke_ux.mjs [rootDir]
import { chromium } from '/Users/minglijiang/source/parthenon/e2e/node_modules/playwright/index.mjs';
import fs from 'fs';
import path from 'path';

const ROOT = process.argv[2] || 'tmp/ux_split';
const abs = path.resolve(ROOT);
const pages = ['index.html', ...fs.readdirSync(path.join(abs, 'modules')).filter(f => f.endsWith('.html')).map(f => 'modules/' + f)];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
let failures = [];
let totalViews = 0;

for (const p of pages) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 300)); });
  page.on('pageerror', e => errors.push('pageerror: ' + String(e).slice(0, 300)));
  const url = 'file://' + path.join(abs, p);
  await page.goto(url);
  await page.waitForTimeout(350);

  // every view id in this document
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll('[id^="view-"]')).map(e => e.id));
  totalViews += ids.length;

  // sidebar links resolve to real pages
  const links = await page.evaluate(() => Array.from(document.querySelectorAll('a.nav-item')).map(a => a.getAttribute('href')));
  for (const h of links) {
    const f = h.split('#')[0];
    if (!f) continue;
    const target = path.resolve(path.dirname(path.join(abs, p)), f);
    if (!fs.existsSync(target)) failures.push(`${p}: dead nav href ${h}`);
  }

  // activate each view and check it is visible
  for (const id of ids) {
    await page.evaluate((vid) => { location.hash = vid; }, id);
    await page.waitForTimeout(90);
    const info = await page.evaluate((vid) => {
      const el = document.getElementById(vid);
      if (!el) return { ok: false, why: 'missing' };
      const r = el.getBoundingClientRect();
      const active = el.classList.contains('active');
      return { ok: active && r.height > 0 && r.width > 0, why: `active=${active} h=${Math.round(r.height)} w=${Math.round(r.width)}` };
    }, id);
    if (!info.ok) failures.push(`${p}: view ${id} not rendered (${info.why})`);
  }

  if (errors.length) failures.push(`${p}: ${errors.join(' | ')}`);
  await page.close();
}

// click-through: index -> every nav entry -> back
const page = await ctx.newPage();
const errs = [];
page.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0, 200)));
await page.goto('file://' + path.join(abs, 'index.html'));
await page.waitForTimeout(300);
const navHrefs = await page.evaluate(() => Array.from(new Set(Array.from(document.querySelectorAll('a.nav-item')).map(a => a.getAttribute('href')))));
for (const h of navHrefs) {
  await page.goto('file://' + path.join(abs, 'index.html'));
  await page.waitForTimeout(120);
  await page.click(`a.nav-item[href="${h}"]`);
  await page.waitForTimeout(280);
  const url = page.url();
  const want = path.resolve(path.join(abs, h.split('#')[0] || 'index.html'));
  if (!url.startsWith('file://' + want)) failures.push(`nav click ${h} landed on ${url}`);
  const active = await page.evaluate(() => {
    const a = document.querySelector('.view.active');
    return a ? a.id : null;
  });
  if (h.includes('#') && !h.endsWith(active || '###')) failures.push(`nav click ${h} activated ${active}`);
}
if (errs.length) failures.push('click-through: ' + errs.join(' | '));
await page.close();

await browser.close();
console.log('pages:', pages.length, 'views handled:', totalViews);
console.log('failures:', failures.length);
failures.slice(0, 40).forEach(f => console.log(' -', f));
