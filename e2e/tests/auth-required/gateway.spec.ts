import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_AGENT_TYPES = [
  { id: 'at-1', name: 'Research Agent', mode: 'skillful', description: 'Research', is_active: true },
]

test.describe('Gateway Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_AGENT_TYPES) })
    )
  })

  test('gateway config page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('gateway config page does not redirect to login', async ({ page }) => {
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('gateway page shows agent type names', async ({ page }) => {
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    await expect(page.getByText('Research Agent')).toBeVisible()
  })

  test('gateway page shows HTTP endpoint path', async ({ page }) => {
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    await expect(page.getByText(/\/gateway\/at-1\/init/)).toBeVisible()
  })

  test('gateway page shows MCP tool names', async ({ page }) => {
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    await expect(page.getByText('skillful')).toBeVisible()
  })

  test('gateway page has interactive elements for configuration', async ({ page }) => {
    await page.goto('/gateway')
    await page.waitForLoadState('load')
    await expect(page.getByRole('button').first()).toBeVisible()
  })
})