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
  await page.route(/^https?:\/\/(?!localhost:4173)/, (route) => route.abort())
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
