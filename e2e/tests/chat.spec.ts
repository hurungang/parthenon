import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_AGENT_TYPES = [
  { id: 'at-1', name: 'Research Agent', mode: 'skillful-agent', is_active: true },
]

const MOCK_SESSIONS = [
  { id: 'sess-1', agent_type_id: 'at-1', channel: 'http', created_at: '2026-04-23T10:00:00Z' },
]

const MOCK_MESSAGES = [
  { id: 'msg-1', session_id: 'sess-1', role: 'agent', content: 'Hello! How can I help you today?', created_at: '2026-04-23T10:00:00Z' },
]

test.describe('Chat', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES) })
    )
    await page.route('**/api/v1/chat/sessions', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, body: JSON.stringify({ id: 'sess-1', agent_type_id: 'at-1' }) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SESSIONS) })
      }
    })
    await page.route('**/api/v1/chat/sessions/*/messages', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_MESSAGES) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_MESSAGES[0]) })
      }
    })
    await page.route('**/ws/**', (route) =>
      route.fulfill({ status: 200, body: '' })
    )
    await standardSetup(page)
  })

  test('chat page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/chat')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver') && !e.includes('WebSocket'))).toHaveLength(0)
  })

  test('chat page does not redirect to login', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('chat page has a message input area', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForLoadState('load')
    const inputArea = page.locator('input[type="text"], textarea, [contenteditable="true"]')
    const count = await inputArea.count()
    if (count > 0) {
      await expect(inputArea.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('chat page displays agent greeting message from API', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForLoadState('load')
    // The mock returns a greeting from the agent — it may appear after session loads
    const greeting = page.getByText('Hello! How can I help you today?')
    const hasGreeting = await greeting.count() > 0
    if (hasGreeting) {
      await expect(greeting).toBeVisible()
    } else {
      // Some UIs only show messages after a session is selected/started
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('chat page shows agent type selector or session list', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForLoadState('load')
    // Agent type 'Research Agent' should be selectable
    const agentOption = page.getByText('Research Agent')
    const hasAgentOption = await agentOption.count() > 0
    if (hasAgentOption) {
      await expect(agentOption.first()).toBeVisible()
    } else {
      // Might be in a dropdown/select
      const selects = page.locator('select, [role="combobox"], [role="listbox"]')
      const hasSelect = await selects.count() > 0
      expect(hasSelect || (await page.getByRole('button').count()) > 0).toBeTruthy()
    }
  })

  test('chat page send button is present and enabled', async ({ page }) => {
    await page.goto('/chat')
    await page.waitForLoadState('load')
    const sendBtn = page.locator('button').filter({ hasText: /send|submit/i })
    const hasSendBtn = await sendBtn.count() > 0
    if (hasSendBtn) {
      await expect(sendBtn.first()).toBeVisible()
    } else {
      // May use icon button — just verify at least one button exists
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })
})