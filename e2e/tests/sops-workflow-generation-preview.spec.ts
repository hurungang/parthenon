import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_SOP = {
  id: 'sop-1',
  name: 'Workflow SOP',
  description: 'Initial sop description',
  instructions: 'Initial SOP workflow',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_SOP_DETAIL = {
  ...MOCK_SOP,
  steps: [
    {
      id: 'step-1',
      sop_id: 'sop-1',
      order: 0,
      step_type: 'skill_invocation',
      skill_id: 'skill-1',
      target_agent_type_id: null,
      step_config: null,
      name: 'Step One',
      description: 'Step One Description',
    },
  ],
}

async function setupSopEditorBaseMocks(page: import('@playwright/test').Page) {
  await standardSetup(page)

  await page.route('**/api/v1/sops', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SOP]) })
      return
    }
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SOP) })
  })

  await page.route('**/api/v1/sops/sop-1', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SOP_DETAIL) })
  })

  await page.route('**/api/v1/sops/sop-1/roles', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  })

  await page.route('**/api/v1/skills', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([{ id: 'skill-1', name: 'Skill 1' }]) })
  })

  await page.route('**/api/v1/agents/types', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  })

  await page.route('**/api/v1/agents/roles', (route) => {
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  })
}

test.describe('SOP workflow generation and preview (mocked API)', () => {
  test('uses Workflow terminology and not legacy System Instruction in editor', async ({ page }) => {
    await setupSopEditorBaseMocks(page)

    await page.goto('/sops')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await expect(page.getByLabel('Workflow')).toBeVisible()
    await expect(page.getByText('System Instruction')).toHaveCount(0)
  })

  test('preview renders one SOP instruction file and uses latest unsaved workflow text', async ({ page }) => {
    await setupSopEditorBaseMocks(page)

    let previewPayload: Record<string, unknown> | null = null
    await page.route('**/api/v1/sops/workflow/preview', (route) => {
      previewPayload = route.request().postDataJSON() as Record<string, unknown>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          instruction_file: '# SOP Workflow Instruction File\nLatest unsaved SOP draft',
          model_id: 'gpt-4o-mini',
          steps: [],
        }),
      })
    })

    await page.route('**/api/v1/sops/workflow/generate', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify({ workflow: 'generated sop workflow', model_id: 'gpt-4o-mini' }) })
    })

    await page.goto('/sops')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await page.getByLabel('Description').fill('latest sop description')
    await page.getByLabel('Workflow').fill('Latest unsaved SOP draft')
    await page.getByRole('button', { name: 'Preview Workflow' }).click()

    await expect(page.getByText('Workflow Preview (Model: gpt-4o-mini)')).toBeVisible()
    await expect(page.getByText('# SOP Workflow Instruction File')).toBeVisible()
    await expect(page.locator('pre', { hasText: 'Latest unsaved SOP draft' })).toBeVisible()

    expect(previewPayload).not.toBeNull()
    expect(previewPayload?.workflow).toBe('Latest unsaved SOP draft')
    expect(previewPayload?.description).toBe('latest sop description')
  })

  test('missing model returns user-visible error and does not fallback to generated SOP workflow', async ({ page }) => {
    await setupSopEditorBaseMocks(page)

    await page.route('**/api/v1/sops/workflow/generate', (route) => {
      route.fulfill({
        status: 422,
        body: JSON.stringify({
          detail: 'Workflow generation model is not configured. Configure it in system settings.',
        }),
      })
    })

    await page.goto('/sops')
    await page.waitForLoadState('load')

    await page.locator('tbody tr').first().locator('button').first().click()

    await page.getByLabel('Workflow').fill('manual sop workflow text')
    await page.getByRole('button', { name: 'Generate Workflow with AI' }).click()

    await expect(page.getByText(/not configured/i)).toBeVisible()
    await expect(page.getByLabel('Workflow')).toHaveValue('manual sop workflow text')
  })
})
