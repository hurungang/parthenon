import { chromium } from '/Users/minglijiang/source/parthenon/e2e/node_modules/playwright/index.mjs';
import path from 'path'; import fs from 'fs';
const files = ['separate-optimization-from-execution','optimizer-conversational-agent','persistent-agent-activity-state','resumable-agent-turn-persistence']
  .map(d => `docs/changes/${d}/prototype/index.html`);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1400, height: 900 } });
for (const f of files) {
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0, 160)));
  p.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 160)); });
  const reqs = [];
  p.on('request', r => reqs.push(r.url()));
  await p.goto('file://' + path.resolve(f));
  await p.waitForTimeout(400);
  // click only the first 12 buttons to stay inside the timeout
  const btns = (await p.$$('button')).slice(0, 12);
  for (const btn of btns) { await btn.click({ timeout: 1200, force: true }).catch(()=>{}); await p.waitForTimeout(80); }
  await p.waitForTimeout(200);
  const external = reqs.filter(u => !u.startsWith('file://'));
  const txt = fs.readFileSync(path.resolve(f), 'utf8');
  console.log(`${f.split('/')[2]}: ${txt.split('\n').length} lines, ${txt.length} B, ext-req ${external.length}, errors ${errs.length}`);
  errs.slice(0,4).forEach(e => console.log('   !', e));
  await p.close();
}
await b.close();
