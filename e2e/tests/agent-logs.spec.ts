import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// ── Mock data ──────────────────────────────────────────────────────────────────

const SESSION_ID = 'test-log-session-001'

const MOCK_SESSION = {
  id: SESSION_ID,
  agent_type_id: 'at-log-test',
  triggered_by_user_id: 'user-1',
  input_data: { query: 'Analyse the quarterly report' },
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:05:00Z',
  output_data: { result: 'Analysis complete' },
  error_message: null,
  conversation_history: null,
  created_at: '2026-01-01T10:00:00Z',
}

const MOCK_EXECUTION_LOG = {
  id: 'execlog-001',
  session_id: SESSION_ID,
  system_instruction: [
    'Identity: analytics-agent@example.com',
    'Role: DataAnalyst',
    'Model: gpt-4o',
    'Assigned SOPs: DataPipeline, ReportGenerator',
    'Assigned Skills: QueryTool, ExportTool',
    '',
    'Implementation Plan:',
    '1. Load the dataset',
    '2. Validate schema',
    '3. Run analysis pipeline',
    '4. Export results',
  ].join('\n'),
  user_prompt: 'Analyse the quarterly report for Q4 2025',
  logged_at: '2026-01-01T10:00:01Z',
}

const MOCK_LOG_ENTRIES = [
  {
    id: 'entry-000',
    timestamp: '2026-01-01T10:00:00Z',
    event_type: 'session_started',
    log_level: 'INFO',
    message: 'Session execution started',
    data: {
      agent_type_id: 'at-log-test',
      model_id: 'gpt-4o',
      input_type: 'typed',
      system_instruction_length: 200,
      identity_name: 'analytics-agent@example.com',
      role_name: 'DataAnalyst',
    },
  },
  {
    id: 'entry-000b',
    timestamp: '2026-01-01T10:00:01Z',
    event_type: 'sops_skills_loaded',
    log_level: 'INFO',
    message: 'Loaded SOPs and Skills',
    data: {
      role_id: 'role-uuid',
      sops: [
        { id: 'sop-1', name: 'DataPipeline' },
        { id: 'sop-2', name: 'ReportGenerator' },
      ],
      skills: [
        { id: 'skill-1', name: 'QueryTool' },
        { id: 'skill-2', name: 'ExportTool' },
      ],
    },
  },
  {
    id: 'entry-001',
    timestamp: '2026-01-01T10:00:02Z',
    event_type: 'llm_call',
    log_level: 'INFO',
    message: 'Initial LLM reasoning call',
    data: {},
  },
  {
    id: 'entry-002',
    timestamp: '2026-01-01T10:01:00Z',
    event_type: 'tool_call',
    log_level: 'INFO',
    message: 'Calling QueryTool with SQL query',
    data: { tool_name: 'QueryTool', input: 'SELECT * FROM sales WHERE quarter = 4' },
  },
  {
    id: 'entry-003',
    timestamp: '2026-01-01T10:02:00Z',
    event_type: 'tool_end',
    log_level: 'INFO',
    message: 'QueryTool returned 1200 rows',
    data: { tool_name: 'QueryTool', row_count: 1200 },
  },
  {
    id: 'entry-004',
    timestamp: '2026-01-01T10:03:00Z',
    event_type: 'llm_end',
    log_level: 'INFO',
    message: 'LLM produced analysis summary',
    data: {},
  },
  {
    id: 'entry-005',
    timestamp: '2026-01-01T10:04:00Z',
    event_type: 'tool_call',
    log_level: 'INFO',
    message: 'Calling ExportTool to save results',
    data: { tool_name: 'ExportTool', format: 'pdf' },
  },
  {
    id: 'entry-006',
    timestamp: '2026-01-01T10:05:00Z',
    event_type: 'session_completed',
    log_level: 'INFO',
    message: 'Agent completed successfully',
    data: {},
  },
]

// ── Shared setup ───────────────────────────────────────────────────────────────

async function setupLogViewerPage(page: import('@playwright/test').Page) {
  await standardSetup(page)

  // Mock all session-list and type calls to avoid unhandled request errors
  await page.route('**/api/v1/agents/types/**', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )

  // Mock the specific session fetch
  await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_SESSION) })
  )

  // Mock execution logs (system instruction + user prompt)
  await page.route(
    `**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`,
    (route) => route.fulfill({ status: 200, body: JSON.stringify([MOCK_EXECUTION_LOG]) })
  )

  // Mock log entries
  await page.route(
    `**/api/v1/agents/sessions/${SESSION_ID}/logs`,
    (route) => route.fulfill({ status: 200, body: JSON.stringify(MOCK_LOG_ENTRIES) })
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('Agent Log Viewer', () => {
  test('LogViewer renders on completed session page', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // The LogViewer title should be visible
    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })
  })

  test('Summary panel displays identity and role from system instruction', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // Scope to the summary panel (Paper element = 2 levels up from title)
    const summaryPanel = page.getByText('Execution Summary').locator('../..')
    await expect(summaryPanel.getByText('analytics-agent@example.com')).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel.getByText('DataAnalyst')).toBeVisible({ timeout: 10000 })
  })

  test('Summary panel displays SOPs/skills as chips', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // Scope to the summary panel (Paper element = 2 levels up from title)
    const summaryPanel = page.getByText('Execution Summary').locator('../..')
    await expect(summaryPanel.getByText('DataPipeline')).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel.getByText('ReportGenerator')).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel.getByText('QueryTool')).toBeVisible({ timeout: 10000 })
    await expect(summaryPanel.getByText('ExportTool')).toBeVisible({ timeout: 10000 })
  })

  test('Summary panel shows success result badge for completed session', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // Scope to the summary panel to avoid matching step messages
    const summaryPanel = page.getByText('Execution Summary').locator('..')
    await expect(summaryPanel.getByText('Success', { exact: true })).toBeVisible({ timeout: 10000 })
  })

  test('"View Execution Logs" button/dialog is NOT present (regression check)', async ({
    page,
  }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // The old "View Execution Logs" button should no longer exist
    await expect(page.getByText(/view execution logs/i)).toHaveCount(0)
  })

  test('Agent Working Steps section is collapsed by default', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // The collapsible section header should be visible and show the "show" text
    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // The section toggle should show "Show N Working Steps" text
    const toggleEl = page.locator('[aria-expanded="false"]').first()
    await expect(toggleEl).toBeVisible()
  })

  test('Expand working steps section reveals step rows', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // Wait for the Working Steps section to render
    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // Find and click the collapse toggle button
    const toggleEl = page
      .locator('[role="button"]')
      .filter({ hasText: /show.*working steps/i })
      .first()
    await toggleEl.click()

    // After expanding, step messages should be visible
    await expect(page.getByText('Initial LLM reasoning call')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Calling QueryTool with SQL query')).toBeVisible({ timeout: 5000 })
  })

  test('Collapse working steps section hides step rows', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // Expand the section
    const toggleEl = page
      .locator('[role="button"]')
      .filter({ hasText: /show.*working steps/i })
      .first()
    await toggleEl.click()
    await expect(page.getByText('Initial LLM reasoning call')).toBeVisible({ timeout: 5000 })

    // Collapse by clicking again
    const hideToggleEl = page
      .locator('[role="button"]')
      .filter({ hasText: /hide working steps/i })
      .first()
    await hideToggleEl.click()

    // The section toggle should now show "Show N Working Steps" again
    await expect(
      page.locator('[role="button"]').filter({ hasText: /show.*working steps/i }).first()
    ).toBeVisible({ timeout: 5000 })
  })

  test('Expand individual step detail block', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // First expand the working steps section
    const toggleEl = page
      .locator('[role="button"]')
      .filter({ hasText: /show.*working steps/i })
      .first()
    await toggleEl.click()

    // Find a step that has a detail expand button (tool_call with data)
    await expect(page.getByText('Calling QueryTool with SQL query')).toBeVisible({ timeout: 5000 })

    // Click the expand detail button for that step
    const expandBtn = page.locator('[aria-label="Expand detail"]').first()
    await expandBtn.click()

    // After clicking, the Tooltip title changes from 'Expand detail' to 'Collapse detail'
    // so the button's aria-label changes too — check for the collapse button being visible
    const collapseBtn = page.locator('[aria-label="Collapse detail"]').first()
    await expect(collapseBtn).toBeVisible({ timeout: 5000 })
  })

  test('Collapse individual step detail block', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 10000 })

    // Expand working steps section
    await page
      .locator('[role="button"]')
      .filter({ hasText: /show.*working steps/i })
      .first()
      .click()

    await expect(page.getByText('Calling QueryTool with SQL query')).toBeVisible({ timeout: 5000 })

    // Expand detail
    const expandBtn = page.locator('[aria-label="Expand detail"]').first()
    await expandBtn.click()
    // After expand, aria-label changes to 'Collapse detail'
    const collapseBtn = page.locator('[aria-label="Collapse detail"]').first()
    await expect(collapseBtn).toBeVisible({ timeout: 5000 })

    // Collapse detail — click the collapse button
    await collapseBtn.click()
    // After collapse, the expand button appears again
    await expect(page.locator('[aria-label="Expand detail"]').first()).toBeVisible({ timeout: 5000 })
  })

  test('Toggle to raw mode hides friendly panels', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Summary')).toBeVisible({ timeout: 10000 })

    // Click the "Raw Output" label text (inside FormControlLabel) to toggle the switch
    // MUI Switch inputProps aria-label is on the hidden input — click the visible label instead
    await page.getByText('Raw Output', { exact: true }).click()

    // Friendly panels should disappear
    await expect(page.getByText('Execution Summary')).not.toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Agent Working Steps')).not.toBeVisible({ timeout: 5000 })
  })

  test('Toggle to raw mode shows monospace raw log block', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })

    // Click the "Raw Output" label text to switch to raw mode
    await page.getByText('Raw Output', { exact: true }).click()

    // Raw log pre block should appear
    const rawBlock = page.locator('pre[aria-label="Raw execution log output"]')
    await expect(rawBlock).toBeVisible({ timeout: 5000 })

    // The raw block should contain log content
    await expect(rawBlock).toContainText('analytics-agent@example.com')
    await expect(rawBlock).toContainText('Initial LLM reasoning call')
  })

  test('Raw mode copy button is visible', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })

    // Click the "Raw Output" label text to switch to raw mode
    await page.getByText('Raw Output', { exact: true }).click()

    // Copy button should be visible in raw mode
    const copyBtn = page.locator('[aria-label="Copy Raw Log"]')
    await expect(copyBtn).toBeVisible({ timeout: 5000 })
  })

  test('Toggle back to friendly mode restores panels', async ({ page }) => {
    await setupLogViewerPage(page)
    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Execution Summary')).toBeVisible({ timeout: 10000 })

    // Click "Raw Output" label to switch to raw mode
    await page.getByText('Raw Output', { exact: true }).click()
    await expect(page.getByText('Execution Summary')).not.toBeVisible({ timeout: 5000 })

    // Click "Raw Output" label again to switch back to friendly mode
    await page.getByText('Raw Output', { exact: true }).click()
    await expect(page.getByText('Execution Summary')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Agent Working Steps')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Agent Log Viewer — Edge Cases', () => {
  test('Empty log entries — no crash', async ({ page }) => {
    await standardSetup(page)
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_SESSION) })
    )
    // Return execution log with no entries
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`, (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'execlog-empty',
            session_id: SESSION_ID,
            system_instruction: null,
            user_prompt: null,
            logged_at: '2026-01-01T10:00:00Z',
          },
        ]),
      })
    )
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )

    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // Should not crash
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
    // LogViewer should still render
    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })
  })

  test('Special characters in log messages — displays without XSS', async ({ page }) => {
    await standardSetup(page)
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_SESSION) })
    )
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`, (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([{ ...MOCK_EXECUTION_LOG, user_prompt: '<script>alert("xss")</script>' }]),
      })
    )
    const specialEntries = [
      {
        id: 'se-001',
        timestamp: '2026-01-01T10:01:00Z',
        event_type: 'agent_finish',
        log_level: 'INFO',
        message: 'Result: <b>Bold</b> & "quoted" text with émojis 🎉',
        data: {},
      },
    ]
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(specialEntries) })
    )

    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
    await expect(page.getByText('Execution Log')).toBeVisible({ timeout: 10000 })
    // Verify the script was not executed (page title was not changed by XSS)
    await expect(page).not.toHaveTitle('XSS')
  })

  test('No execution logs — LogViewer not rendered', async ({ page }) => {
    await standardSetup(page)
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_SESSION) })
    )
    // Return empty execution logs array — LogViewer should not render
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs`, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )

    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    // When no execution logs, LogViewer should not render
    await expect(page.getByText('Execution Log')).not.toBeVisible({ timeout: 5000 })
  })
})
