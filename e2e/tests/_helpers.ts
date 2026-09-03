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
 * 2. Register a catch-all abort rule for non-localhost origins
 * 3. Inject the fake JWT via addInitScript (runs before any page JS)
 *
 * Tests call page.goto('/their-route') AFTER this returns.
 * Test-specific route mocks must be registered BEFORE page.goto().
 */
export async function standardSetup(page: Page) {
  // IMPORTANT: Use full-url patterns (http://localhost:8000/api/v1/...) instead of
  // glob patterns (**/api/v1/...), because Playwright's ** globs do NOT match
  // requests to a different port on the same host (localhost:8000 vs localhost:5173).
  await mockHealth(page)
  await mockTelemetry(page)
  await mockIdentityStatus(page)

  // Inject token before any page JS runs — this persists across all navigations
  await page.addInitScript((token) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
}

/**
 * Registers a catch-all route for the API backend to prevent real API calls.
 * Must be called AFTER test-specific route mocks so they take priority.
 * Routes are checked in reverse registration order.
 */
export async function mockApiCatchAll(page: Page) {
  await page.route('http://localhost:8000/api/v1/**', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify({}) })
  })
}

/**
 * Origin-agnostic API catch-all — covers BOTH topologies:
 *  - direct backend: http://localhost:8000/api/v1 (VITE_API_BASE_URL set), and
 *  - same-origin Vite dev proxy: /api/v1 on the dev-server origin (no
 *    VITE_API_BASE_URL, the default), which mockApiCatchAll never matched.
 *
 * Must be registered FIRST (before standardSetup and any test-specific
 * mocks): Playwright resolves route handlers last-registered-first, so this
 * stays the lowest-priority handler.
 *
 * Why it matters: an unmocked API request that reaches the real backend gets
 * a 401, which trips the frontend axios response interceptor — it clears the
 * stored token and redirects to /login, aborting the test mid-flight with a
 * navigation. Fulfilling every API request keeps mock-first tests hermetic.
 * The public bootstrap endpoints (identity-status, health) return realistic
 * payloads so the app does not divert to the setup wizard.
 */
export async function mockApiCatchAllProxyAware(page: Page) {
  await page.route(/\/api\/v1\//, (route) => {
    const url = route.request().url()
    if (url.includes('/setup/identity-status')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          setup_state: 'CONFIGURED',
          provider_type: 'keycloak_bundled',
          oidc_provider_url: 'http://localhost:8082/realms/parthenon',
        }),
      })
    }
    if (url.endsWith('/api/v1/health')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok' }),
      })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

/**
 * Mocks the standard API health endpoint.
 * Uses explicit localhost:8000 URL to ensure cross-origin matching works.
 */
export async function mockHealth(page: Page) {
  await page.route('http://localhost:8000/api/v1/health', (route) =>
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
  await page.route('http://localhost:8000/api/v1/telemetry/config', (route) =>
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
  await page.route(/^https?:\/\/(?!localhost)/, (route) => route.abort())
}

/**
 * Mocks the identity-status endpoint so the app doesn't redirect to setup wizard.
 */
export async function mockIdentityStatus(page: Page) {
  await page.route('http://localhost:8000/api/v1/setup/identity-status', (route) =>
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
