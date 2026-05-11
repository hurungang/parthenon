import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { standardSetup } from './_helpers'

// ── Mock data for log viewer accessibility tests ────────────────────────────────

const LOG_SESSION_ID = 'a11y-log-session-001'

const MOCK_A11Y_SESSION = {
  id: LOG_SESSION_ID,
  agent_type_id: 'at-a11y',
  triggered_by_user_id: 'user-1',
  input_data: null,
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:05:00Z',
  output_data: { result: 'done' },
  error_message: null,
  conversation_history: null,
  created_at: '2026-01-01T10:00:00Z',
}

const MOCK_A11Y_EXECUTION_LOG = {
  id: 'execlog-a11y',
  session_id: LOG_SESSION_ID,
  system_instruction:
    'Identity: bot@example.com\nRole: Analyst\nModel: gpt-4o\nAssigned SOPs: AnalysisSOP\n',
  user_prompt: 'Run the analysis',
  logged_at: '2026-01-01T10:00:01Z',
}

const MOCK_A11Y_LOG_ENTRIES = [
  {
    id: 'a11y-entry-001',
    timestamp: '2026-01-01T10:01:00Z',
    event_type: 'llm_call',
    log_level: 'INFO',
    message: 'LLM call started',
    data: {},
  },
  {
    id: 'a11y-entry-002',
    timestamp: '2026-01-01T10:05:00Z',
    event_type: 'agent_finish',
    log_level: 'INFO',
    message: 'Agent finished',
    data: {},
  },
]

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

// ── Log Viewer Accessibility Tests ─────────────────────────────────────────────

test.describe('Accessibility — Log Viewer Controls', () => {
  async function setupLogViewerA11y(page: import('@playwright/test').Page) {
    await standardSetup(page)
    await page.route(`**/api/v1/agents/sessions/${LOG_SESSION_ID}`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_A11Y_SESSION) })
    )
    await page.route(`**/api/v1/agents/sessions/${LOG_SESSION_ID}/execution-logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_A11Y_EXECUTION_LOG]) })
    )
    await page.route(`**/api/v1/agents/sessions/${LOG_SESSION_ID}/logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_A11Y_LOG_ENTRIES) })
    )
  }

  test('Raw log toggle has accessible label via FormControlLabel', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })

    // The toggle is wrapped in a FormControlLabel with "Raw Output" text.
    // Screen readers announce the switch via this label association.
    // Verify the label text is visible (provides accessible context).
    const rawLabel = page.locator('label').filter({ hasText: 'Raw Output' })
    await expect(rawLabel).toBeVisible({ timeout: 5000 })
  })

  test('Collapsible working steps section has aria-expanded attribute', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // The collapsible toggle must expose its expanded state via aria-expanded
    const toggleEl = page.locator('[role="button"][aria-expanded]').first()
    await expect(toggleEl).toBeVisible({ timeout: 5000 })
    await expect(toggleEl).toHaveAttribute('aria-expanded', 'false')
  })

  test('Collapsible section is keyboard-navigable with Tab', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // Tab through the page until we reach the collapsible toggle
    const toggleEl = page.locator('[role="button"][aria-expanded]').first()
    await toggleEl.focus()

    // The toggle should be focusable (tabindex="0")
    const tabIndex = await toggleEl.getAttribute('tabindex')
    expect(tabIndex).toBe('0')
  })

  test('Collapsible section responds to Enter key', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    const toggleEl = page.locator('[role="button"][aria-expanded]').first()
    await toggleEl.focus()

    // Press Enter to expand
    await page.keyboard.press('Enter')
    await expect(toggleEl).toHaveAttribute('aria-expanded', 'true', { timeout: 3000 })
  })

  test('Collapsible section responds to Space key', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    const toggleEl = page.locator('[role="button"][aria-expanded]').first()
    await toggleEl.focus()

    // Press Space to expand
    await page.keyboard.press(' ')
    await expect(toggleEl).toHaveAttribute('aria-expanded', 'true', { timeout: 3000 })
  })

  test('Raw log block has ARIA label when visible', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })

    // Toggle to raw mode via the "Raw Output" FormControlLabel
    await page.getByText('Raw Output', { exact: true }).click()

    // Raw log pre block should have its aria-label
    const rawBlock = page.locator('[aria-label="Raw execution log output"]')
    await expect(rawBlock).toBeVisible({ timeout: 5000 })
  })

  test('Copy button has ARIA label when in raw mode', async ({ page }) => {
    await setupLogViewerA11y(page)
    await page.goto(`/agents/sessions/${LOG_SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })

    // Toggle to raw mode via the "Raw Output" FormControlLabel
    await page.getByText('Raw Output', { exact: true }).click()

    // The copy button should have an accessible label
    const copyBtn = page.locator('[aria-label="Copy Raw Log"]')
    await expect(copyBtn).toBeVisible({ timeout: 5000 })
  })
})
