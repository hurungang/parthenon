import puppeteer from 'puppeteer-core'

const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: 'new',
  args: ['--no-sandbox', '--window-size=1600,1000'],
  defaultViewport: { width: 1600, height: 1000 },
})
const page = await browser.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 200))
})
try {
  await page.goto('http://localhost:5173/agents/panel', { waitUntil: 'networkidle2', timeout: 45000 })
} catch (e) {
  console.log('goto issue:', e.message)
}
await new Promise((r) => setTimeout(r, 3000))
console.log('URL now:', page.url())

// Keycloak login if redirected
if (page.url().includes('8082')) {
  await page.waitForSelector('#username', { timeout: 20000 })
  await page.type('#username', 'qfix-tester')
  await page.type('#password', 'qfix-pass-123')
  await page.click('#kc-login')
  await page.waitForFunction(() => !location.href.includes('8082'), { timeout: 30000 }).catch(() => {})
  await new Promise((r) => setTimeout(r, 3000))
  console.log('URL after login:', page.url())
}

await page.goto('http://localhost:5173/agents/panel', { waitUntil: 'networkidle2', timeout: 45000 }).catch((e) => console.log('goto2:', e.message))
await new Promise((r) => setTimeout(r, 3000))

const metrics = await page.evaluate(() => {
  const out = { url: location.href, viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio } }
  const grids = [...document.querySelectorAll('div')].filter((d) => getComputedStyle(d).display === 'grid')
  out.grids = grids.map((g) => {
    const cs = getComputedStyle(g)
    const kids = [...g.children].map((k) => {
      const r = k.getBoundingClientRect()
      return { cls: k.className.slice(0, 60), x: Math.round(r.x), w: Math.round(r.width) }
    })
    return { gtc: cs.gridTemplateColumns, w: Math.round(g.getBoundingClientRect().width), kids }
  })
  const papers = [...document.querySelectorAll('.MuiPaper-root')]
  out.papers = papers.slice(0, 6).map((p) => {
    const r = p.getBoundingClientRect()
    return { x: Math.round(r.x), w: Math.round(r.width), overflow: getComputedStyle(p).overflowX }
  })
  const btns = [...document.querySelectorAll('button')].map((b) => b.textContent?.trim()).filter(Boolean)
  out.buttons = btns.slice(0, 15)
  out.bodyScrollW = document.documentElement.scrollWidth
  return out
})
console.log(JSON.stringify(metrics, null, 1))
await page.screenshot({ path: 'tmp/qfix-panel.png' })
await browser.close()
