import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('Accessibility', () => {
  test.beforeEach(async ({ page }) => {
    // Mock API responses
    await page.route('**/api/v1/**', route => route.fulfill({ json: { data: [] } }));
  });

  test('Color contrast meets WCAG AA standards', async ({ page }) => {
    await page.goto('/');
    
    // Run axe accessibility scan
    const accessibilityScanResults = await new AxeBuilder({ page })
      .include('body')
      .analyze();
    
    // Check for color contrast violations
    const contrastViolations = accessibilityScanResults.violations.filter(
      v => v.id === 'color-contrast'
    );
    
    expect(contrastViolations).toHaveLength(0);
  });

  test('Focus indicators are visible', async ({ page }) => {
    await page.goto('/');
    
    // Find first focusable element (button or link)
    const focusable = page.locator('button, a').first();
    
    if (await focusable.count() > 0) {
      await focusable.focus();
      
      // Check that outline or other focus indicator exists
      const outline = await focusable.evaluate(el => {
        const computed = window.getComputedStyle(el);
        return {
          outline: computed.outline,
          outlineWidth: computed.outlineWidth,
          boxShadow: computed.boxShadow
        };
      });
      
      // Should have some kind of focus indicator
      const hasFocusIndicator = 
        outline.outlineWidth !== '0px' || 
        outline.boxShadow !== 'none';
      
      expect(hasFocusIndicator).toBe(true);
    }
  });

  test('No critical accessibility violations', async ({ page }) => {
    await page.goto('/');
    
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();
    
    // Filter to critical and serious violations only
    const criticalViolations = accessibilityScanResults.violations.filter(
      v => v.impact === 'critical' || v.impact === 'serious'
    );
    
    expect(criticalViolations).toHaveLength(0);
  });
});
