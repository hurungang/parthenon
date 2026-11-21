import { test, expect, type Locator, type Page } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_ROLES = [
  {
    id: 'role-1',
    name: 'Test Role',
    description: null,
    sop_ids: ['sop-1', 'sop-2'],
    skill_ids: ['sk-1', 'sk-2'],
    allowed_identity_types: [],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const MOCK_SOPS = [
  { id: 'sop-1', name: 'Onboarding SOP', description: 'New employee onboarding', is_active: true, instructions: 'Follow steps' },
  { id: 'sop-2', name: 'Incident Response', description: 'Handle incidents', is_active: true, instructions: null },
]

const MOCK_SKILLS = [
  { id: 'sk-1', name: 'Summarise Text', description: 'Summarises long text', is_active: true, instructions: null, tool_ids: ['tool-1'] },
  { id: 'sk-2', name: 'Send Email', description: 'Sends an email', is_active: true, instructions: null, tool_ids: ['tool-2'] },
]

const MOCK_AGENT_TYPE_BASE = {
  id: 'at-e2e-1',
  name: 'E2E Test Agent',
  description: '',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: null,
  input_type: 'none',
  input_schema: null,
  output_type: 'auto',
  output_schema: null,
  sop_bindings: [],
  skill_bindings: [],
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

async function setupBindingMocks(page: Page) {
  // Collection first — route handlers resolve last-registered-first, so the
  // item / sub-resource mocks below keep priority. The trailing `**` is
  // required: the list request carries `?limit=&offset=`.
  await page.route('**/api/v1/agents/types**', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
      return
    }
    route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_TYPE_BASE) })
  })

  await page.route('**/api/v1/agents/types/*', (route) => {
    if (route.request().method() === 'DELETE') {
      route.fulfill({ status: 204 })
      return
    }
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE_BASE) })
  })

  await page.route('**/api/v1/agents/types/*/**', (route) =>
    route.fulfill({ status: 404, body: JSON.stringify({ detail: 'not mocked' }) })
  )

  await page.route('**/api/v1/agents/roles', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_ROLES) })
  )

  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )

  await page.route('**/api/v1/agents/model-configs', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )

  await page.route('**/api/v1/sops', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SOPS) })
  )

  await page.route('**/api/v1/skills', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILLS) })
  )

  await page.route('**/api/v1/data-types**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({ items: [], total: 0 }) })
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Opens the "Create Agent Type" dialog on the agents page. */
async function openCreateDialog(page: Page): Promise<Locator> {
  await page.goto('/agents')
  await page.waitForLoadState('load')

  const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
  await expect(createBtn).toBeVisible()
  await createBtn.click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

/**
 * MUI Selects have no accessible name of their own, so selects are resolved
 * through their `.MuiFormControl-root` wrapper, matched by the visible label.
 */
function formControl(dialog: Locator, label: string): Locator {
  return dialog.locator('.MuiFormControl-root').filter({ hasText: label })
}

/** Picks the agent role in the form (enables the binding section). */
async function selectRole(page: Page, dialog: Locator, roleName = 'Test Role') {
  await formControl(dialog, 'Agent Role').locator('[role="combobox"]').click()
  await page.waitForSelector('[role="listbox"]', { state: 'visible' })
  await page.getByRole('option', { name: roleName, exact: true }).click()
}

/** Opens the inline add-binding row and picks an item of the given type. */
async function addBinding(
  page: Page,
  dialog: Locator,
  options: { type: 'SOP' | 'Skill'; name: string },
) {
  await dialog.getByRole('button', { name: 'Add Binding' }).click()
  if (options.type === 'Skill') {
    await dialog.getByRole('button', { name: 'Skill', exact: true }).click()
  }
  // The un-labelled picker shows the "Select an item…" placeholder while empty.
  await dialog.getByText('Select an item…').click()
  await page.waitForSelector('[role="listbox"]', { state: 'visible' })
  await page.getByRole('option', { name: options.name, exact: true }).click()
  await dialog.getByRole('button', { name: 'Add', exact: true }).click()
}

/** The binding row (chip + name + reorder/remove actions) for a bound item. */
function bindingRow(dialog: Locator, name: string): Locator {
  return dialog.getByText(name, { exact: true }).locator('..')
}

test.describe('Agent Type Bindings — Mocked', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupBindingMocks(page)
  })

  test('binding section renders with title and empty state in create dialog', async ({ page }) => {
    const dialog = await openCreateDialog(page)

    await expect(dialog.getByText('SOP / Skill Bindings')).toBeVisible()
    // Empty state is the blocking validation copy (a save without at least one
    // SOP/skill binding is rejected by the form and by the backend).
    await expect(
      dialog.getByText('At least one SOP or Skill binding is required. Add a binding before saving.'),
    ).toBeVisible()
  })

  test('Add Binding button is disabled when no role selected', async ({ page }) => {
    const dialog = await openCreateDialog(page)

    const addBindingBtn = dialog.getByRole('button', { name: 'Add Binding' })
    await expect(addBindingBtn).toBeDisabled()
  })

  test('selecting a role enables Add Binding button', async ({ page }) => {
    const dialog = await openCreateDialog(page)

    const addBindingBtn = dialog.getByRole('button', { name: 'Add Binding' })
    await expect(addBindingBtn).toBeDisabled()

    await selectRole(page, dialog)

    await expect(addBindingBtn).toBeEnabled()
  })

  test('add SOP binding via complete UI flow', async ({ page }) => {
    const dialog = await openCreateDialog(page)
    await selectRole(page, dialog)

    await addBinding(page, dialog, { type: 'SOP', name: 'Onboarding SOP' })

    await expect(dialog.getByText('Onboarding SOP')).toBeVisible()
    await expect(bindingRow(dialog, 'Onboarding SOP').getByText('SOP', { exact: true })).toBeVisible()
    // The blocking empty-state copy disappears once a binding exists.
    await expect(
      dialog.getByText('At least one SOP or Skill binding is required. Add a binding before saving.'),
    ).toHaveCount(0)
  })

  test('add Skill binding via UI flow with type toggle', async ({ page }) => {
    const dialog = await openCreateDialog(page)
    await selectRole(page, dialog)

    await addBinding(page, dialog, { type: 'Skill', name: 'Summarise Text' })

    await expect(dialog.getByText('Summarise Text')).toBeVisible()
    await expect(bindingRow(dialog, 'Summarise Text').getByText('Skill', { exact: true })).toBeVisible()
  })

  test('remove binding from the list', async ({ page }) => {
    const dialog = await openCreateDialog(page)
    await selectRole(page, dialog)
    await addBinding(page, dialog, { type: 'SOP', name: 'Onboarding SOP' })

    await expect(dialog.getByText('Onboarding SOP')).toBeVisible()

    await dialog.getByRole('button', { name: 'Remove', exact: true }).click()

    await expect(dialog.getByText('Onboarding SOP')).toHaveCount(0)
    await expect(
      dialog.getByText('At least one SOP or Skill binding is required. Add a binding before saving.'),
    ).toBeVisible()
  })

  test('reorder bindings with move up', async ({ page }) => {
    const dialog = await openCreateDialog(page)
    await selectRole(page, dialog)

    await addBinding(page, dialog, { type: 'SOP', name: 'Onboarding SOP' })
    await addBinding(page, dialog, { type: 'SOP', name: 'Incident Response' })

    // Ordering is per binding list (SOP bindings vs skill bindings), so both
    // rows expose a "Move up" action and only the first is disabled.
    const moveUpButtons = dialog.getByRole('button', { name: 'Move up' })
    await expect(moveUpButtons).toHaveCount(2)
    await expect(moveUpButtons.first()).toBeDisabled()
    await expect(moveUpButtons.last()).toBeEnabled()

    await expect(bindingRow(dialog, 'Onboarding SOP')).toContainText('#1')
    await moveUpButtons.last().click()

    // The swap rewrites the `order` values shown on each row.
    await expect(bindingRow(dialog, 'Incident Response')).toContainText('#1')
    await expect(bindingRow(dialog, 'Onboarding SOP')).toContainText('#2')
  })

  test('save sends bindings in API payload', async ({ page }) => {
    let capturedPayload: Record<string, unknown> | null = null

    // Later registration wins in Playwright — this POST mock overrides the
    // base collection mock from beforeEach.
    await page.route('**/api/v1/agents/types**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([]) })
        return
      }
      if (route.request().method() === 'POST') {
        capturedPayload = route.request().postDataJSON()
        route.fulfill({
          status: 201,
          body: JSON.stringify({
            ...MOCK_AGENT_TYPE_BASE,
            name: capturedPayload!.name as string,
            role_id: 'role-1',
            sop_bindings: [
              { id: 'bind-1', sop_id: 'sop-1', sop_name: 'Onboarding SOP', order: 1, created_at: '2026-01-01T00:00:00Z' },
            ],
            skill_bindings: [
              { id: 'bind-2', skill_id: 'sk-1', skill_name: 'Summarise Text', order: 1, created_at: '2026-01-01T00:00:00Z' },
            ],
          }),
        })
        return
      }
    })

    const dialog = await openCreateDialog(page)

    // Names must be a lowercase slug: /^[a-z0-9-]+$/.
    await dialog.locator('input').first().fill('e2e-test-agent')
    await selectRole(page, dialog)

    await addBinding(page, dialog, { type: 'SOP', name: 'Onboarding SOP' })
    await addBinding(page, dialog, { type: 'Skill', name: 'Summarise Text' })

    const saveBtn = dialog.getByRole('button', { name: 'Save', exact: true })
    await expect(saveBtn).toBeEnabled()
    await saveBtn.click()

    await expect.poll(() => capturedPayload).not.toBeNull()
    // First binding in its list starts at order 1 (0 means "unset").
    expect(capturedPayload!['sop_bindings']).toEqual([{ sop_id: 'sop-1', order: 1 }])
    expect(capturedPayload!['skill_bindings']).toEqual([{ skill_id: 'sk-1', order: 1 }])
    expect(capturedPayload!['role_id']).toBe('role-1')
  })
})
