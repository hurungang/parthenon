import { chromium } from '/Users/minglijiang/source/parthenon/e2e/node_modules/playwright/index.mjs';
import path from 'path';
const ROOT = path.resolve('docs/master/ux/prototype');
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1500, height: 950 } });
const errs = [];
const p = await ctx.newPage();
p.on('pageerror', e => errs.push('pageerror: ' + String(e).slice(0,200)));
p.on('console', m => { if (m.type()==='error' && !/attribute d: Expected number/.test(m.text())) errs.push('console: ' + m.text().slice(0,200)); });
await p.goto('file://' + path.join(ROOT, 'modules/agents.html'));
await p.waitForTimeout(400);
// Optimize on a gated agent
await p.click('button[onclick="optimizeAgentType(\'report-generator\')"]');
await p.waitForTimeout(300);
console.log('plan modal open:', await p.evaluate(() => document.getElementById('modal-optimized-plan').classList.contains('open')));
console.log('gen btn label:', await p.textContent('#opt-gen-btn'));
// regenerate
await p.click('#opt-gen-btn'); await p.waitForTimeout(1200);
console.log('after generate:', await p.textContent('#opt-gen-btn'), '| status:', await p.textContent('#opt-status-chip'));
// talk to optimizer
await p.click('#opt-chat-btn'); await p.waitForTimeout(300);
console.log('optimizer modal open:', await p.evaluate(() => document.getElementById('modal-optimizer').classList.contains('open')));
await p.fill('#optc-input', 'Can the report path be scripted end to end?');
await p.click('#optc-send'); await p.waitForTimeout(1400);
console.log('ask card:', await p.evaluate(() => !!document.getElementById('optc-ask')));
await p.click('#optc-ask button'); await p.waitForTimeout(1400);
console.log('approval card:', await p.evaluate(() => !!document.getElementById('optc-approval')));
await p.click('button[onclick="optcApprove()"]'); await p.waitForTimeout(1800);
console.log('bar live:', await p.textContent('#optc-bar-count'), '| status:', await p.textContent('#opt-status-chip'));
// disabled gated row
await p.click('button[onclick="closeModal(\'modal-optimizer\')"]').catch(()=>{});
console.log('pr-reviewer optimize disabled:', await p.getAttribute('button[onclick="optimizeAgentType(\'pr-reviewer\')"]', 'disabled') !== null);
await p.close();

const s = await ctx.newPage();
s.on('pageerror', e => errs.push('system pageerror: ' + String(e).slice(0,200)));
await s.goto('file://' + path.join(ROOT, 'modules/system.html'));
await s.waitForTimeout(400);
await s.goto('file://' + path.join(ROOT, 'modules/system.html#view-model-configs'));
await s.waitForTimeout(400);
await s.selectOption('#am-select', 'gpt-4.1'); await s.click('#am-save'); await s.waitForTimeout(200);
console.log('authoring reminder hidden:', await s.evaluate(() => document.getElementById('am-reminder').style.display === 'none'));
await s.click('button[onclick="omStaleDemo()"]'); await s.waitForTimeout(200);
console.log('optimizer stale reminder:', await s.evaluate(() => document.getElementById('om-reminder').style.display === 'flex'));
await s.close();

const c = await ctx.newPage();
c.on('pageerror', e => errs.push('chat pageerror: ' + String(e).slice(0,200)));
await c.goto('file://' + path.join(ROOT, 'modules/chat.html#view-conversational-intervention'));
await c.waitForTimeout(400);
await c.click('button[onclick="rsPlayApprove()"]'); await c.waitForTimeout(2600);
console.log('resume badge:', await c.textContent('#rs-badge'));
await c.click('button[onclick="rsPlayTerminal()"]'); await c.waitForTimeout(300);
console.log('terminal card:', await c.evaluate(() => /can no longer be resumed/.test(document.getElementById('ciMessages').textContent)));
await c.close();

await b.close();
console.log('errors:', errs.length); errs.slice(0,6).forEach(e => console.log('  !', e));
