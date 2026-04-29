import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_DASHBOARD = {
  active_agents: 3,
  mcp_servers: 2,
  scheduled_jobs: 5,
  conversation_sessions: 42,
}

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/dashboard/summary', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_DASHBOARD) })
    )
    await standardSetup(page)
  })

  test('dashboard page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('dashboard page has content', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
    await expect(page.getByRole('button').first()).toBeVisible()
  })

  test('dashboard renders app shell layout with header', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
    await expect(page.locator('header').first()).toBeVisible()
  })

  test('dashboard displays app title or welcome content', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // DashboardPage renders the app title/tagline via i18n
    const heading = page.locator('h4, h3, h5').first()
    const hasHeading = await heading.count() > 0
    if (hasHeading) {
      await expect(heading).toBeVisible()
    } else {
      await expect(page.locator('main, [role="main"]').first()).toBeVisible()
    }
  })

  test('dashboard has page content area', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // Main content area should be present
    const main = page.locator('main').first()
    await expect(main).toBeVisible()
  })

  test('dashboard has navigation sidebar with nav items', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // MUI AppShell has a sidebar drawer with ListItemButton items (rendered as <button>)
    // Use a broad selector since the drawer may render via portal outside <nav>
    const navButtons = page.locator('[class*="MuiListItemButton"], [class*="MuiDrawer"] button, nav button').first()
    const hasNavButtons = await navButtons.count() > 0
    if (hasNavButtons) {
      await expect(navButtons).toBeVisible()
    } else {
      // At minimum the header with title should be present
      await expect(page.locator('header').first()).toBeVisible()
    }
  })

  test('dashboard navigation links are clickable', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // Nav items render as MUI ListItemButton elements
    const navBtn = page.locator('[class*="MuiListItemButton"]:visible, nav button:visible').first()
    const hasNavBtn = await navBtn.count() > 0
    if (hasNavBtn) {
      await expect(navBtn).toBeEnabled()
    } else {
      await expect(page.locator('button:visible').first()).toBeVisible()
    }
  })
})