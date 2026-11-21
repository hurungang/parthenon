import { expect, test } from '@playwright/test'

/**
 * The GitHub Pages showcase is a separate static build (`site/dist`), not the
 * application served by the default Playwright webServer. Run it explicitly:
 *   SHOWCASE_URL=http://localhost:4180 npx playwright test tests/github-pages-showcase.spec.ts
 * (serve `site/dist` on that port first). Static-content coverage also lives in
 * `backend/tests/unit/test_github_pages_showcase_site.py` and the frontend
 * service-decomposition suite.
 */
const SHOWCASE_URL = process.env.SHOWCASE_URL

test.describe('GitHub Pages showcase page', () => {
  test.skip(!SHOWCASE_URL, 'Set SHOWCASE_URL to run against the static showcase build (site/dist)')

  test('renders core sections and switches walkthrough tabs', async ({ page }) => {
    await page.goto(SHOWCASE_URL as string)

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
