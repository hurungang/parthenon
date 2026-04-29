import { test, expect } from '@playwright/test';

test.describe('Theme Application', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API responses
    await page.route('**/api/v1/health', route => route.fulfill({ json: { status: 'healthy' } }));
    await page.route('**/api/v1/**', route => route.fulfill({ json: {} }));
  });

  test('Inter font is applied globally', async ({ page }) => {
    await page.goto('/');
    
    // Check computed font-family on body or main element
    const fontFamily = await page.evaluate(() => {
      return window.getComputedStyle(document.body).fontFamily;
    });
    
    expect(fontFamily).toContain('Inter');
  });

  test('Primary color is indigo on active navigation', async ({ page }) => {
    await page.goto('/');
    
    // Find an active nav item (dashboard is usually active on home)
    const activeNav = page.locator('[aria-current="page"]').first();
    
    if (await activeNav.count() > 0) {
      const color = await activeNav.evaluate(el => {
        return window.getComputedStyle(el).color;
      });
      
      // Indigo #4f46e5 converts to rgb(79, 70, 229)
      expect(color).toContain('rgb(79, 70, 229)');
    }
  });

  test('Background colors match theme', async ({ page }) => {
    await page.goto('/');
    
    // Check main background is slate
    const bgColor = await page.evaluate(() => {
      return window.getComputedStyle(document.body).backgroundColor;
    });
    
    // #f8fafc converts to rgb(248, 250, 252)
    expect(bgColor).toContain('rgb(248, 250, 252)');
  });
});
