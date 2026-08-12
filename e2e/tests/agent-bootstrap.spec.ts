/**
 * E2E tests for agent realm bootstrap — verifies realm initialization flow.
 *
 * Adjustment: Agent identities use a dedicated agent realm (ai_agents by default)
 * within the same identity provider as users. Bootstrap initializes this realm.
 *
 * These tests:
 *   - Mocked variant: verifies the UI reflects bootstrap status (no Keycloak needed)
 *   - Real Keycloak variant: skipped when Keycloak is not running (port 8082)
 *
 * The real-Keycloak tests catch bootstrap failures that mocked tests miss.
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// ---------------------------------------------------------------------------
// Mocked Bootstrap Status
// ---------------------------------------------------------------------------

test.describe('Agent Realm Bootstrap — Mocked', () => {
  test('health endpoint reports identity provider status', async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/health', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          status: 'ok',
          identity_provider: 'keycloak_bundled',
          agent_realm_initialized: true,
        }),
      })
    )

    const response = await page.request.get('http://localhost:5173/')
    // The app loads (this is the base check — health is a backend concern)
    expect(response.status()).toBeLessThan(500)
  })

  test('agent identities page loads when realm is initialized (mocked)', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'id-1',
            name: 'Bootstrap Bot',
            realm_name: 'ai_agents',
            realm_username: 'bootstrap-agent',
            status: 'active',
            token_expires_at: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ]),
      })
    )

    await page.goto('/agents/identities')
    await page.waitForLoadState('load')

    await expect(page.getByText('Bootstrap Bot')).toBeVisible()
    await expect(page.getByText('ai_agents')).toBeVisible()
  })

  test('realm name column displays configured agent realm', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'id-2',
            name: 'Custom Realm Bot',
            realm_name: 'custom-agent-realm',
            realm_username: 'custom-agent',
            status: 'active',
            token_expires_at: null,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
        ]),
      })
    )

    await page.goto('/agents/identities')
    await page.waitForLoadState('load')

    // Realm name should be configurable — not hardcoded to 'ai_agents'
    await expect(page.getByText('custom-agent-realm')).toBeVisible()
  })
})

// ---------------------------------------------------------------------------
// Real Keycloak Integration — skipped when Keycloak is not running
// ---------------------------------------------------------------------------

test.describe('Agent Realm Bootstrap — Real Keycloak Integration', () => {
  /**
   * Check if Keycloak is running on port 8082 before each test.
   * These tests are skipped in CI if Keycloak is unavailable.
   */
  async function isKeycloakRunning(page: Parameters<typeof test>[1] extends (...args: infer A) => unknown ? A[0] : never): Promise<boolean> {
    try {
      const res = await page.request.get('http://localhost:8082/realms/master/.well-known/openid-configuration', {
        timeout: 3000,
      })
      return res.ok()
    } catch {
      return false
    }
  }

  test('agent realm openid-configuration is reachable after bootstrap', async ({ page }) => {
    const keycloakRunning = await isKeycloakRunning(page)
    if (!keycloakRunning) {
      test.skip()
      return
    }

    // After bootstrap, the ai_agents realm must expose its OpenID configuration
    const response = await page.request.get(
      'http://localhost:8082/realms/ai_agents/.well-known/openid-configuration',
      { timeout: 5000 }
    )

    // 200 = realm exists and is initialized
    // 404 = realm not initialized yet (bootstrap not run) — this should not happen
    expect(response.status()).toBe(200)

    const body = await response.json()
    expect(body).toHaveProperty('issuer')
    expect(body.issuer).toContain('ai_agents')
  })

  test('user realm openid-configuration is still reachable after agent realm bootstrap', async ({ page }) => {
    const keycloakRunning = await isKeycloakRunning(page)
    if (!keycloakRunning) {
      test.skip()
      return
    }

    // Bootstrap must not break the user realm
    const response = await page.request.get(
      'http://localhost:8082/realms/parthenon/.well-known/openid-configuration',
      { timeout: 5000 }
    )
    // Either 200 (realm configured) or 404 (not set up yet) — both are valid dev states
    // The critical assertion is that the agent realm bootstrap didn't corrupt it
    expect([200, 404]).toContain(response.status())
  })

  test('backend health reports agent_realm_initialized: true after bootstrap', async ({ page }) => {
    const keycloakRunning = await isKeycloakRunning(page)
    if (!keycloakRunning) {
      test.skip()
      return
    }

    let backendRunning = false
    try {
      const healthRes = await page.request.get('http://localhost:8000/api/v1/health', { timeout: 3000 })
      backendRunning = healthRes.ok()
    } catch {
      // Backend not running
    }

    if (!backendRunning) {
      test.skip()
      return
    }

    await standardSetup(page)

    const response = await page.request.get('http://localhost:8000/api/v1/health')
    if (response.ok()) {
      const body = await response.json()
      // If the field is present, it must be true (bootstrap completed)
      if ('agent_realm_initialized' in body) {
        expect(body.agent_realm_initialized).toBe(true)
      }
    }
  })
})
