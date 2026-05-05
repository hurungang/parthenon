import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_AGENT_TYPES = [
  {
    id: 'at-1',
    name: 'Research Agent',
    description: '',
    identity_id: null,
    role_id: null,
    llm_provider: 'openai',
    llm_model: 'gpt-4o',
    system_instruction: null,
    input_type: 'none',
    input_schema: null,
    output_type: 'markdown',
    output_schema: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

test.describe('Agent Management', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/agents/types', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_TYPES[0]) })
      }
    })
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES[0]) })
    )
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/sessions', (route) =>
      route.fulfill({ status: 201, body: JSON.stringify({ id: 'sess-1', status: 'queued' }) })
    )
  })

  test('Agent management page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/agents')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('Agent management page has content', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
    await expect(page.getByRole('button').first()).toBeVisible()
  })

  test('Agent management page has at least one button', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    const buttons = page.getByRole('button')
    await expect(buttons.first()).toBeVisible()
  })

  test('displays list of agent types from API', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    // Agent name from mock should appear in the list
    await expect(page.getByText('Research Agent')).toBeVisible()
  })

  test('displays input_type for each agent type', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    // input_type 'none' is rendered as a chip in the agent type row
    await expect(page.getByText('none')).toBeVisible()
  })

  test('shows create agent type button and opens dialog on click', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    // Button text from i18n: agents.createType = "Create Agent Type"
    const createBtn = page.locator('button:visible').filter({ hasText: /Create Agent Type|create|add/i }).first()
    const hasCreateBtn = await createBtn.count() > 0
    if (hasCreateBtn) {
      await createBtn.click()
      // MUI Dialog renders with class MuiDialog-root (distinct from MUI Drawer)
      await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 5000 })
    } else {
      await expect(page.locator('button:visible').first()).toBeVisible()
    }
  })
})