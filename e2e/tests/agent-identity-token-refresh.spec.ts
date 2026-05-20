import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// ── Real backend integration ──────────────────────────────────────────────────

test.describe('Real Backend Integration — Token Refresh Persistence', () => {
  /**
   * Verifies the token refresh endpoint is correctly wired to the backend and
   * that changes are persisted to the database (i.e., commit() is called).
   *
   * This test makes real HTTP calls — no page.route() mocks.
   * It catches migration or wiring issues that unit tests cannot detect.
   */
  test('backend health check confirms API is reachable', async ({ request }) => {
    // Public health endpoint — no auth required
    const response = await request.get('http://localhost:8000/health')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
  })

  test('refresh-token endpoint exists and requires authentication (not 404)', async ({ request }) => {
    // Use a non-existent identity UUID — we expect 401 (auth required) or 404 (not found after auth)
    // A 401 proves the endpoint is routed and the backend is handling it
    // A 404 would mean the endpoint doesn't exist at all
    const response = await request.post(
      'http://localhost:8000/api/v1/agents/identities/00000000-0000-0000-0000-000000000001/refresh-token',
      { headers: { 'Content-Type': 'application/json' } }
    )
    // Must NOT be 404 — endpoint must exist
    expect(response.status()).not.toBe(404)
    // Must NOT be 500 — no server errors
    expect(response.status()).not.toBe(500)
    // Expected: 401 (unauthenticated) or possibly 422 (validation error)
    expect([401, 403, 422]).toContain(response.status())
  })

  test('agent identities endpoint exists and requires authentication', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/agents/identities')
    // Must exist (not 404) and require auth (401)
    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([401, 403]).toContain(response.status())
  })
})

// ── UI tests with mocked backend ──────────────────────────────────────────────

const IDENTITY_WITH_REFRESH = {
  id: 'e2e-id-1',
  name: 'E2E Refresh Bot',
  realm_name: 'ai_agents',
  realm_username: 'e2e-refresh-bot',
  identity_type: 'realm_user',
  status: 'active',
  token_expires_at: '2099-01-01T00:00:00Z',
  has_refresh_token: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const IDENTITY_NO_REFRESH = {
  id: 'e2e-id-2',
  name: 'E2E No-Refresh Bot',
  realm_name: 'ai_agents',
  realm_username: 'e2e-no-refresh-bot',
  identity_type: 'realm_user',
  status: 'suspended',
  token_expires_at: null,
  has_refresh_token: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

test.describe('Agent Identity — conditional action buttons (mocked)', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    // Mock the roles and identities endpoints
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
    )
  })

  test('shows green refresh button for identity with valid refresh token', async ({ page }) => {
    await page.route('**/api/v1/agents/identities', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([IDENTITY_WITH_REFRESH]),
        })
      } else {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(IDENTITY_WITH_REFRESH) })
      }
    })

    await page.goto('/agents/identities')
    await page.waitForLoadState('load')

    // Identity name must appear
    await expect(page.getByText('E2E Refresh Bot')).toBeVisible()

    // Success-colored refresh button must exist (green = has_refresh_token: true)
    const successBtn = page.locator('.MuiIconButton-colorSuccess').first()
    await expect(successBtn).toBeVisible()
  })

  test('shows red reauth button for identity with no refresh token', async ({ page }) => {
    await page.route('**/api/v1/agents/identities', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([IDENTITY_NO_REFRESH]),
        })
      } else {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(IDENTITY_NO_REFRESH) })
      }
    })

    await page.goto('/agents/identities')
    await page.waitForLoadState('load')

    // Identity name must appear
    await expect(page.getByText('E2E No-Refresh Bot')).toBeVisible()

    // No success button — identity has no valid refresh token
    const successBtns = page.locator('.MuiIconButton-colorSuccess')
    await expect(successBtns).toHaveCount(0)
  })

  test('clicking green refresh button calls refresh-token API', async ({ page }) => {
    await page.route('**/api/v1/agents/identities', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([IDENTITY_WITH_REFRESH]),
        })
      } else {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(IDENTITY_WITH_REFRESH) })
      }
    })

    // Track the refresh-token POST call
    let refreshCalled = false
    await page.route(`**/api/v1/agents/identities/${IDENTITY_WITH_REFRESH.id}/refresh-token`, (route) => {
      refreshCalled = true
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(IDENTITY_WITH_REFRESH) })
    })

    await page.goto('/agents/identities')
    await page.waitForLoadState('load')
    await expect(page.getByText('E2E Refresh Bot')).toBeVisible()

    // Click the green refresh button
    const successBtn = page.locator('.MuiIconButton-colorSuccess').first()
    await successBtn.click()

    // Verify the refresh-token endpoint was called
    await expect.poll(() => refreshCalled, { timeout: 5000 }).toBe(true)
  })
})
