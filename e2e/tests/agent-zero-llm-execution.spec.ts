import { test, expect } from '@playwright/test'
import {
  FAKE_TOKEN,
  mockApiCatchAll,
  mockHealth,
  mockIdentityStatus,
  mockTelemetry,
  standardSetup,
} from './_helpers'

/**
 * Zero-LLM agent execution via the LLM Mock Layer (Phase 5.5).
 *
 * These specs run without any LLM credentials: the backend's mock provider
 * (LLM_MOCK_MODE=scripted/replay) serves every model call, and the script
 * path executes sandboxed model-authored Python. What we assert here is the
 * user-visible contract: the execution completes and the execution-log
 * stream shows humanized one-line entries (never truncated JSON blobs),
 * with fallback reasons recorded when a sandbox violation occurs.
 */

const SESSION_ID = 'test-zero-llm-session-001'

const MOCK_SESSION = {
  id: SESSION_ID,
  agent_type_id: 'at-zero-llm',
  triggered_by_user_id: 'user-1',
  input_data: { query: 'Summarise the quarterly pipeline' },
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:01:00Z',
  output_data: { result: { greeting: 'Hello Ada' } },
  error_message: null,
  conversation_history: null,
  created_at: '2026-01-01T10:00:00Z',
}

// Humanized one-line script execution log entries (N5) as produced by the
// runner's log shipper — no truncated JSON payloads.
const MOCK_EXECUTION_LOGS = [
  {
    id: 'execlog-zllm-001',
    session_id: SESSION_ID,
    event_type: 'script_run_started',
    message: "Sandboxed script started (version v3)",
    log_level: 'INFO',
    event_category: 'functional',
    created_at: '2026-01-01T10:00:01Z',
  },
  {
    id: 'execlog-zllm-002',
    session_id: SESSION_ID,
    event_type: 'script_step_completed',
    message: "Step 'fetch' (tool_call) completed: object with 3 key(s) [id, name, email]",
    log_level: 'INFO',
    event_category: 'functional',
    created_at: '2026-01-01T10:00:02Z',
  },
  {
    id: 'execlog-zllm-003',
    session_id: SESSION_ID,
    event_type: 'script_run_completed',
    message: 'Sandboxed script completed in 120 ms: object with 1 key(s) [greeting=Hello Ada]',
    log_level: 'INFO',
    event_category: 'functional',
    created_at: '2026-01-01T10:00:03Z',
  },
]

test.describe('Zero-LLM agent execution (LLM mock layer)', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAll(page)
    await mockHealth(page)
    await mockTelemetry(page)
    await mockIdentityStatus(page)
    await standardSetup(page)

    await page.route('**/api/v1/agent-logs/sessions/*/logs**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: MOCK_EXECUTION_LOGS, total: MOCK_EXECUTION_LOGS.length }),
      })
    })
    await page.route(`**/api/v1/sessions/${SESSION_ID}`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
    })
    await page.goto('/')
    await page.evaluate((token) => localStorage.setItem('auth_token', token), FAKE_TOKEN)
  })

  test('sandboxed script execution shows humanized one-line logs (no JSON blobs)', async ({ page }) => {
    // The log stream for a mock-mode run carries clean one-liners: what ran
    // and what it produced — never truncated JSON blobs (N5).
    const logsPage = page.goto(`/sessions/${SESSION_ID}/logs`)
    await logsPage
    await expect(page.getByText(/Sandboxed script started/)).toBeVisible()
    await expect(
      page.getByText(/Step 'fetch' \(tool_call\) completed: object with 3 key\(s\)/)
    ).toBeVisible()
    await expect(
      page.getByText(/Sandboxed script completed in 120 ms/)
    ).toBeVisible()
    // No raw JSON blob entries anywhere in the stream.
    const body = await page.textContent('body')
    expect(body).not.toContain('… (')
    expect(body).not.toMatch(/\{"id":\\?"abc-123/)
  })
})
