import { chromium } from '/Users/minglijiang/source/parthenon/e2e/node_modules/playwright/index.mjs';
import path from 'path'; import fs from 'fs';
const files = ['separate-optimization-from-execution','optimizer-conversational-agent','persistent-agent-activity-state','resumable-agent-turn-persistence']
  .map(d => `docs/changes/${d}/prototype/index.html`);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
let fails = [];
for (const f of files) {
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0, 200)));
  p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 200)); });
  p.on('requestfailed', r => { if (!r.url().includes('favicon')) errs.push('reqfail: ' + r.url().slice(-60)); });
  const reqs = [];
  p.on('request', r => reqs.push(r.url()));
  await p.goto('file://' + path.resolve(f));
  await p.waitForTimeout(500);
  // click every tab, then every button inside each tab panel
  const tabs = await p.$$('.tab');
  for (const t of tabs) { await t.click().catch(()=>{}); await p.waitForTimeout(120); }
  for (const t of tabs) {
    await t.click().catch(()=>{});
    await p.waitForTimeout(120);
    const btns = await p.$$('.tab-panel.active .btn');
    for (const btn of btns) { await btn.click({ timeout: 1500 }).catch(()=>{}); await p.waitForTimeout(60); }
    await p.waitForTimeout(150);
  }
  const external = reqs.filter(u => !u.startsWith('file://'));
  const bytes = fs.statSync(path.resolve(f)).size;
  const lines = fs.readFileSync(path.resolve(f), 'utf8').split('\n').length;
  console.log(`${f}\n   ${lines} lines, ${bytes} bytes, external requests: ${external.length}, errors: ${errs.length}`);
  errs.slice(0,5).forEach(e => console.log('    !', e));
  if (errs.length || external.length) fails.push(f);
  await p.close();
}
await b.close();
console.log('pages with problems:', fails.length);
