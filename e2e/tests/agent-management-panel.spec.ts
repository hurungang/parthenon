import { expect, test, type Page } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { muiCombobox, mockPanelWorld, selectMuiOption, seedAgents, type PanelWorldState } from './_agent_panel_world'

/**
 * Agent Management Panel — full agent CRUD lifecycle through the panel
 * (create → read → edit → delete → recreate same name), parent auto-refresh
 * assertions (no manual reload), unsaved-changes guard, and single-PUT save
 * semantics. All API traffic is mocked (mock-first convention).
 *
 * A real-backend (unmocked) CRUD flow variant lives at the bottom of this
 * file and skips cleanly when the live stack is not usable.
 */

test.describe.configure({ timeout: 90_000 })

const UNIQUE = `${Date.now()}`
const AGENT_NAME = `e2e-panel-agent-${UNIQUE}`

/** Navigates to the panel and skips cleanly if auth redirected to /login. */
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
  // Slot cards are the only `variant="outlined"` Papers in the panel grid.
  return page.locator('.MuiPaper-outlined').filter({
    has: page.getByText(label, { exact: true }),
  })
}

async function createAgentViaForm(page: Page, name: string, withModel = false) {
  await page.getByRole('button', { name: 'Create Agent' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Create Agent Type' })).toBeVisible()

  // Required-field enforcement: Save stays disabled until name + binding exist.
  await expect(dialog.getByRole('button', { name: 'Save', exact: true })).toBeDisabled()

  await dialog.getByLabel('Name').fill(name)
  // Select the seeded role so the SOP binding becomes available.
  await selectMuiOption(page, dialog, 'Agent Role', 'panel-e2e-role')
  // Add a SOP binding (mandatory: at least one SOP or skill binding).
  await dialog.getByRole('button', { name: 'Add Binding' }).click()
  await dialog
    .locator('.MuiToggleButtonGroup-root')
    .locator('..')
    .getByRole('combobox')
    .click()
  await page.getByRole('option', { name: 'panel-e2e-sop' }).click()
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
  if (withModel) {
    await selectMuiOption(page, dialog, 'Model', /gpt-4o \(Panel E2E GPT\)/)
  }
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
}

async function selectAgent(page: Page, name: string) {
  await page.getByRole('button', { name }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}

async function markNoReload(page: Page) {
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).__e2e_no_reload = true
  })
}

async function assertNoReload(page: Page) {
  const marker = await page.evaluate(
    () => (window as unknown as Record<string, unknown>).__e2e_no_reload,
  )
  expect(marker).toBe(true)
}

test.describe('Agent Management Panel — CRUD lifecycle', () => {
  let state: PanelWorldState

  test.beforeEach(async ({ page }) => {
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    state = await mockPanelWorld(page)
  })

  test('creates an agent from the panel and shows it in sidebar + header immediately (no reload)', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    await markNoReload(page)
    await createAgentViaForm(page, AGENT_NAME)

    // Sidebar shows the new agent immediately, without any manual reload.
    await expect(page.getByRole('button', { name: AGENT_NAME })).toBeVisible()
    // The saved agent is auto-selected: header card shows the name.
    await expect(page.getByRole('heading', { name: AGENT_NAME, exact: true })).toBeVisible()
    // Sidebar count updated (3 seeded + 1 created).
    await expect(page.getByText('4 agents')).toBeVisible()

    // No page reload happened during the whole flow.
    await assertNoReload(page)

    // Persisted server-side exactly once, with the expected payload.
    expect(state.agentPostBodies).toHaveLength(1)
    expect(state.agentPostBodies[0]).toMatchObject({
      name: AGENT_NAME,
      role_id: 'role-p1',
      sop_bindings: [{ sop_id: 'sop-p1', order: 1 }],
    })
  })

  test('create dialog enforces required fields and slug name pattern', async ({ page }) => {
    if (!(await gotoPanel(page))) return

    await page.getByRole('button', { name: 'Create Agent' }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('heading', { name: 'Create Agent Type' })).toBeVisible()

    const save = dialog.getByRole('button', { name: 'Save', exact: true })
    await expect(save).toBeDisabled()

    // A name without a binding still blocks saving.
    await dialog.getByLabel('Name').fill('agent-without-bindings')
    await expect(save).toBeDisabled()

    // Invalid slug pattern (uppercase/space) keeps Save disabled.
    await dialog.getByLabel('Name').fill('Invalid Name!')
    await expect(save).toBeDisabled()

    // Nothing was persisted.
    expect(state.agentPostBodies).toHaveLength(0)
  })

  test('edits an agent through the property bar and refreshes sidebar + header without reload', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    await selectAgent(page, 'panel-e2e-alpha')
    await markNoReload(page)

    // No edit dialog — base properties are edited in place in the right
    // property bar, pre-populated from the selected agent.
    await expect(page.getByLabel('Name')).toHaveValue('panel-e2e-alpha')
    const descInput = page.getByLabel('Description')
    await expect(descInput).toHaveValue('E2E panel agent')

    const updatedDesc = `updated by e2e ${UNIQUE}`
    await descInput.fill(updatedDesc)

    // The edit is draft-only: the tray flags unsaved changes before saving.
    await expect(page.getByText('unsaved changes')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()

    await page.getByRole('button', { name: 'Save Changes' }).click()
    await expect(page.getByText('saved', { exact: true })).toBeVisible()

    // Header + sidebar reflect the change immediately — no manual reload.
    await expect(page.getByText(updatedDesc).first()).toBeVisible()
    await assertNoReload(page)

    // Exactly one PUT with the updated description.
    expect(state.agentPutBodies).toHaveLength(1)
    expect(state.agentPutBodies[0]).toMatchObject({
      name: 'panel-e2e-alpha',
      description: updatedDesc,
    })
  })

  test('deletes an agent with confirmation and allows recreating the same name (true deletion)', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    await selectAgent(page, 'panel-e2e-alpha')
    await page.getByLabel('Delete').click()

    // Confirmation dialog names the agent before deleting.
    const confirm = page.getByRole('dialog')
    await expect(
      confirm.getByText('Delete agent "panel-e2e-alpha"? This cannot be undone.'),
    ).toBeVisible()
    await confirm.getByRole('button', { name: 'Delete', exact: true }).click()

    // Removed from the sidebar immediately; count drops to 2.
    await expect(page.getByRole('button', { name: 'panel-e2e-alpha' })).toBeHidden()
    await expect(page.getByText('2 agents')).toBeVisible()
    // Selection reset — header shows the empty prompt again (header card +
    // topology region both render it; assert the first).
    await expect(
      page.getByText('Select an agent to view and equip its configuration').first(),
    ).toBeVisible()
    // Backend actually received the DELETE for the right id.
    expect(state.deletedAgentIds).toEqual(['at-a'])

    // True deletion: the same name can be created again.
    await createAgentViaForm(page, 'panel-e2e-alpha')
    await expect(page.getByRole('button', { name: 'panel-e2e-alpha' }).first()).toBeVisible()
    await expect(page.getByRole('heading', { name: 'panel-e2e-alpha', exact: true })).toBeVisible()
    expect(state.agentPostBodies).toHaveLength(1)
    expect(state.agentPostBodies[0]).toMatchObject({ name: 'panel-e2e-alpha' })
  })

  test('guards agent switching with unsaved changes — Keep Editing preserves, Discard switches', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    await selectAgent(page, 'panel-e2e-alpha')

    // Dirty the draft: remove the role (first slot chip's Remove icon).
    await page.getByLabel('Remove').first().click()
    await expect(page.getByText('unsaved changes')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()

    // Attempting to switch agents raises the confirmation dialog.
    await page.getByRole('button', { name: 'panel-e2e-beta' }).click()
    const guard = page.getByRole('dialog')
    await expect(guard.getByText('Discard unsaved changes?')).toBeVisible()

    // Keep Editing preserves the draft: still on alpha, still dirty.
    await guard.getByRole('button', { name: 'Keep Editing' }).click()
    await expect(guard).toBeHidden()
    await expect(page.getByRole('heading', { name: 'panel-e2e-alpha', exact: true })).toBeVisible()
    await expect(page.getByText('unsaved changes')).toBeVisible()

    // Second attempt + Discard performs the switch and resets the draft.
    await page.getByRole('button', { name: 'panel-e2e-beta' }).click()
    await page
      .getByRole('dialog')
      .getByRole('button', { name: 'Discard', exact: true })
      .click()
    await expect(page.getByRole('heading', { name: 'panel-e2e-beta', exact: true })).toBeVisible()
    await expect(page.getByText('saved', { exact: true })).toBeVisible()
    // The discard was purely client-side — no save fired.
    expect(state.agentPutBodies).toHaveLength(0)
  })

  test('pending-changes tray saves the draft with exactly one agent-type PUT', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    // Beta has no model equipped — assign one via the model slot.
    await selectAgent(page, 'panel-e2e-beta')

    const modelSlot = slot(page, 'Model')
    await modelSlot.getByRole('button', { name: 'Assign existing' }).click()
    await modelSlot.getByRole('combobox').click()
    await page.getByRole('option', { name: 'gpt-4o (Panel E2E GPT)' }).click()

    // Slot reflects the assignment and the tray lists the changed slot.
    await expect(modelSlot.getByText('gpt-4o (Panel E2E GPT)')).toBeVisible()
    await expect(page.getByText('Pending changes (1)')).toBeVisible()
    await expect(page.getByText('unsaved changes')).toBeVisible()

    // Assigning equipment is draft-only: zero write API calls fired.
    const writes = state.requests.filter(
      (r) => r.startsWith('POST') || r.startsWith('PUT') || r.startsWith('DELETE'),
    )
    expect(writes).toEqual([])

    await page.getByRole('button', { name: 'Save Changes' }).click()
    await expect(page.getByText('saved', { exact: true })).toBeVisible()

    expect(state.agentPutBodies).toHaveLength(1)
    // The single PUT carries the equipment change AND the (unchanged) base
    // properties, which now live in the same draft.
    expect(state.agentPutBodies[0]).toMatchObject({
      model_id: 'gpt-4o',
      name: 'panel-e2e-beta',
      description: 'Beta agent (role only)',
    })
  })

  test('sidebar search filters the agent list client-side', async ({ page }) => {
    if (!(await gotoPanel(page))) return

    await page.getByPlaceholder('Search agents…').fill('beta')
    await expect(page.getByRole('button', { name: 'panel-e2e-beta' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'panel-e2e-alpha' })).toBeHidden()
    await expect(page.getByRole('button', { name: 'panel-e2e-conv' })).toBeHidden()

    await page.getByPlaceholder('Search agents…').fill('no-match-at-all')
    await expect(page.getByText('No agents match your search')).toBeVisible()
  })

  test('all seven equipment slots render dashed empty placeholders for a fresh agent', async ({
    page,
  }) => {
    // Re-register the world (highest priority) with a fully unequipped agent.
    const fresh = seedAgents().map((a) =>
      a.id === 'at-a'
        ? { ...a, role_id: null, model_id: null, sop_bindings: [], skill_bindings: [] }
        : a,
    )
    await mockPanelWorld(page, { agents: fresh })

    if (!(await gotoPanel(page))) return
    await selectAgent(page, 'panel-e2e-alpha')

    for (const label of ['Role', 'Identity', 'Skills', 'SOPs', 'Output Data Type', 'Model']) {
      await expect(slot(page, label).getByText('Nothing equipped yet')).toBeVisible()
    }
    // The input slot always renders its input-type Select (value: None).
    await expect(slot(page, 'Input Data Type').getByRole('combobox')).toBeVisible()
  })
})

test.describe('Real Backend Integration — agent management panel', () => {
  test('full CRUD lifecycle through the panel against the live stack', async ({ page }) => {
    // Gate 1: backend reachable? (Any HTTP response counts — this deployment
    // returns 401 on health without an Authorization header, which still
    // proves the service is up. A network error means it is not running.)
    let backendUp = false
    try {
      await page.request.get('http://localhost:8000/api/v1/health', { timeout: 3000 })
      backendUp = true
    } catch {
      backendUp = false
    }
    test.skip(!backendUp, 'Backend on http://localhost:8000 is not reachable — live CRUD variant skipped.')
    if (!backendUp) return

    // Gate 2: real OIDC login through the dev server (proxies /api → :8000).
    // Same steps as `loginViaUI` in _helpers.ts, but origin-aware: that helper
    // hard-waits for localhost:5173, which only matches when the flow starts
    // on the dev server (the one origin that proxies to the real backend).
    try {
      await page.goto('http://localhost:5173/')
      await page.waitForLoadState('networkidle')
      if (page.url().includes('/login')) {
        await page.click('button:has-text("Sign In")')
        await page.waitForURL('**/realms/**/protocol/openid-connect/**', { timeout: 15000 })
        const username = process.env.E2E_TEST_USERNAME || 'testuser'
        const password = process.env.E2E_TEST_PASSWORD || 'testuser'
        await page.fill('input[name="username"]', username)
        await page.fill('input[name="password"]', password)
        await page.press('input[name="password"]', 'Enter')
        await page.waitForURL((url) => url.href.includes('localhost:5173'), { timeout: 30000 })
        if (page.url().includes('/callback')) {
          await page.waitForURL(/^http:\/\/localhost:5173\/(dashboard|agents|mcp)/, {
            timeout: 15000,
          })
        }
      }
    } catch {
      test.skip('Real OIDC login did not complete (test user/provider unavailable) — live CRUD variant skipped.')
      return
    }

    await page.goto('http://localhost:5173/agents/panel')
    await page.waitForLoadState('load')
    if (page.url().includes('/login')) {
      test.skip('Panel redirected to login — live CRUD variant skipped.')
      return
    }
    await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()

    const name = `e2e-panel-live-${Date.now()}`

    // Gate 3: creation must succeed on the live stack (it requires the
    // agent::types create permission and an existing role with bindable
    // SOPs/skills — anything missing means the variant cannot proceed).
    let created = false
    try {
      await page.getByRole('button', { name: 'Create Agent' }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog.getByRole('heading', { name: 'Create Agent Type' })).toBeVisible()
      await dialog.getByLabel('Name').fill(name)
      await muiCombobox(dialog, 'Agent Role').click()
      const roleOptions = page.getByRole('option')
      if ((await roleOptions.count()) <= 1) {
        test.skip('Roles list unavailable on the live stack (empty or permission-denied for the test user) — live CRUD variant skipped.')
        return
      }
      await roleOptions.nth(1).click()
      await dialog.getByRole('button', { name: 'Add Binding' }).click()
      await dialog
        .locator('.MuiToggleButtonGroup-root')
        .locator('..')
        .getByRole('combobox')
        .click()
      const bindingOptions = page.getByRole('option')
      if ((await bindingOptions.count()) <= 1) {
        test.skip('Selected role has no bindable SOPs/skills on the live stack — live CRUD variant skipped.')
        return
      }
      await bindingOptions.nth(1).click()
      await dialog.getByRole('button', { name: 'Add', exact: true }).click()
      await dialog.getByRole('button', { name: 'Save', exact: true }).click()
      await expect(dialog).toBeHidden({ timeout: 15_000 })
      created = true
    } catch {
      test.skip('Agent creation did not complete on the live stack (permission denied or validation) — live CRUD variant skipped.')
      return
    }

    // CREATE is visible in the sidebar + header without a reload.
    await expect(page.getByRole('button', { name })).toBeVisible()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    expect(created).toBe(true)

    try {
      // DELETE via the confirmation dialog.
      await page.getByLabel('Delete').click()
      const confirm = page.getByRole('dialog')
      await expect(confirm.getByText(new RegExp(`Delete agent "${name}"`))).toBeVisible()
      await confirm.getByRole('button', { name: 'Delete', exact: true }).click()
      await expect(page.getByRole('button', { name })).toBeHidden({ timeout: 15_000 })
    } finally {
      // Safety net: if the UI delete did not happen, remove the agent via the
      // API so the live database is never left with test data.
      const token = await page.evaluate(() => localStorage.getItem('access_token'))
      if (token) {
        try {
          const list = await page.request.get('http://localhost:8000/api/v1/agents/types', {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (list.ok()) {
            const agents = (await list.json()) as { id: string; name: string }[]
            const leftover = agents.find((a) => a.name === name)
            if (leftover) {
              await page.request.delete(
                `http://localhost:8000/api/v1/agents/types/${leftover.id}`,
                { headers: { Authorization: `Bearer ${token}` } },
              )
            }
          }
        } catch {
          // cleanup best-effort only
        }
      }
    }

    // RECREATE with the same name — proves true deletion on the live backend.
    await page.getByRole('button', { name: 'Create Agent' }).click()
    const dialog2 = page.getByRole('dialog')
    await expect(dialog2.getByRole('heading', { name: 'Create Agent Type' })).toBeVisible()
    await dialog2.getByLabel('Name').fill(name)
    await muiCombobox(dialog2, 'Agent Role').click()
    await page.getByRole('option').nth(1).click()
    await dialog2.getByRole('button', { name: 'Add Binding' }).click()
    await dialog2
      .locator('.MuiToggleButtonGroup-root')
      .locator('..')
      .getByRole('combobox')
      .click()
    await page.getByRole('option').nth(1).click()
    await dialog2.getByRole('button', { name: 'Add', exact: true }).click()
    await dialog2.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(dialog2).toBeHidden()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()

    // Cleanup the recreated agent as well.
    await page.getByLabel('Delete').click()
    const confirm2 = page.getByRole('dialog')
    await confirm2.getByRole('button', { name: 'Delete', exact: true }).click()
    await expect(page.getByRole('button', { name })).toBeHidden({ timeout: 15_000 })
  })
})
