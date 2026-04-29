import { test, expect } from '@playwright/test'

/**
 * Health / smoke E2E tests.
 * Verifies the app loads and is structurally sound.
 */

test.describe('App Health', () => {
  test('app root loads and renders an HTML body', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).not.toBeEmpty()
  })

  test('app renders a root element', async ({ page }) => {
    await page.goto('/')
    // The Vite React app mounts into #root
    await expect(page.locator('#root')).toBeAttached()
  })

  test('no unhandled JavaScript errors on load', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Filter out known benign errors (ResizeObserver, etc.)
    const fatal = errors.filter(
      (e) => !e.includes('ResizeObserver') && !e.includes('Non-Error promise rejection')
    )
    expect(fatal).toHaveLength(0)
  })

  test('page title is set', async ({ page }) => {
    await page.goto('/')
    const title = await page.title()
    expect(title.length).toBeGreaterThan(0)
  })

  test('navigating to unknown path renders something', async ({ page }) => {
    await page.goto('/this-path-does-not-exist')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('body')).not.toBeEmpty()
  })
})
