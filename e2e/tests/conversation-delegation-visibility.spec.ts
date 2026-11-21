import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

import { standardSetup } from './_helpers'

/**
 * Conversation delegation visibility.
 *
 * `ChatPage` mounts `ConversationDialog` with `testIdPrefix="chat"`, so every
 * `testId('x')` inside the dialog surfaces as `chat-x` — and the status ids were
 * already named `chat-status-*`, giving `chat-chat-status-indicator` /
 * `chat-chat-status-terminal`.
 *
 * Delegation progress is rendered inline in the active delegation cycle: the
 * intro line ("Delegating to agent …"), a live status line, then a compact
 * `DelegationMiniLog` (no fold/expand toggle — the log lines are always shown
 * for the active cycle).
 */

const DELEGATED_SESSION_ID = 'delegated-session-1'

async function mockChatResumeRoutes(page: Page) {
  await page.route('**/api/v1/agents/types', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: 'agent-type-1', name: 'Coordinator Agent', is_active: true }]),
    })
  )

  await page.route('**/api/v1/conversations/session-1/resume', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'session-1',
        agent_type_id: 'agent-type-1',
        turns: [],
      }),
    })
  )

  // Delegated sub-agent activity shown inline in the delegation cycle.
  await page.route(`**/api/v1/agents/sessions/${DELEGATED_SESSION_ID}/logs`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'delegated-log-1',
          session_id: DELEGATED_SESSION_ID,
          timestamp: '2026-06-17T12:00:10Z',
          event_type: 'tool_call',
          log_level: 'INFO',
          event_category: 'functional',
          message: 'Searching knowledge base',
          data: { tool_name: 'knowledge_search' },
        },
      ]),
    })
  )

  await page.route(`**/api/v1/agents/sessions/${DELEGATED_SESSION_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: DELEGATED_SESSION_ID,
        agent_type_id: 'agent-type-2',
        agent_type_name: 'Research Agent',
        triggered_by_user_id: null,
        triggered_by_user_name: null,
        input_data: null,
        status: 'running',
        started_at: '2026-06-17T12:00:05Z',
        completed_at: null,
        output_data: null,
        error_message: null,
        conversation_history: null,
        created_at: '2026-06-17T12:00:05Z',
      }),
    })
  )
}

async function installMockWebSocket(
  page: Page,
  scenario: 'waiting' | 'timeout_or_failed'
) {
  await page.addInitScript((chosen) => {
    class MockWebSocket {
      static OPEN = 1
      readyState = MockWebSocket.OPEN
      onopen: ((ev: Event) => void) | null = null
      onmessage: ((ev: MessageEvent) => void) | null = null
      onclose: ((ev: CloseEvent) => void) | null = null
      onerror: ((ev: Event) => void) | null = null

      constructor() {
        setTimeout(() => {
          this.onopen?.(new Event('open'))

          this.onmessage?.(
            new MessageEvent('message', {
              data: JSON.stringify({
                type: 'chat_status',
                status: 'thinking',
                timestamp: new Date().toISOString(),
              }),
            })
          )

          this.onmessage?.(
            new MessageEvent('message', {
              data: JSON.stringify({
                type: 'chat_status',
                status: 'delegating',
                agent_type: 'agent____research-agent',
                receiver_session_id: 'delegated-session-1',
                timestamp: new Date().toISOString(),
              }),
            })
          )

          if (chosen === 'waiting') {
            this.onmessage?.(
              new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'chat_status',
                  status: 'waiting',
                  agent_type: 'agent__research-agent',
                  receiver_session_id: 'delegated-session-1',
                  timestamp: new Date().toISOString(),
                }),
              })
            )
          } else {
            this.onmessage?.(
              new MessageEvent('message', {
                data: JSON.stringify({
                  type: 'chat_status',
                  status: 'timeout_or_failed',
                  timestamp: new Date().toISOString(),
                }),
              })
            )
          }
        }, 0)
      }

      send() {}

      close() {
        this.onclose?.(new CloseEvent('close'))
      }
    }

    Object.defineProperty(window, 'WebSocket', {
      writable: true,
      value: MockWebSocket,
    })
  }, scenario)
}

test.describe('Conversation Delegation Visibility', () => {
  test('shows delegating label and waiting indicator with inline delegation snippet log', async ({ page }) => {
    await standardSetup(page)
    await mockChatResumeRoutes(page)
    await installMockWebSocket(page, 'waiting')

    await page.goto('/agents/agent-type-1/chat/session-1')
    await page.waitForLoadState('load')

    const statusIndicator = page.getByTestId('chat-chat-status-indicator')
    await expect(statusIndicator.first()).toBeVisible()
    await expect(page.getByText('Delegating to agent research-agent')).toBeVisible()
    await expect(
      statusIndicator.first().getByText('Waiting for delegated response…')
    ).toBeVisible()

    // The active delegation cycle always shows its sub-agent log lines inline
    // (there is no fold/expand toggle).
    const snippetsPanel = page.getByTestId('chat-delegation-snippets')
    await expect(snippetsPanel).toBeVisible()
    await expect(snippetsPanel.getByText('Searching knowledge base')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Show Details' })).toHaveCount(0)
  })

  test('shows timeout_or_failed terminal status in chat', async ({ page }) => {
    await standardSetup(page)
    await mockChatResumeRoutes(page)
    await installMockWebSocket(page, 'timeout_or_failed')

    await page.goto('/agents/agent-type-1/chat/session-1')
    await page.waitForLoadState('load')

    await expect(page.getByTestId('chat-chat-status-terminal')).toBeVisible()
    await expect(
      page.getByText('Delegated step timed out or failed. Please try again.')
    ).toBeVisible()
  })
})
