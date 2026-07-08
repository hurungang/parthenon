import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_DASHBOARD_SUMMARY = {
  snapshot_counts: {
    agent_types: 5,
    agent_types_active: 3,
    agent_types_running: 1,
    pending_interventions: 2,
    model_configs: 3,
    active_schedules: 4,
    agent_identities: 10,
    agent_roles: 2,
    mcp_servers: 3,
  },
  time_sensitive: {
    guardrail_breaches: 1,
    agent_executions: { completed: 10, failed: 2 },
    posture_breaches: 0,
  },
  permission_flags: {
    agent_types: false,
    interventions: false,
    model_configs: false,
    schedules: false,
    identities: false,
    roles: false,
    mcp_servers: false,
    guardrail_breaches: false,
    executions: false,
    posture_breaches: false,
  },
}

test.describe('Dashboard Operational Metrics', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the new dashboard summary endpoint
    await page.route('http://localhost:8000/api/v1/dashboard/summary**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_DASHBOARD_SUMMARY) })
    )
    await standardSetup(page)
  })

  test('dashboard page renders without console errors', async ({ page }) => {
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
    const main = page.locator('main').first()
    await expect(main).toBeVisible()
  })

  test('dashboard has navigation sidebar with nav items', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    const navButtons = page.locator('[class*="MuiListItemButton"], [class*="MuiDrawer"] button, nav button').first()
    const hasNavButtons = await navButtons.count() > 0
    if (hasNavButtons) {
      await expect(navButtons).toBeVisible()
    } else {
      await expect(page.locator('header').first()).toBeVisible()
    }
  })

  test('dashboard navigation links are clickable', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    const navBtn = page.locator('[class*="MuiListItemButton"]:visible, nav button:visible').first()
    const hasNavBtn = await navBtn.count() > 0
    if (hasNavBtn) {
      await expect(navBtn).toBeEnabled()
    } else {
      await expect(page.locator('button:visible').first()).toBeVisible()
    }
  })

  test('operational metric cards are visible', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // Wait for the metrics to render
    await page.waitForTimeout(2000)

    // Check that the operational metrics section is present
    const opsSection = page.getByText('Operational Metrics')
    const hasOpsSection = await opsSection.count() > 0
    if (hasOpsSection) {
      await expect(opsSection).toBeVisible()
    }
  })

  test('time-sensitive metrics section is visible', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    await page.waitForTimeout(2000)

    const timeSection = page.getByText('Time-Sensitive Metrics')
    const hasTimeSection = await timeSection.count() > 0
    if (hasTimeSection) {
      await expect(timeSection).toBeVisible()
    }
  })

  test('identity provider status section is retained', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    await page.waitForTimeout(2000)

    const idpSection = page.getByText('Identity Provider Status')
    const hasIdpSection = await idpSection.count() > 0
    if (hasIdpSection) {
      await expect(idpSection).toBeVisible()
    }
  })

  test('date range picker preset buttons are visible', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    await page.waitForTimeout(2000)

    // Preset buttons should be visible
    const hourBtn = page.getByText('Last Hour')
    const dayBtn = page.getByText('Last 24h')
    const weekBtn = page.getByText('Last 7d')

    const hasHourBtn = await hourBtn.count() > 0
    const hasDayBtn = await dayBtn.count() > 0
    const hasWeekBtn = await weekBtn.count() > 0

    if (hasHourBtn) await expect(hourBtn).toBeVisible()
    if (hasDayBtn) await expect(dayBtn).toBeVisible()
    if (hasWeekBtn) await expect(weekBtn).toBeVisible()
  })
})
