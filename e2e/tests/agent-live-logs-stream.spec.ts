import { expect, test } from '@playwright/test'
import { standardSetup } from './_helpers'

const SESSION_ID = 'stream-session-001'

test.describe('Agent Live Logs Stream', () => {
  test('uses live stream endpoint for running non-conversation session and shows live-stream hint', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    )

    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: SESSION_ID,
          agent_type_id: 'at-1',
          triggered_by_user_id: 'user-1',
          input_data: { query: 'non-conversation run' },
          status: 'running',
          started_at: '2026-05-29T10:00:00Z',
          completed_at: null,
          output_data: null,
          error_message: null,
          conversation_history: null,
          created_at: '2026-05-29T10:00:00Z',
        }),
      }),
    )

    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/execution-logs`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    )

    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    )

    await page.route(`**/api/v1/agents/sessions/${SESSION_ID}/logs/stream`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/x-ndjson',
        body: [
          JSON.stringify({
            type: 'log_entry',
            entry: {
              id: 'stream-entry-1',
              timestamp: '2026-05-29T10:00:05Z',
              event_type: 'system',
              log_level: 'INFO',
              message: 'streamed progress event',
              data: { step: 1 },
            },
          }),
          JSON.stringify({
            type: 'stream_completed',
            session_id: SESSION_ID,
            session_status: 'completed',
          }),
          '',
        ].join('\n'),
      }),
    )

    const streamRequest = page.waitForRequest(
      (req) => req.url().includes(`/api/v1/agents/sessions/${SESSION_ID}/logs/stream`) && req.method() === 'GET',
    )

    await page.goto(`/agents/sessions/${SESSION_ID}`)
    await page.waitForLoadState('networkidle')

    await streamRequest
    await expect(page.getByText(/Live stream:/)).toBeVisible()
  })
})
