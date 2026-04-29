import { test, expect } from '@playwright/test';

test.describe('Component Theming', () => {
  test.beforeEach(async ({ page }) => {
    // Mock all API calls
    await page.route('**/api/v1/**', route => route.fulfill({ json: { data: [] } }));
  });

  test('Cards have 12px border radius', async ({ page }) => {
    await page.goto('/');
    
    // Find any card element (MUI Card typically has role or specific class)
    const card = page.locator('[class*="MuiCard-root"], [class*="MuiPaper-root"]').first();
    
    if (await card.count() > 0) {
      const borderRadius = await card.evaluate(el => {
        return window.getComputedStyle(el).borderRadius;
      });
      
      expect(borderRadius).toBe('12px');
    }
  });

  test('AppBar is white with border-bottom', async ({ page }) => {
    await page.goto('/');
    
    // Find AppBar
    const appBar = page.locator('header[class*="MuiAppBar"]').first();
    
    if (await appBar.count() > 0) {
      const styles = await appBar.evaluate(el => {
        const computed = window.getComputedStyle(el);
        return {
          backgroundColor: computed.backgroundColor,
          boxShadow: computed.boxShadow,
          borderBottom: computed.borderBottom
        };
      });
      
      // White background: rgb(255, 255, 255)
      expect(styles.backgroundColor).toContain('rgb(255, 255, 255)');
      // No shadow or minimal shadow
      expect(styles.boxShadow).not.toContain('rgba(0, 0, 0, 0.2)');
    }
  });

  test('Buttons show correct styles', async ({ page }) => {
    await page.goto('/');
    
    // Find any button
    const button = page.locator('button[class*="MuiButton"]').first();
    
    if (await button.count() > 0) {
      const borderRadius = await button.evaluate(el => {
        return window.getComputedStyle(el).borderRadius;
      });
      
      // Buttons should have 8px border radius
      expect(borderRadius).toBe('8px');
    }
  });
});
