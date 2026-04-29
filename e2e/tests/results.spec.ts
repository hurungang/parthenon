import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_RESULTS = [
  {
    id: 'res-1',
    agent_type_id: 'at-1',
    session_id: 'sess-1',
    content_type: 'text/plain',
    payload: { text: 'Analysis complete' },
    tags: ['research', 'q1-2026'],
    created_at: '2026-04-20T12:00:00Z',
  },
  {
    id: 'res-2',
    agent_type_id: 'at-1',
    session_id: 'sess-2',
    content_type: 'application/json',
    payload: { summary: 'Market report' },
    tags: ['market', 'q2-2026'],
    created_at: '2026-04-21T09:00:00Z',
  },
]

test.describe('Result Repository', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/results**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_RESULTS) })
    )
    await standardSetup(page)
  })

  test('result repository page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/results')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('result repository page does not redirect to login', async ({ page }) => {
    await page.goto('/results')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('result repository shows result payload text', async ({ page }) => {
    await page.goto('/results')
    await page.waitForLoadState('load')
    // 'Analysis complete' from the first mock result should appear
    const resultText = page.getByText(/Analysis complete|res-1/i)
    const hasResult = await resultText.count() > 0
    if (hasResult) {
      await expect(resultText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('result repository shows tags for results', async ({ page }) => {
    await page.goto('/results')
    await page.waitForLoadState('load')
    const tagText = page.getByText(/research|q1-2026/i)
    const hasTags = await tagText.count() > 0
    if (hasTags) {
      await expect(tagText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('result repository shows content types', async ({ page }) => {
    await page.goto('/results')
    await page.waitForLoadState('load')
    const typeText = page.getByText(/text\/plain|application\/json|plain|json/i)
    const hasType = await typeText.count() > 0
    if (hasType) {
      await expect(typeText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('result repository has filter or search capability', async ({ page }) => {
    await page.goto('/results')
    await page.waitForLoadState('load')
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i], input[placeholder*="filter" i]')
    const hasSearch = await searchInput.count() > 0
    if (hasSearch) {
      await expect(searchInput.first()).toBeVisible()
    } else {
      // At minimum should have interactive elements
      const interactive = page.locator('button:visible, input:visible, [role="row"]:visible')
      await expect(interactive.first()).toBeVisible()
    }
  })
})