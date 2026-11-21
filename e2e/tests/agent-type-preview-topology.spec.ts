import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'

/**
 * Agent Type preview — unified panel topology canvas (unify-agent-topology-diagram).
 *
 * The agent preview dialog (`AgentTypeDetailsDialog` → "Agent Topology" tab) for
 * ALL agent types renders the SAME `PanelTopologyCanvas` used by the agent
 * management panel — zoned layout (① Configuration / ② Capabilities / ③ TOOLS),
 * the Communication Hub bar, empty-slot placeholders — fed by the pure
 * agent-type → draft mapping. Zoom (0.5×–3×, step 1.2) and node interaction
 * (entity view dialogs) work in the preview exactly as in the panel, and the
 * old divergent conversation-topology rendering is gone.
 *
 * The implementation plan lives on its own "Implementation Plan" tab (there is
 * no separate plan-preview modal and no "Agent Preview" tab any more).
 *
 * All backend traffic is mocked via `page.route()` per project convention —
 * no live backend needed.
 */

test.describe.configure({ timeout: 90_000 })

/**
 * Locates the agent-type details dialog. Its accessible name is the agent type
 * name (the DialogTitle renders it), so it is identified by its tab set.
 */
function agentDetailsDialog(page: Page) {
  return page
    .getByRole('dialog')
    .filter({ has: page.getByRole('tab', { name: 'Agent Topology' }) })
}

/**
 * Opens the agent-type details dialog from the Agent Types list (a row click
 * opens the dialog — there is no per-row View button) and switches to the
 * "Agent Topology" tab, where the unified canvas renders.
 */
async function openPreview(page: Page, agentName: string) {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  const row = page.getByRole('row').filter({ hasText: agentName })
  await expect(row).toBeVisible()
  await row.getByText(agentName, { exact: true }).click()

  const dialog = agentDetailsDialog(page)
  await expect(dialog.getByRole('tab', { name: 'Agent Topology' })).toBeVisible()
  await dialog.getByRole('tab', { name: 'Agent Topology' }).click()
  return true
}

test.describe('Agent Type preview — unified panel topology canvas', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockPanelWorld(page)
  })

  test('preview shows the unified zoned panel topology canvas with hub bar', async ({
    page,
  }) => {
    if (!(await openPreview(page, 'panel-e2e-conv'))) return

    const dialog = agentDetailsDialog(page)
    const canvas = dialog.getByTestId('panel-topology-canvas')
    await expect(canvas).toBeVisible()

    // Zoned composition identical to the panel: role node (Capabilities zone),
    // the composed SOP skill tree, the routed tool, and the ③ TOOLS zone.
    await expect(canvas.getByText('panel-e2e-role')).toBeVisible()
    await expect(canvas.getByText('panel-e2e-sop', { exact: true })).toBeVisible()
    await expect(canvas.getByText('panel-e2e-sop-skill')).toBeVisible()
    await expect(canvas.getByText('panel____search')).toBeVisible()
    await expect(canvas.getByText('③ TOOLS')).toBeVisible()

    // The Communication Hub renders as the vertical hub BAR (not the old
    // divergent preview's dashed "platform messaging" conversation edge).
    await expect(canvas.getByText('Communication Hub')).toBeVisible()
    await expect(canvas.getByText('platform messaging')).toHaveCount(0)
    await expect(canvas.getByText('executes via')).toHaveCount(0)

    // Empty-slot placeholders appear for unequipped slots (conv agent has no
    // identity, model, or data types).
    await expect(canvas.getByText('Identity (empty)')).toBeVisible()

    // No stale typed/plan branch content — this is the panel canvas.
    await expect(dialog.getByTestId('no-plan')).toHaveCount(0)
  })

  test('zoom controls work in the preview fullscreen (parity with panel)', async ({
    page,
  }) => {
    if (!(await openPreview(page, 'panel-e2e-conv'))) return

    const dialog = agentDetailsDialog(page)
    const canvas = dialog.getByTestId('panel-topology-canvas')
    await expect(canvas.getByText('panel-e2e-role')).toBeVisible()

    // Enter fullscreen via the canvas header toggle (same control as panel).
    await dialog.getByTestId('panel-topology-fullscreen').click()

    // Auto-fit on enter: zoom level reads 100%, whole graph visible.
    const overlay = page.getByTestId('panel-topology-fullscreen-overlay')
    await expect(overlay).toBeVisible()
    await expect(overlay.getByText('③ TOOLS')).toBeVisible()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Zoom in/out steps by the panel's factor (1.2 → 120%).
    await page.getByTestId('panel-topology-zoom-in').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('120%')
    await page.getByTestId('panel-topology-zoom-out').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Fit returns to auto-fit and disables at zoom 1.
    await page.getByTestId('panel-topology-zoom-in').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('120%')
    await page.getByTestId('panel-topology-zoom-fit').click()
    await expect(page.getByTestId('panel-topology-zoom-level')).toHaveText('100%')

    // Exit returns to the inline canvas inside the dialog.
    await page.getByTestId('panel-topology-fullscreen-exit').click()
    await expect(page.getByTestId('panel-topology-fullscreen-overlay')).toHaveCount(0)
    await expect(canvas.getByText('panel-e2e-role')).toBeVisible()
  })

  test('clicking a topology node opens the entity view dialog', async ({ page }) => {
    if (!(await openPreview(page, 'panel-e2e-conv'))) return

    const dialog = agentDetailsDialog(page)
    const canvas = dialog.getByTestId('panel-topology-canvas')
    await expect(canvas.getByText('panel-e2e-role')).toBeVisible()

    // Click the role node in the preview topology → the role view dialog
    // opens (same interaction contract as the panel's detail bubble).
    await canvas.getByText('panel-e2e-role').click()

    await expect(page.getByRole('dialog', { name: 'Agent Role' })).toBeVisible()
  })
})

test.describe('Agent Type preview — regression of untouched branches', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
  })

  test('typed agents also get the unified canvas; plan steps kept, plan topology removed', async ({
    page,
  }) => {
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

    if (!(await openPreview(page, 'panel-e2e-plan-agent'))) return

    const dialog = agentDetailsDialog(page)
    // Unified zoned panel canvas renders for typed agents too (fed by the
    // agent-type → draft mapping, not the plan's topology nodes).
    const canvas = dialog.getByTestId('panel-topology-canvas')
    await expect(canvas.getByText('panel-e2e-role')).toBeVisible()
    await expect(canvas.getByText('③ TOOLS')).toBeVisible()
    await expect(canvas.getByText('Communication Hub')).toBeVisible()
    // The old plan-topology branch content must NOT appear.
    await expect(canvas.getByText('platform messaging')).toHaveCount(0)

    // Plan steps are still kept on the Implementation Plan tab.
    await dialog.getByRole('tab', { name: 'Implementation Plan' }).click()
    await expect(dialog.getByText('Do the thing')).toBeVisible()
  })
})
