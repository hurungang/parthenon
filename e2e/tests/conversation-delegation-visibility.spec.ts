import { expect, test } from '@playwright/test'

import { standardSetup } from './_helpers'

async function mockChatResumeRoutes(page: Parameters<typeof test>[0]['page']) {
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
}

async function installMockWebSocket(
  page: Parameters<typeof test>[0]['page'],
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
  test('shows delegating label and waiting indicator in chat', async ({ page }) => {
    await standardSetup(page)
    await mockChatResumeRoutes(page)
    await installMockWebSocket(page, 'waiting')

    await page.goto('/agents/agent-type-1/chat/session-1')
    await page.waitForLoadState('load')

    await expect(page.getByTestId('chat-status-indicator')).toBeVisible()
    await expect(page.getByText('Delegating to agent research-agent')).toBeVisible()
    await expect(page.getByText('Waiting for delegated response…')).toBeVisible()
  })

  test('shows timeout_or_failed terminal status in chat', async ({ page }) => {
    await standardSetup(page)
    await mockChatResumeRoutes(page)
    await installMockWebSocket(page, 'timeout_or_failed')

    await page.goto('/agents/agent-type-1/chat/session-1')
    await page.waitForLoadState('load')

    await expect(page.getByTestId('chat-status-terminal')).toBeVisible()
    await expect(
      page.getByText('Delegated step timed out or failed. Please try again.')
    ).toBeVisible()
  })
})
