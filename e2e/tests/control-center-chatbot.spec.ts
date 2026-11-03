import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * Control Center Assistant — mocked conversational flows.
 *
 * No live backend: uses page.route() mocks to drive the assistant entry point
 * (floating action button → ConversationDialog) and the is_system surfacing on
 * the Agent Types list.  The full natural-language → management-tool journey is
 * exercised in the backend integration tests and the real-backend spec.
 */

const SYSTEM_ASSISTANT = {
  id: 'at-assistant',
  name: 'control-center-assistant',
  description: 'System-provided conversational assistant',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: 'assistant instructions',
  input_type: 'conversation',
  output_type: 'auto',
  is_active: true,
  is_system: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const REGULAR_AGENT = {
  id: 'at-1',
  name: 'Research Agent',
  description: '',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: null,
  input_type: 'typed',
  output_type: 'markdown',
  is_active: true,
  is_system: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

async function mockAgentTypes(page: import('@playwright/test').Page, types: unknown[]) {
  // Trailing * matches the paginated list URL (…/agents/types?limit=25&offset=0)
  // used by AgentManagementPage as well as the unpaginated AppShell query.
  await page.route('**/api/v1/agents/types*', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ status: 200, body: JSON.stringify(types) })
    }
    return route.fulfill({ status: 201, body: JSON.stringify(types[0] ?? {}) })
  })
  await page.route('**/api/v1/agents/roles', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
}

test.describe('Control Center Assistant (mocked)', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('assistant FAB appears only when a system agent type is resolved', async ({ page }) => {
    await mockAgentTypes(page, [REGULAR_AGENT])
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // No system type → no assistant launcher.
    await expect(page.getByLabel('Control Center Assistant')).toHaveCount(0)

    // Re-mock to include the system assistant and reload.
    await mockAgentTypes(page, [REGULAR_AGENT, SYSTEM_ASSISTANT])
    await page.reload()
    await page.waitForLoadState('load')
    await expect(page.getByLabel('Control Center Assistant')).toBeVisible()
  })

  test('clicking the assistant FAB opens the conversational surface', async ({ page }) => {
    await mockAgentTypes(page, [SYSTEM_ASSISTANT])
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    await page.getByLabel('Control Center Assistant').click()

    // The reused ConversationDialog opens (MUI dialog container).
    await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('Agent Types list marks system agent types and disables edit/delete', async ({ page }) => {
    await mockAgentTypes(page, [SYSTEM_ASSISTANT])
    await page.goto('/agents')
    await page.waitForLoadState('load')

    // The system badge is shown next to the assistant's name (scoped to the
    // table so it doesn't collide with the sidebar "System" nav group).
    await expect(page.locator('table').getByText('System', { exact: true })).toBeVisible()

    // Edit and delete controls are disabled for the system agent type.
    const editBtn = page.getByRole('button', { name: 'Edit' })
    await expect(editBtn).toBeDisabled()
    const deleteBtn = page.getByRole('button', { name: 'Delete' })
    await expect(deleteBtn).toBeDisabled()
  })

  test('non-system agent types remain editable and deletable', async ({ page }) => {
    await mockAgentTypes(page, [REGULAR_AGENT])
    await page.goto('/agents')
    await page.waitForLoadState('load')

    // No system badge for a normal agent type (scoped to the table).
    await expect(page.locator('table').getByText('System', { exact: true })).toHaveCount(0)

    // Edit and delete are enabled for non-system types.
    await expect(page.getByRole('button', { name: 'Edit' })).toBeEnabled()
    await expect(page.getByRole('button', { name: 'Delete' })).toBeEnabled()
  })
})
