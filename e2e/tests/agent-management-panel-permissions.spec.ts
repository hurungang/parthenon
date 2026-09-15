import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, type PanelWorldState } from './_agent_panel_world'

/**
 * Agent Management Panel — permission gating / graceful degradation.
 *
 * Uses `page.route` 403 mocks with the platform's structured permission
 * payload (`detail.required_permission`) exactly as the backend emits it:
 *  - a 403 on a slot's backing list query degrades that slot: localized
 *    explanation instead of an error surface, actions disabled/hidden;
 *  - a 403 on the agent list degrades the sidebar via PermissionDeniedAlert
 *    while the rest of the shell keeps working (read-only browsing);
 *  - a 403 on the draft save surfaces the error inside the pending-changes
 *    tray per the Dialog Error Handling Standard and keeps the draft dirty.
 * 403s must NEVER trigger the auth redirect (that is 401-only behaviour).
 */

test.describe.configure({ timeout: 90_000 })

function forbidden(resourceType: string, action = 'read') {
  return {
    status: 403,
    contentType: 'application/json',
    body: JSON.stringify({
      detail: {
        required_permission: { resource_type: resourceType, action, resource_id: null },
      },
    }),
  }
}

async function gotoPanel(page: Page) {
  await page.goto('/agents/panel')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()
  return true
}

function slot(page: Page, label: string) {
  return page.locator('.MuiPaper-outlined').filter({
    has: page.getByText(label, { exact: true }),
  })
}

async function selectAgent(page: Page, name: string) {
  await page.getByRole('button', { name }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}

test.describe('Agent Management Panel — permissions', () => {
  let state: PanelWorldState

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    state = await mockPanelWorld(page)
  })

  test('403 on the roles list disables only the role slot with a localized explanation', async ({
    page,
  }) => {
    // Higher-priority override (registered after the world): roles denied.
    await page.route(/\/api\/v1\/agents\/roles(\?.*)?$/, (route) => route.fulfill(forbidden('agent::roles')))

    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    // Role slot degrades: explanation + no write actions.
    const roleSlot = slot(page, 'Role')
    await expect(
      roleSlot.getByText(/lacks permission for this module \(agent::roles\)/),
    ).toBeVisible()
    await expect(roleSlot.getByRole('button', { name: 'Assign existing' })).toHaveCount(0)
    await expect(roleSlot.getByRole('button', { name: 'Create new' })).toHaveCount(0)

    // Every other slot keeps working (skills shown as example).
    const skillsSlot = slot(page, 'Skills')
    await expect(skillsSlot.getByRole('button', { name: 'Assign existing' })).toBeVisible()
    await expect(skillsSlot.getByText('panel-e2e-skill')).toBeVisible()

    // Degradation is silent for the rest of the panel — no error alert.
    await expect(page.getByText('Permission Denied:')).toHaveCount(0)
  })

  test('403 on the agent list degrades the sidebar gracefully and keeps the session', async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/agents\/types(\?.*)?$/, (route) => route.fulfill(forbidden('agent::types')))

    if (!(await gotoPanel(page))) return

    // Sidebar renders the structured permission alert — not a crash, not a
    // redirect to /login.
    await expect(page.getByText('Permission Denied:').first()).toBeVisible()
    await expect(page.getByText('agent::types').first()).toBeVisible()
    expect(page.url()).not.toContain('/login')
    await expect(page.getByRole('button', { name: 'Create Agent' })).toBeVisible()

    // Topology region shows the empty-selection prompt.
    await expect(
      page.getByText('Select an agent to view and equip its configuration').first(),
    ).toBeVisible()
  })

  test('read-only browsing: all slot lists denied — compositions stay viewable, no write actions', async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/agents\/roles(\?.*)?$/, (route) => route.fulfill(forbidden('agent::roles')))
    await page.route(/\/api\/v1\/agents\/identities(\?.*)?$/, (route) =>
      route.fulfill(forbidden('agent::identities')),
    )
    await page.route(/\/api\/v1\/skills(\?.*)?$/, (route) => route.fulfill(forbidden('agent::skills')))
    await page.route(/\/api\/v1\/sops(\?.*)?$/, (route) => route.fulfill(forbidden('agent::sops')))
    await page.route(/\/api\/v1\/data-types(\?.*)?$/, (route) =>
      route.fulfill(forbidden('agent::data_types')),
    )
    await page.route(/\/api\/v1\/agents\/model-configs(\?.*)?$/, (route) =>
      route.fulfill(forbidden('agent::model_configs')),
    )

    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    // All seven slots explain themselves instead of erroring.
    for (const label of [
      'Role',
      'Identity',
      'Skills',
      'SOPs',
      'Input Data Type',
      'Output Data Type',
      'Model',
    ]) {
      await expect(slot(page, label).getByText(/lacks permission for this module/)).toBeVisible()
    }
    // No write actions anywhere.
    await expect(page.getByRole('button', { name: 'Create new' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Assign existing' })).toHaveCount(0)

    // Read-only browsing still works: composition viewable in the topology
    // (built client-side from the fetched agent configuration).
    const svg = page.getByLabel('Agent Topology')
    await expect(svg.getByText('panel-e2e-alpha')).toBeVisible()
    await expect(svg.getByText('Communication Hub')).toBeVisible()
    await expect(page.getByText('LIVE', { exact: true })).toBeVisible()
  })

  test('403 on save surfaces the error in the pending-changes tray and keeps the draft dirty', async ({
    page,
  }) => {
    await page.route(/\/api\/v1\/agents\/types\/[^/]+(\?.*)?$/, (route) => {
      if (route.request().method() === 'PUT') {
        return route.fulfill(forbidden('agent::types', 'update'))
      }
      return route.fallback()
    })

    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    // Dirty the draft: remove the role assignment.
    await slot(page, 'Role').getByLabel('Remove').click()
    await expect(page.getByText('unsaved changes')).toBeVisible()

    // Save → 403 → error surfaced inside the tray area.
    await page.getByRole('button', { name: 'Save Changes' }).click()
    await expect(page.getByText('Permission Denied:')).toBeVisible()
    await expect(page.getByText('agent::types').first()).toBeVisible()

    // Draft remains dirty and intact — no partial write, chip unchanged.
    await expect(page.getByText('unsaved changes')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()
    const svg = page.getByLabel('Agent Topology')
    await expect(svg.getByText('Role (empty)')).toBeVisible()
    expect(state.agentPutBodies).toHaveLength(0)
  })
})
