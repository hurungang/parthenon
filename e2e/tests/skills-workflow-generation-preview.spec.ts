import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_SKILL = {
  id: 'sk-1',
  name: 'Workflow Skill',
  description: 'Initial skill description',
  instructions: 'Initial workflow',
  is_active: true,
  tool_ids: ['tool-1'],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_TOOL = {
  id: 'tool-1',
  server_id: 'srv-1',
  name: 'internal____search',
  original_name: 'search',
  description: 'Search docs',
  input_schema: { type: 'object' },
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

async function setupSkillEditorBaseMocks(page: import('@playwright/test').Page) {
  await standardSetup(page)

  await page.route('**/api/v1/skills', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SKILL]) })
      return
    }
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILL) })
  })

  await page.route('**/api/v1/skills/sk-1', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILL) })
  })

  await page.route('**/api/v1/skills/sk-1/roles', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  })

  await page.route('**/api/v1/mcp/tools', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([MOCK_TOOL]) })
  })

  await page.route('**/api/v1/mcp/servers', (route) => {
    route.fulfill({
      status: 200,
      body: JSON.stringify([{ id: 'srv-1', slug: 'internal', name: 'Internal', base_url: 'http://x', status: 'active' }]),
    })
  })

  await page.route('**/api/v1/agents/roles', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  })
}

test.describe('Skill workflow generation and preview (mocked API)', () => {
  test('uses Workflow terminology and not legacy System Instruction in editor', async ({ page }) => {
    await setupSkillEditorBaseMocks(page)

    await page.goto('/skills')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await expect(page.getByLabel('Workflow')).toBeVisible()
    await expect(page.getByText('System Instruction')).toHaveCount(0)
  })

  test('preview renders one instruction file and uses latest unsaved workflow text', async ({ page }) => {
    await setupSkillEditorBaseMocks(page)

    let previewPayload: Record<string, unknown> | null = null
    await page.route('**/api/v1/skills/workflow/generate', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify({ workflow: 'Generated workflow', model_id: 'gpt-4o-mini' }) })
    })
    await page.route('**/api/v1/skills/workflow/preview', (route) => {
      previewPayload = route.request().postDataJSON() as Record<string, unknown>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          instruction_file: '# Skill Workflow Instruction File\nLatest unsaved draft for preview',
          model_id: 'gpt-4o-mini',
          selected_tools: [],
        }),
      })
    })

    await page.goto('/skills')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await page.getByLabel('Description').fill('latest business description')
    await page.getByLabel('Workflow').fill('Latest unsaved draft for preview')
    await page.getByRole('button', { name: 'Preview Workflow' }).click()

    await expect(page.getByText('Workflow Preview (Model: gpt-4o-mini)')).toBeVisible()
    await expect(page.getByText('# Skill Workflow Instruction File')).toBeVisible()
    await expect(page.locator('pre', { hasText: 'Latest unsaved draft for preview' })).toBeVisible()

    expect(previewPayload).not.toBeNull()
    expect(previewPayload?.workflow).toBe('Latest unsaved draft for preview')
    expect(previewPayload?.description).toBe('latest business description')
  })

  test('missing model returns user-visible error and does not fallback to generated workflow', async ({ page }) => {
    await setupSkillEditorBaseMocks(page)

    await page.route('**/api/v1/skills/workflow/generate', (route) => {
      route.fulfill({
        status: 422,
        body: JSON.stringify({
          detail: 'Workflow generation model is not configured. Configure it in system settings.',
        }),
      })
    })

    await page.goto('/skills')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await page.getByLabel('Workflow').fill('manual workflow text')
    await page.getByRole('button', { name: 'Generate Workflow with AI' }).click()

    await expect(page.getByText(/not configured/i)).toBeVisible()
    await expect(page.getByLabel('Workflow')).toHaveValue('manual workflow text')
  })
})
