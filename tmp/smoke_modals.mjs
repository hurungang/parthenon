import { chromium } from '/Users/minglijiang/source/parthenon/e2e/node_modules/playwright/index.mjs';
import fs from 'fs'; import path from 'path';
const ROOT = path.resolve('tmp/ux_split');
const pages = ['index.html', ...fs.readdirSync(path.join(ROOT,'modules')).map(f=>'modules/'+f)];
const b = await chromium.launch();
const ctx = await b.newContext({ viewport:{width:1440,height:900} });
let fails = [], checked = 0, redirected = 0;
for (const rel of pages) {
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('pageerror: '+String(e).slice(0,160)));
  p.on('console', m => { if (m.type()==='error' && !/attribute d: Expected number/.test(m.text())) errs.push('console: '+m.text().slice(0,160)); });
  await p.goto('file://'+path.join(ROOT, rel));
  await p.waitForTimeout(400);
  const targets = await p.evaluate(() => {
    const out = [];
    document.querySelectorAll('[onclick]').forEach((el, i) => {
      const m = /openModal\('([^']+)'\)/.exec(el.getAttribute('onclick'));
      if (m) out.push({ id: m[1], sel: el.outerHTML.slice(0, 120) });
    });
    return out;
  });
  for (const t of targets) {
    if (await p.$('#'+t.id)) {
      await p.evaluate((mid) => { openModal(mid); }, t.id);
      await p.waitForTimeout(30);
      const open = await p.evaluate((mid) => document.getElementById(mid).classList.contains('open'), t.id);
      checked++;
      if (!open) fails.push(`${rel}: modal ${t.id} did not open`);
      await p.evaluate((mid) => { closeModal(mid); }, t.id);
    } else {
      // dialog owned by another page: clicking must navigate there and open it
      await Promise.all([
        p.waitForNavigation({ timeout: 3000 }).catch(()=>{}),
        p.evaluate((mid) => { openModal(mid); }, t.id),
      ]);
      await p.waitForTimeout(450);
      const st = await p.evaluate((mid) => ({ url: location.pathname.split('/').pop() + location.search, open: !!document.getElementById(mid)?.classList.contains('open') }), t.id);
      redirected++;
      if (!st.open) fails.push(`${rel}: cross-page modal ${t.id} not open after redirect (${st.url})`);
      await p.goto('file://'+path.join(ROOT, rel));
      await p.waitForTimeout(250);
    }
  }
  await p.waitForTimeout(120);
  if (errs.length) fails.push(`${rel}: ${errs.slice(0,3).join(' | ')}`);
  await p.close();
}
await b.close();
console.log('local modals checked:', checked, 'cross-page redirects:', redirected, 'failures:', fails.length);
fails.slice(0,25).forEach(f=>console.log(' -', f));
