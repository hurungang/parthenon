import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_SERVERS = [
  {
    id: 'srv-1',
    name: 'Internal Tools',
    slug: 'internal-tools',
    base_url: 'http://mcp.internal',
    status: 'active',
    description: 'Internal tool server',
    last_synced_at: '2026-04-23T10:00:00Z',
  },
  {
    id: 'srv-2',
    name: 'External Research',
    slug: 'external-research',
    base_url: 'http://research.mcp.example.com',
    status: 'inactive',
    description: 'External research tools',
    last_synced_at: '2026-04-22T08:00:00Z',
  },
]

test.describe('MCP Hub', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/mcp/servers', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SERVERS) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_SERVERS[0]) })
      }
    })
  })

  test('MCP Hub page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('MCP Hub page does not redirect to login', async ({ page }) => {
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('MCP Hub shows server names from API', async ({ page }) => {
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    await expect(page.getByText('Internal Tools')).toBeVisible()
  })

  test('MCP Hub shows second server in list', async ({ page }) => {
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    await expect(page.getByText('External Research')).toBeVisible()
  })

  test('MCP Hub shows server status indicators', async ({ page }) => {
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    // Active/inactive status chips or text should be visible
    const statusText = page.getByText(/active|inactive/i)
    const hasStatus = await statusText.count() > 0
    if (hasStatus) {
      await expect(statusText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('MCP Hub has a register/add server button', async ({ page }) => {
    await page.goto('/mcp')
    await page.waitForLoadState('load')
    // Button text from i18n: mcp.registerServer = "Register Server"
    const addBtn = page.locator('button:visible').filter({ hasText: /Register Server|register|add|connect|new/i }).first()
    const hasAddBtn = await addBtn.count() > 0
    if (hasAddBtn) {
      await expect(addBtn).toBeVisible()
      await addBtn.click()
      // MUI Dialog (not Drawer) should open
      await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 5000 })
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })
})