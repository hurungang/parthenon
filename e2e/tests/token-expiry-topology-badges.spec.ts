import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import {
  mockPanelWorld,
  PANEL_IDENTITY,
  seedAgents,
  type PanelWorldState,
} from './_agent_panel_world'

/**
 * Token Expiry Alerting — topology badges on the unified agent topology
 * canvas. All API calls are mocked (no live backend needed).
 *
 *  - A container whose identity is EXPIRED renders an error badge.
 *  - A container whose identity is EXPIRING (≤7 days) renders a warning badge.
 *  - Healthy/unknown identities render no badge.
 *  - Older payloads without health enrichment render without errors.
 *
 * Badges are carried by the topology SVG nodes:
 *   [data-testid=topology-token-badge-<nodeId>][data-token-health=…]
 */

test.describe.configure({ timeout: 90_000 })

function tokenHealthPayload(identityState: 'expired' | 'expiring' | 'healthy') {
  const items =
    identityState === 'healthy'
      ? []
      : [
          {
            id: PANEL_IDENTITY.id,
            name: PANEL_IDENTITY.name,
            health_state: identityState,
            expires_at: '2026-10-28T00:00:00Z',
            refresh_expires_at: null,
            last_refresh_outcome: null,
            last_refresh_at: null,
            remediation_target: 'agent_identity',
            remediation_path: '/agents/identities',
          },
        ]
  return {
    identities: {
      expired_count: identityState === 'expired' ? 1 : 0,
      expiring_count: identityState === 'expiring' ? 1 : 0,
      healthy_count: identityState === 'healthy' ? 1 : 0,
      unknown_count: 0,
      items,
    },
    mcp_sessions: {
      expired_count: 0, expiring_count: 0, healthy_count: 0, unknown_count: 0, items: [],
    },
    permission_flags: { identities: false, mcp_sessions: false },
  }
}

async function setup(page: Page, identityState: 'expired' | 'expiring' | 'healthy') {
  const errors: string[] = []
  page.on('pageerror', (err) => errors.push(err.message))
  await mockApiCatchAllProxyAware(page)
  await page.addInitScript((token: string) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
  await standardSetup(page)
  // Alpha agent is bound to the (health-state) identity under test.
  const agents = seedAgents()
  agents[0] = { ...agents[0], identity_id: PANEL_IDENTITY.id }
  const state = await mockPanelWorld(page, { agents })
  await page.route('http://localhost:8000/api/v1/dashboard/token-health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(tokenHealthPayload(identityState)),
    })
  )
  return { state, errors }
}

async function gotoPanel(page: Page) {
  await page.goto('/agents/panel')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  await expect(
    page.getByRole('heading', { name: 'Agent Management Panel' })
  ).toBeVisible()
  // Select the agent bound to the identity under test.
  await page.getByRole('button', { name: 'panel-e2e-alpha' }).click()
  await expect(
    page.getByRole('heading', { name: 'panel-e2e-alpha', exact: true })
  ).toBeVisible()
  return true
}

test.describe('Token expiry — topology badges', () => {
  test('expired identity renders an error badge on its container', async ({ page }) => {
    const { errors } = await setup(page, 'expired')
    if (!(await gotoPanel(page))) return

    const badge = page.locator(
      '[data-testid="topology-token-badge-identity"]'
    )
    await expect(badge).toHaveAttribute('data-token-health', 'expired')
  })

  test('expiring identity renders a warning badge on its container', async ({ page }) => {
    const { errors } = await setup(page, 'expiring')
    if (!(await gotoPanel(page))) return

    const badge = page.locator(
      '[data-testid="topology-token-badge-identity"]'
    )
    await expect(badge).toHaveAttribute('data-token-health', 'expiring')
  })

  test('healthy identity renders no badge and the topology still renders', async ({
    page,
  }) => {
    const { errors } = await setup(page, 'healthy')
    if (!(await gotoPanel(page))) return

    await expect(
      page.locator('[data-testid="topology-token-badge-identity"]')
    ).toHaveCount(0)
  })

  test('older payload without health enrichment renders without errors', async ({ page }) => {
    const { errors } = await setup(page, 'healthy')
    // Override with the legacy empty-object payload (no health enrichment).
    await page.route('http://localhost:8000/api/v1/dashboard/token-health', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    )
    if (!(await gotoPanel(page))) return

    await expect(
      page.locator('[data-testid^="topology-token-badge-"]')
    ).toHaveCount(0)
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })
})
