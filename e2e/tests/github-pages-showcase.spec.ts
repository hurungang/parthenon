import { expect, test } from '@playwright/test'

test.describe('GitHub Pages showcase page', () => {
  test('renders core sections and switches walkthrough tabs', async ({ page }) => {
    await page.goto('/')

    await expect(page.getByRole('heading', { name: 'High-Level Architecture' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Security Deep Dive' })).toBeVisible()

    await page.locator('.tab-pill[data-tab="tab-skill"]').click()
    await expect(page.locator('#tab-skill')).toHaveClass(/active/)

    await page.locator('.tab-pill[data-tab="tab-role"]').click()
    await expect(page.locator('#tab-role')).toHaveClass(/active/)

    await page.locator('.tab-pill[data-tab="tab-agent"]').click()
    await expect(page.locator('#tab-agent')).toHaveClass(/active/)

    await page.locator('.tab-pill[data-tab="tab-logs"]').click()
    await expect(page.locator('#tab-logs')).toHaveClass(/active/)
    await expect(page.locator('#tab-logs img[alt*=\"placeholder\"]')).toBeVisible()
  })
})
