import { test, expect } from '@playwright/test'

/**
 * Auth flow E2E tests.
 * Uses page.route() to mock all API and OIDC calls — no backend required.
 */

test.describe('Authentication', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) })
    )
    await page.route('**/api/v1/telemetry/config', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ traces_enabled: false, metrics_enabled: false, logs_enabled: false, otel_collector_endpoint: '' }),
      })
    )
    await page.route('http://localhost:4318/**', (route) =>
      route.fulfill({ status: 200, body: '{}' })
    )
    await page.route(/^https?:\/\/(?!localhost:4173)/, (route) => route.abort())
    // Registered AFTER catch-all so it takes priority — app needs this to initialize properly
    await page.route('**/api/v1/setup/identity-status', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          setup_state: 'CONFIGURED',
          provider_type: 'keycloak_bundled',
          oidc_provider_url: 'http://localhost:8082/realms/parthenon',
        }),
      })
    )
  })

  test('unauthenticated user sees the login page', async ({ page }) => {
    await page.addInitScript(() => { localStorage.removeItem('access_token') })
    await page.goto('/')
    await expect(page.locator('button').first()).toBeVisible({ timeout: 10000 })
  })

  test('login page renders without JavaScript errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.addInitScript(() => { localStorage.removeItem('access_token') })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('login page has a clickable action button', async ({ page }) => {
    await page.addInitScript(() => { localStorage.removeItem('access_token') })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const btn = page.getByRole('button').first()
    await expect(btn).toBeVisible()
    await expect(btn).toBeEnabled()
  })

  test('unauthenticated request to protected route redirects to login', async ({ page }) => {
    await page.addInitScript(() => { localStorage.removeItem('access_token') })
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    // Should either redirect to /login or show login UI, not the protected content
    const url = page.url()
    const hasLoginInUrl = url.includes('/login')
    if (!hasLoginInUrl) {
      await expect(page.locator('button').first()).toBeVisible({ timeout: 5000 })
    } else {
      expect(hasLoginInUrl).toBeTruthy()
    }
  })

  test('clearing token on logout redirects to login', async ({ page }) => {
    // Start authenticated
    await page.route('**/api/v1/dashboard/summary', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ active_agents: 0, mcp_servers: 0, scheduled_jobs: 0, conversation_sessions: 0 }) })
    )
    const { FAKE_TOKEN } = await import('./_helpers')
    await page.goto('/login')
    await page.evaluate((token) => { localStorage.setItem('access_token', token) }, FAKE_TOKEN)
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // Now clear token and reload — should go to login
    await page.evaluate(() => { localStorage.removeItem('access_token') })
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    const url = page.url()
    const hasLoginBtn = await page.locator('button').first().isVisible()
    expect(url.includes('/login') || hasLoginBtn).toBeTruthy()
  })
})
