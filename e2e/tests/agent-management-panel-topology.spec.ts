import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import {
  mockPanelWorld,
  seedAgents,
  type PanelWorldState,
} from './_agent_panel_world'

/**
 * Agent Management Panel — live topology behaviours.
 *
 *  - The panel topology is composed purely client-side from the draft: every
 *    assign/unassign re-renders it immediately with ZERO network requests
 *    (asserted via a request observer on every /api/v1 route).
 *  - Switching agents re-renders the topology for that agent's saved state.
 *  - The Communication Hub node (dashed "platform messaging" edge) appears in
 *    the panel topology AND in the existing agent preview topology of the
 *    Agent Types view (AgentTypeDetailsDialog → Agent Preview tab), for both
 *    the conversational branch and the typed/plan branch (AgentPlanContent).
 */

test.describe.configure({ timeout: 90_000 })

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

test.describe('Agent Management Panel — live topology', () => {
  let state: PanelWorldState

  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    state = await mockPanelWorld(page)
  })

  test('panel topology renders every equipped node plus the Communication Hub', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    const svg = page.getByLabel('Agent Topology')
    // Agent node + equipped role / SOP / skill nodes (labels resolved from
    // the shared caches) and the model node (long label is width-fitted and
    // truncated with an ellipsis by the renderer; the full text lives on the
    // node's native <title>, which never carries the ellipsis — the regexes
    // below require it so they match the visible <text> only).
    await expect(svg.getByText('panel-e2e-alpha')).toBeVisible()
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
    // exact: the composed "panel-e2e-sop-skill" node contains this text too.
    await expect(svg.getByText('panel-e2e-sop', { exact: true })).toBeVisible()
    await expect(svg.getByText('panel-e2e-skill')).toBeVisible()
    await expect(svg.getByText(/gpt-4o \(Panel E2E G…/)).toBeVisible()
    // SOP composition chain: the bound SOP composes skill-p2
    // ("panel-e2e-sop-skill") via its detail's skill_invocation step — the
    // composed skill renders beneath its SOP and routes its tool
    // ("panel____search") across the Hub like any directly bound skill.
    await expect(svg.getByText('panel-e2e-sop-skill')).toBeVisible()
    await expect(svg.getByText('panel____search')).toBeVisible()
    // Empty slots render dashed placeholder nodes.
    await expect(svg.getByText('Identity (empty)')).toBeVisible()
    await expect(svg.getByText(/Input Data Type \(e.*…/)).toBeVisible()
    await expect(svg.getByText(/Output Data Type \(e.*…/)).toBeVisible()
    // Communication Hub renders as a vertical bar between Capabilities and
    // Tools (zone ③ renamed from Runtime) — no "executes via" fan edge.
    await expect(svg.getByText('Communication Hub')).toBeVisible()
    await expect(svg.getByText('③ TOOLS')).toBeVisible()
    await expect(svg.getByText('executes via')).toHaveCount(0)

    // Localized zoned edge-semantics legend ("call path via Hub" chip is
    // used nowhere else in the app).
    await expect(page.getByText('call path via Hub')).toBeVisible()
    // LIVE indicator.
    await expect(page.getByText('LIVE', { exact: true })).toBeVisible()
  })

  test('fullscreen topology auto-fits and supports zoom controls', async ({ page }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    const svg = page.getByLabel('Agent Topology')
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()

    // Enter fullscreen via the header toggle.
    await page.getByLabel('Expand topology to full screen').click()

    // Auto-fit: the whole graph is visible — the tools zone (right-most,
    // previously clipped at the bottom/side on small windows) renders inside
    // the bounded svg (preserveAspectRatio meet).
    const fullscreenSvg = page.getByTestId('panel-topology-fullscreen-overlay').getByLabel('Agent Topology')
    await expect(fullscreenSvg).toBeVisible()
    await expect(fullscreenSvg).toHaveAttribute('preserveAspectRatio', 'xMidYMid meet')
    await expect(fullscreenSvg.getByText('③ TOOLS')).toBeVisible()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Zoom in / out steps the % readout.
    await page.getByTestId('panel-topology-zoom-in').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('120%')
    await page.getByTestId('panel-topology-zoom-out').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Fit returns to auto-fit (the button disables at zoom 1).
    await page.getByTestId('panel-topology-zoom-in').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('120%')
    await page.getByTestId('panel-topology-zoom-fit').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Exit returns to the inline canvas.
    await page.getByLabel('Exit full screen').click()
    await expect(page.getByTestId('panel-topology-fullscreen-overlay')).toHaveCount(0)
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
  })

  test('topology updates immediately on draft mutations with zero network requests', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    const svg = page.getByLabel('Agent Topology')
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
    // The async SOP-detail fetch (composition chain) also settles before the
    // observation window opens — the composed skill only renders after it.
    await expect(svg.getByText('panel-e2e-sop-skill')).toBeVisible()

    // Observe all traffic from here on.
    state.requests.length = 0

    // Unassign the role → placeholder node appears instantly.
    await slot(page, 'Role').getByLabel('Remove').click()
    await expect(svg.getByText('Role (empty)')).toBeVisible()
    await expect(svg.getByText('panel-e2e-role')).toBeHidden()

    // Re-assign via assign-existing → real node returns instantly.
    const roleSlot = slot(page, 'Role')
    await roleSlot.getByRole('button', { name: 'Assign existing' }).click()
    await roleSlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'panel-e2e-role' }).click()
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
    await expect(svg.getByText('Role (empty)')).toBeHidden()

    // NOTHING was sent to the backend — the "see exactly what I am about to
    // persist" guarantee (no save, not even a refetch).
    expect(state.requests).toEqual([])
    expect(state.agentPutBodies).toHaveLength(0)
  })

  test('switching agents re-renders the topology for that agent after the unsaved-changes guard', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    // Alpha: fully equipped (real skill/SOP nodes).
    await selectAgent(page, 'panel-e2e-alpha')
    const svg = page.getByLabel('Agent Topology')
    await expect(svg.getByText('panel-e2e-skill')).toBeVisible()

    // Dirty the draft, then switch — the guard must appear.
    await slot(page, 'Role').getByLabel('Remove').click()
    await expect(page.getByText('unsaved changes')).toBeVisible()
    await page.getByRole('button', { name: 'panel-e2e-beta' }).click()
    await expect(page.getByRole('dialog').getByText('Discard unsaved changes?')).toBeVisible()
    await page
      .getByRole('dialog')
      .getByRole('button', { name: 'Discard', exact: true })
      .click()

    // Beta's topology reflects its SAVED state: role only — the empty Skills
    // section is omitted entirely (no placeholder node, no group frame), the
    // SOPs section keeps its empty placeholder, and alpha's skill node is gone.
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
    await expect(svg.getByText('Skills (empty)')).toHaveCount(0)
    await expect(svg.getByText('SOPs (empty)')).toBeVisible()
    await expect(svg.getByText('panel-e2e-skill')).toBeHidden()
    // Hub present on every topology.
    await expect(svg.getByText('Communication Hub')).toBeVisible()
  })

  test('discarded draft changes do not leak when switching agents and back', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-beta')

    const svg = page.getByLabel('Agent Topology')
    // Beta has no model — assign one (draft-only).
    const modelSlot = slot(page, 'Model')
    await modelSlot.getByRole('button', { name: 'Assign existing' }).click()
    await modelSlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()
    // Truncated model label appears (the full text is on the node's <title>,
    // which lacks the ellipsis — the regex matches the visible text only).
    await expect(svg.getByText(/gpt-4o \(Panel E2E G…/)).toBeVisible()

    // Switch away — the guard fires because the draft is dirty; discard it.
    await page.getByRole('button', { name: 'panel-e2e-alpha' }).click()
    await expect(page.getByRole('dialog').getByText('Discard unsaved changes?')).toBeVisible()
    await page
      .getByRole('dialog')
      .getByRole('button', { name: 'Discard', exact: true })
      .click()
    await expect(page.getByRole('heading', { name: 'panel-e2e-alpha', exact: true })).toBeVisible()

    // Switch back to beta (both pristine now — no guard).
    await page.getByRole('button', { name: 'panel-e2e-beta' }).click()
    await expect(page.getByRole('heading', { name: 'panel-e2e-beta', exact: true })).toBeVisible()

    // The unsaved model assignment was discarded on switch: beta shows the
    // empty model placeholder again, and nothing was persisted.
    await expect(svg.getByText(/gpt-4o/)).toHaveCount(0)
    await expect(svg.getByText('Model (empty)')).toBeVisible()
    expect(state.agentPutBodies).toHaveLength(0)
  })
})

test.describe('Agent Management Panel — Communication Hub in existing preview topologies', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
  })

  test('Agent Types details dialog shows the hub in a conversational agent preview topology', async ({
    page,
  }) => {
    await mockPanelWorld(page)
    await page.goto('/agents')
    await page.waitForLoadState('load')
    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    const row = page.getByRole('row').filter({ hasText: 'panel-e2e-conv' })
    await expect(row).toBeVisible()
    await row.getByLabel('View').click()

    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('tab', { name: 'Agent Preview' })).toBeVisible()
    await dialog.getByRole('tab', { name: 'Agent Preview' }).click()

    const svg = dialog.getByLabel('Agent Topology')
    await expect(svg.getByText('Communication Hub')).toBeVisible()
    await expect(svg.getByText('platform messaging')).toBeVisible()
    // The agent's role resolves into the preview topology as well.
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
  })

  test('Agent Types details dialog shows the hub in a typed agent plan preview topology', async ({
    page,
  }) => {
    // Typed agent whose persisted plan already carries topology nodes — the
    // hub is appended client-side at render time (AgentPlanContent).
    const withPlan = seedAgents().map((a) =>
      a.id === 'at-a'
        ? {
            ...a,
            name: 'panel-e2e-plan-agent',
            input_type: 'typed' as const,
            plan: {
              id: 'plan-a',
              agent_type_id: 'at-a',
              generation_status: 'completed',
              generation_error: null,
              agent_config_hash: null,
              generated_at: '2026-06-01T00:00:00Z',
              plan_steps: [
                { order: 1, type: 'skill_invocation', name: 'Do the thing', description: null },
              ],
              topology_nodes: [
                { id: 'agent', type: 'agent', label: 'panel-e2e-plan-agent' },
                { id: 'role', type: 'role', label: 'panel-e2e-role' },
              ],
              topology_edges: [{ source: 'agent', target: 'role' }],
            },
          }
        : a,
    )
    await mockPanelWorld(page, { agents: withPlan })

    await page.goto('/agents')
    await page.waitForLoadState('load')
    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    const row = page.getByRole('row').filter({ hasText: 'panel-e2e-plan-agent' })
    await expect(row).toBeVisible()
    await row.getByLabel('View').click()

    const dialog = page.getByRole('dialog')
    await dialog.getByRole('tab', { name: 'Agent Preview' }).click()

    const svg = dialog.getByLabel('Agent Topology')
    // Plan topology nodes render, plus the client-appended hub node + edge.
    await expect(svg.getByText('panel-e2e-plan-agent')).toBeVisible()
    await expect(svg.getByText('panel-e2e-role')).toBeVisible()
    await expect(svg.getByText('Communication Hub')).toBeVisible()
    await expect(svg.getByText('platform messaging')).toBeVisible()
    // Hub is present exactly once (helper idempotence in the rendered graph).
    await expect(svg.getByText('Communication Hub')).toHaveCount(1)
  })
})
