import { test, expect } from '@playwright/test'

// Use the same base URL as the Playwright config (preview server)
const BASE = 'http://localhost:4173'

// Dynamic exp 2h from now
const exp = Math.floor(Date.now() / 1000) + 7200
const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url')
const payload = Buffer.from(
  JSON.stringify({ sub: 'e2e-admin', exp, iat: Math.floor(Date.now() / 1000), name: 'E2E Admin' })
).toString('base64url')
const FAKE_TOKEN = `${header}.${payload}.fake-sig`
const FAKE_REFRESH = 'fake-refresh-token'

/**
 * Mocks all infrastructure routes so tests never touch real backend / Keycloak.
 */
async function mockInfra(page: import('@playwright/test').Page) {
  // identity-status → CONFIGURED so AppRouter doesn't redirect to /setup
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
  await page.route('**/api/v1/health', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) })
  )
  // Mock telemetry config
  await page.route('**/api/v1/telemetry/config', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        traces_enabled: false,
        metrics_enabled: false,
        logs_enabled: false,
        otel_collector_endpoint: '',
      }),
    })
  )
  await page.route('http://localhost:4318/**', (route) =>
    route.fulfill({ status: 200, body: '{}' })
  )
  // Mock dashboard summary so /dashboard renders without backend
  await page.route('**/api/v1/dashboard/summary', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({ active_agents: 0, mcp_servers: 0, scheduled_jobs: 0, conversation_sessions: 0 }),
    })
  )
  // Block all cross-origin except our preview server
  await page.route(/^https?:\/\/(?!localhost:4173)/, (route) => route.abort())
}

test.describe('OIDC Callback Flow', () => {
  test('callback with valid code exchanges token and lands on /dashboard', async ({ page }) => {
    await mockInfra(page)

    // Mock the Keycloak token endpoint — return a valid fake JWT
    await page.route('**/protocol/openid-connect/token', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: FAKE_TOKEN,
          refresh_token: FAKE_REFRESH,
          token_type: 'Bearer',
          expires_in: 300,
        }),
      })
    )

    // Navigate to any page first to set sessionStorage
    await page.goto(`${BASE}/login`)
    await page.waitForLoadState('load')

    // Set the PKCE code verifier in sessionStorage (required by OidcCallback page)
    await page.evaluate(() => {
      sessionStorage.setItem('pkce_code_verifier', 'fake-pkce-verifier-for-e2e-test')
    })

    // Navigate to /callback with a fake code (as Keycloak would redirect)
    await page.goto(`${BASE}/callback?code=e2e-fake-code&session_state=abc123`)

    // Should navigate to /dashboard after successful token exchange
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 8000 })
  })

  test('callback without code redirects to /login', async ({ page }) => {
    await mockInfra(page)

    await page.goto(`${BASE}/callback`)
    await page.waitForLoadState('networkidle')

    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test('callback with failed token exchange redirects to /login', async ({ page }) => {
    await mockInfra(page)

    // Mock token endpoint to fail
    await page.route('**/protocol/openid-connect/token', (route) =>
      route.fulfill({ status: 400, body: JSON.stringify({ error: 'invalid_grant' }) })
    )

    await page.goto(`${BASE}/callback?code=bad-code`)
    await page.waitForLoadState('networkidle')

    await expect(page).toHaveURL(/\/login/, { timeout: 5000 })
  })

  test('clicking login button initiates OIDC redirect', async ({ page }) => {
    await mockInfra(page)

    // Clear any existing token so login page shows
    await page.addInitScript(() => localStorage.removeItem('access_token'))

    const navigationPromise = page.waitForURL(/realms\/parthenon\/protocol\/openid-connect\/auth/, {
      timeout: 5000,
    }).catch(() => null) // may be blocked by route abort — that's ok

    await page.goto(`${BASE}/login`)
    await page.waitForLoadState('networkidle')

    const loginBtn = page.getByRole('button').first()
    await expect(loginBtn).toBeVisible()

    // Intercept the navigation rather than follow it
    let oidcUrl = ''
    page.on('request', (req) => {
      if (req.url().includes('openid-connect/auth')) oidcUrl = req.url()
    })

    await loginBtn.click()
    await page.waitForTimeout(1000)

    // Either navigation captured or URL contains OIDC params
    const finalUrl = page.url()
    const isOidcRedirect = finalUrl.includes('openid-connect/auth') || oidcUrl.includes('openid-connect/auth')
    expect(isOidcRedirect || finalUrl.includes('realms')).toBeTruthy()
  })
})
