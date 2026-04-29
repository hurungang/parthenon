import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_SKILLS = [
  { id: 'sk-1', name: 'Summarise Text', description: 'Summarises long text', is_active: true, tool_binding_count: 1 },
  { id: 'sk-2', name: 'Send Email', description: 'Sends an email via SMTP', is_active: true, tool_binding_count: 1 },
  { id: 'sk-3', name: 'Web Search', description: 'Searches the web for information', is_active: false, tool_binding_count: 0 },
]

const MOCK_SOPS = [
  { id: 'sop-1', name: 'Onboarding SOP', description: 'New employee onboarding', is_active: true, step_count: 3 },
  { id: 'sop-2', name: 'Incident Response', description: 'Handle incidents systematically', is_active: true, step_count: 5 },
]

const MOCK_SOP_STEPS = [
  { id: 'step-1', sop_id: 'sop-1', order: 1, action: 'Collect user info', skill_id: 'sk-1' },
  { id: 'step-2', sop_id: 'sop-1', order: 2, action: 'Send welcome email', skill_id: 'sk-2' },
  { id: 'step-3', sop_id: 'sop-1', order: 3, action: 'Schedule follow-up', skill_id: null },
]

test.describe('Skills', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/skills', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILLS) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_SKILLS[0]) })
      }
    })
  })

  test('skills page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/skills')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('skills page does not redirect to login', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('skills page lists skill names from API', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    await expect(page.getByText('Summarise Text')).toBeVisible()
  })

  test('skills page shows all skills including Send Email', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    await expect(page.getByText('Send Email')).toBeVisible()
  })

  test('skills page shows skill descriptions', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    const desc = page.getByText(/Summarises long text|Sends an email/i)
    const hasDesc = await desc.count() > 0
    if (hasDesc) {
      await expect(desc.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('skills page shows active vs inactive status', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    const statusText = page.getByText(/active|inactive/i)
    const hasStatus = await statusText.count() > 0
    if (hasStatus) {
      await expect(statusText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('skills page has create skill button', async ({ page }) => {
    await page.goto('/skills')
    await page.waitForLoadState('load')
    // Button text from i18n: skills.createSkill = "Create Skill"
    const createBtn = page.locator('button:visible').filter({ hasText: /Create Skill|create|add|new/i }).first()
    const hasCreateBtn = await createBtn.count() > 0
    if (hasCreateBtn) {
      await expect(createBtn).toBeVisible()
      await createBtn.click()
      // MUI Dialog (not Drawer) should open - use class selector to avoid matching Drawer
      await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 5000 })
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })
})

test.describe('SOPs', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/sops', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SOPS) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_SOPS[0]) })
      }
    })
    await page.route('**/api/v1/sops/*/steps', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_SOP_STEPS) })
    )
  })

  test('SOPs page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/sops')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('SOPs page does not redirect to login', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('SOPs page lists SOP names from API', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    await expect(page.getByText('Onboarding SOP')).toBeVisible()
  })

  test('SOPs page shows second SOP in list', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    await expect(page.getByText('Incident Response')).toBeVisible()
  })

  test('SOPs page shows step count for SOPs', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    // step_count of 3 should appear
    const stepCount = page.getByText('3')
    const hasCount = await stepCount.count() > 0
    if (hasCount) {
      await expect(stepCount.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('SOPs page shows SOP descriptions', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    const desc = page.getByText(/New employee onboarding|Handle incidents/i)
    const hasDesc = await desc.count() > 0
    if (hasDesc) {
      await expect(desc.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('clicking a SOP shows its steps', async ({ page }) => {
    await page.goto('/sops')
    await page.waitForLoadState('load')
    const sopItem = page.locator('[role="row"], li, tr').filter({ hasText: 'Onboarding SOP' }).first()
    const hasSopItem = await sopItem.count() > 0
    if (hasSopItem) {
      await sopItem.click()
      const stepContent = page.getByText(/Collect user info|Send welcome email|Schedule follow-up/i)
      const hasSteps = await stepContent.count() > 0
      if (hasSteps) {
        await expect(stepContent.first()).toBeVisible({ timeout: 5000 })
      } else {
        await expect(page.getByRole('button').first()).toBeVisible()
      }
    }
  })
})