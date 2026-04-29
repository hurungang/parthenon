import { test, expect } from '@playwright/test';

test.describe('Page Consistency', () => {
  test.beforeEach(async ({ page }) => {
    // Mock all API responses
    await page.route('**/api/v1/**', route => route.fulfill({ 
      json: { data: [], items: [], total: 0 } 
    }));
  });

  const pages = [
    { name: 'Dashboard', path: '/' },
    { name: 'MCP Hub', path: '/mcp-hub' },
    { name: 'Skills', path: '/skills' },
    { name: 'Agents', path: '/agents' },
    { name: 'Conversations', path: '/conversations' },
  ];

  for (const { name, path } of pages) {
    test(`${name} uses theme consistently`, async ({ page }) => {
      await page.goto(path);
      
      // Wait for page to render
      await page.waitForLoadState('networkidle');
      
      // Check Inter font
      const fontFamily = await page.evaluate(() => {
        return window.getComputedStyle(document.body).fontFamily;
      });
      expect(fontFamily).toContain('Inter');
      
      // Check background color (slate)
      const bgColor = await page.evaluate(() => {
        return window.getComputedStyle(document.body).backgroundColor;
      });
      expect(bgColor).toContain('rgb(248, 250, 252)');
      
      // No console errors
      const errors: string[] = [];
      page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
      });
      
      expect(errors).toHaveLength(0);
    });
  }
});
