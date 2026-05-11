import type { Page } from '@playwright/test'

// Dynamic exp: 2 hours from now — keeps refreshIn within JS setTimeout's 32-bit safe range
// (max ~24.8 days). Static far-future exp like 9999999999 overflows and fires immediately.
const exp = Math.floor(Date.now() / 1000) + 7200
const _header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64')
const _payload = Buffer.from(
  JSON.stringify({ sub: 'e2e-admin', exp, iat: 0, name: 'E2E Admin' })
).toString('base64')
export const FAKE_TOKEN = `${_header}.${_payload}.fake-sig`

/**
 * Full standard setup for protected-page tests:
 * 1. Register health + telemetry mocks
 * 2. Navigate directly to /login (always public, no redirect dance)
 * 3. Inject the fake JWT into localStorage via page.evaluate (guaranteed timing)
 *
 * Tests MUST call page.goto('/their-route') AFTER this returns.
 */
export async function standardSetup(page: Page) {
  await mockHealth(page)
  await mockTelemetry(page)
  // Registered AFTER catch-all so it takes priority over the abort rule
  await mockIdentityStatus(page)

  // Navigate to /login — it's always a public route, no redirect complexity
  await page.goto('/login')
  await page.waitForLoadState('load')

  // Set the fake token — localStorage persists across in-page navigations
  await page.evaluate((token) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
}

/**
 * Mocks the standard API health endpoint.
 */
export async function mockHealth(page: Page) {
  await page.route('**/api/v1/health', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) })
  )
}

/**
 * Mocks OTEL collector and aborts other cross-origin requests so they don't
 * block page load or cause hanging fetch calls in tests.
 * Also mocks the telemetry config endpoint.
 */
export async function mockTelemetry(page: Page) {
  // Mock the telemetry config endpoint
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
  
  // Mock OTEL collector
  await page.route('http://localhost:4318/**', (route) =>
    route.fulfill({ status: 200, body: '{}' })
  )
  
  // Abort any cross-origin requests that aren't the app itself (e.g. CDN, external APIs)
  // Use (?!localhost) to allow all localhost ports (5173 dev, 4173 preview, 8000 backend, 4318 OTEL)
  await page.route(/^https?:\/\/(?!localhost)/, (route) => route.abort())
}

/**
 * Mocks the identity-status endpoint so the app doesn't redirect to setup wizard.
 * Must be registered AFTER mockTelemetry's catch-all abort to take priority.
 */
export async function mockIdentityStatus(page: Page) {
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
}

/**
 * Login via UI by navigating to Keycloak login page and filling credentials.
 * Used for tests that need real authentication (e.g., permission error tests).
 * 
 * This function does NOT mock any API endpoints - it relies entirely on the real backend
 * for the OIDC flow to work correctly.
 * 
 * @param page - Playwright page object
 * @param username - Keycloak username (optional, defaults to E2E_TEST_USERNAME env var or 'testuser')
 * @param password - Keycloak password (optional, defaults to E2E_TEST_PASSWORD env var or 'testuser')
 */
export async function loginViaUI(
  page: Page,
  username: string = process.env.E2E_TEST_USERNAME || 'testuser',
  password: string = process.env.E2E_TEST_PASSWORD || 'testuser'
) {
  // Do NOT mock anything - we need real backend for OIDC flow
  
  // Navigate to app root - should redirect to /login
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  
  // Wait for /login page to load
  await page.waitForURL('**/login', { timeout: 5000 })
  
  // Click the "Sign In" button to initiate OIDC redirect
  await page.click('button:has-text("Sign In")')
  
  // Wait for Keycloak login page (OIDC redirect)
  await page.waitForURL('**/realms/**/protocol/openid-connect/**', { timeout: 15000 })
  
  // Fill in credentials
  await page.fill('input[name="username"]', username)
  await page.fill('input[name="password"]', password)
  
  // Submit the form by pressing Enter (more reliable than clicking submit button)
  await page.press('input[name="password"]', 'Enter')
  
  // Wait a moment for Keycloak to process
  await page.waitForTimeout(1000)
  
  console.log('After Enter keypress, URL:', page.url())
  
  // Wait for redirect to app (callback or main page)
  // This should happen automatically after Keycloak processes the auth
  await page.waitForURL((url) => url.href.includes('localhost:5173'), { timeout: 30000 })
  
  console.log('Redirected to app:', page.url())
  
  // If we're at /callback, wait for the final redirect to dashboard/agents/mcp
  if (page.url().includes('/callback')) {
    console.log('At /callback, waiting for final redirect...')
    await page.waitForURL(/^\/(dashboard|agents|mcp)/, { timeout: 15000 })
  }
  
  console.log('Login complete. Final URL:', page.url())
}

/**
 * Get test credentials from environment variables.
 * Used by test suites that need real authentication.
 * 
 * @returns Object with username and password
 */
export function getTestCredentials() {
  return {
    username: process.env.E2E_TEST_USERNAME || 'testuser',
    password: process.env.E2E_TEST_PASSWORD || 'testuser'
  }
}
