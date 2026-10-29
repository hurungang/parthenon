import { expect, test, type Page } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Token Expiry Alerting — dashboard alerts → click-through remediation →
 * warnings cleared. All API calls are mocked (no live backend needed).
 *
 * Journey:
 *  1. Dashboard shows separate expired/expiring indicators for agent
 *     identities and MCP sessions.
 *  2. Each warning card is clickable and navigates to the remediation page
 *     (agent identities / MCP hub).
 *  3. After refresh/re-auth (token-health refetch returns healthy), the
 *     warnings are gone.
 */

const MOCK_DASHBOARD_SUMMARY = {
  snapshot_counts: {
    agent_types: 1, agent_types_active: 1, agent_types_running: 0,
    pending_interventions: 0, model_configs: 1, model_counts: 1,
    active_schedules: 0, agent_identities: 3, agent_roles: 1,
    mcp_servers: 1, pending_access_requests: 0,
  },
  time_sensitive: {
    guardrail_breaches: 0,
    agent_executions: { completed: 0, failed: 0 },
    posture_breaches: 0,
    notification_delivered: 0, notification_failed: 0,
  },
  permission_flags: {},
}

const EXPIRED_PAYLOAD = {
  identities: {
    expired_count: 2, expiring_count: 1, healthy_count: 3, unknown_count: 0,
    items: [
      {
        id: 'ident-1', name: 'researcher', health_state: 'expired',
        expires_at: '2026-10-27T00:00:00Z', refresh_expires_at: null,
        last_refresh_outcome: 'failure', last_refresh_at: null,
        remediation_target: 'agent_identity', remediation_path: '/agents/identities',
      },
    ],
  },
  mcp_sessions: {
    expired_count: 1, expiring_count: 3, healthy_count: 2, unknown_count: 0,
    items: [
      {
        id: 'mcp-1', name: 'github-session', health_state: 'expired',
        expires_at: '2026-10-26T00:00:00Z', refresh_expires_at: null,
        last_refresh_outcome: null, last_refresh_at: null,
        remediation_target: 'mcp_session', remediation_path: '/mcp',
      },
    ],
  },
  permission_flags: { identities: false, mcp_sessions: false },
}

const HEALTHY_PAYLOAD = {
  identities: {
    expired_count: 0, expiring_count: 0, healthy_count: 6, unknown_count: 0, items: [],
  },
  mcp_sessions: {
    expired_count: 0, expiring_count: 0, healthy_count: 6, unknown_count: 0, items: [],
  },
  permission_flags: { identities: false, mcp_sessions: false },
}

async function mockDashboard(page: Page, tokenHealth: unknown) {
  await page.route('http://localhost:8000/api/v1/dashboard/summary**', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(MOCK_DASHBOARD_SUMMARY),
    })
  )
  await page.route('http://localhost:8000/api/v1/dashboard/token-health', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify(tokenHealth),
    })
  )
}

test.describe.configure({ timeout: 60_000 })

test.describe('Token expiry — dashboard alerts & remediation', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await standardSetup(page)
  })

  test('dashboard shows separate expired indicators for identities and MCP sessions', async ({
    page,
  }) => {
    await mockDashboard(page, EXPIRED_PAYLOAD)
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    await expect(page.getByText('Token Health')).toBeVisible()
    const identitiesCard = page
      .getByText('Expired Agent Identity Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(identitiesCard).toContainText('2')

    const mcpCard = page
      .getByText('Expired MCP Session Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(mcpCard).toContainText('1')
  })

  test('expiring-within-7-days breakdown shows next to expired counts', async ({ page }) => {
    await mockDashboard(page, EXPIRED_PAYLOAD)
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    const identitiesCard = page
      .getByText('Expired Agent Identity Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(identitiesCard).toContainText('1 expiring within 7 days')

    const mcpCard = page
      .getByText('Expired MCP Session Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(mcpCard).toContainText('3 expiring within 7 days')
  })

  test('expired identity warning click-through lands on the agent identities page', async ({
    page,
  }) => {
    await mockDashboard(page, EXPIRED_PAYLOAD)
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    await page
      .getByText('Expired Agent Identity Tokens')
      .locator('xpath=ancestor::a[1]')
      .click()
    await expect(page).toHaveURL(/\/agents\/identities$/)
  })

  test('expired MCP session warning click-through lands on the MCP hub', async ({ page }) => {
    await mockDashboard(page, EXPIRED_PAYLOAD)
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    await page
      .getByText('Expired MCP Session Tokens')
      .locator('xpath=ancestor::a[1]')
      .click()
    await expect(page).toHaveURL(/\/mcp$/)
  })

  test('warnings disappear after remediation (refetch returns healthy)', async ({ page }) => {
    // First load: expired. After remediation (second fetch): all healthy.
    let tokenHealthCalls = 0
    await page.route('http://localhost:8000/api/v1/dashboard/summary**', (route) =>
      route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(MOCK_DASHBOARD_SUMMARY),
      })
    )
    await page.route('http://localhost:8000/api/v1/dashboard/token-health', (route) => {
      tokenHealthCalls += 1
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify(tokenHealthCalls <= 1 ? EXPIRED_PAYLOAD : HEALTHY_PAYLOAD),
      })
    })

    await page.goto('/dashboard')
    const identitiesCard = page
      .getByText('Expired Agent Identity Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(identitiesCard).toContainText('2')

    // Remediation happened (identity refreshed) — dashboard reload refetches.
    await page.reload()
    await expect(identitiesCard).toContainText('0')
    const mcpCard = page
      .getByText('Expired MCP Session Tokens')
      .locator('xpath=ancestor::*[contains(@class,"MuiCard-root")]')
    await expect(mcpCard).toContainText('0')
  })

  test('permission-denied placeholder renders instead of counts', async ({ page }) => {
    await mockDashboard(page, {
      identities: { expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [] },
      mcp_sessions: { expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [] },
      permission_flags: { identities: true, mcp_sessions: true },
    })
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // StatCard permission-denied placeholder (permissions.errors.accessDeniedTitle).
    await expect(page.getByText('Access Denied').first()).toBeVisible()
  })
})
