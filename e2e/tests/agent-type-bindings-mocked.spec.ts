import { test, expect } from '@playwright/test'
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

async function setupBindingMocks(page: Parameters<typeof test>[1]['page']) {
  await page.route('**/api/v1/agents/types', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
      return
    }
    route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_TYPE_BASE) })
  })

  await page.route('**/api/v1/agents/types/**', (route) => {
    if (route.request().method() === 'DELETE') {
      route.fulfill({ status: 204 })
      return
    }
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE_BASE) })
  })

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
}

test.describe('Agent Type Bindings — Mocked', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupBindingMocks(page)
  })

  test('binding section renders with title and empty state in create dialog', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await expect(createBtn).toBeVisible()
    await createBtn.click()

    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('SOP / Skill Bindings')).toBeVisible()
    await expect(page.getByText('No bindings configured. Use the button below to add SOP or skill bindings.')).toBeVisible()
  })

  test('Add Binding button is disabled when no role selected', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const addBindingBtn = page.getByRole('dialog').getByRole('button', { name: 'Add Binding' })
    await expect(addBindingBtn).toBeDisabled()
  })

  test('selecting a role enables Add Binding button', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const addBindingBtn = page.getByRole('dialog').getByRole('button', { name: 'Add Binding' })
    await expect(addBindingBtn).toBeDisabled()

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await expect(addBindingBtn).toBeEnabled()
  })

  test('add SOP binding via complete UI flow', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()

    await expect(page.getByRole('dialog').getByText('SOP')).toBeVisible()
    await expect(page.getByRole('dialog').getByText('Skill')).toBeVisible()

    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Onboarding SOP' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    await expect(page.getByRole('dialog').getByText('Onboarding SOP')).toBeVisible()
    await expect(page.getByRole('dialog').getByText('SOP')).toBeVisible()
  })

  test('add Skill binding via UI flow with type toggle', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()

    await page.getByRole('dialog').getByText('Skill').click()

    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Summarise Text' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    await expect(page.getByRole('dialog').getByText('Summarise Text')).toBeVisible()
  })

  test('remove binding from the list', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()
    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Onboarding SOP' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    await expect(page.getByRole('dialog').getByText('Onboarding SOP')).toBeVisible()

    await page.getByRole('dialog').getByRole('button', { name: 'Remove' }).click()

    await expect(page.getByRole('dialog').getByText('Onboarding SOP')).not.toBeVisible()
  })

  test('reorder bindings with move up', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()
    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Incident Response' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()
    await page.getByRole('dialog').getByText('Skill').click()
    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Summarise Text' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    const moveUpButtons = page.getByRole('dialog').getByRole('button', { name: 'Move up' })
    await expect(moveUpButtons).toHaveCount(2)

    const firstMoveUp = moveUpButtons.first()
    await expect(firstMoveUp).toBeDisabled()

    const secondMoveUp = moveUpButtons.last()
    await expect(secondMoveUp).toBeEnabled()

    await secondMoveUp.click()
  })

  test('save sends bindings in API payload', async ({ page }) => {
    let capturedPayload: Record<string, unknown> | null = null

    // Override the types route AFTER beforeEach registered base mocks.
    // This registration is later so it takes precedence.
    await page.route('**/api/v1/agents/types', (route) => {
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
            id: 'at-e2e-1',
            name: capturedPayload!.name as string,
            role_id: 'role-1',
            sop_bindings: [
              { id: 'bind-1', sop_id: 'sop-1', sop_name: 'Onboarding SOP', order: 0, created_at: '2026-01-01T00:00:00Z' },
            ],
            skill_bindings: [
              { id: 'bind-2', skill_id: 'sk-1', skill_name: 'Summarise Text', order: 0, created_at: '2026-01-01T00:00:00Z' },
            ],
          }),
        })
        return
      }
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('E2E Test Agent')

    await page.getByRole('dialog').getByText('No role assigned').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Test Role' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()
    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Onboarding SOP' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    await page.getByRole('dialog').getByRole('button', { name: 'Add Binding' }).click()
    await page.getByRole('dialog').getByText('Skill').click()
    await page.getByRole('dialog').locator('[role="combobox"]').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.getByRole('option', { name: 'Summarise Text' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Add' }).click()

    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    expect(capturedPayload).not.toBeNull()
    expect(capturedPayload!.sop_bindings).toEqual([{ sop_id: 'sop-1', order: 0 }])
    expect(capturedPayload!.skill_bindings).toEqual([{ skill_id: 'sk-1', order: 0 }])
  })
})
