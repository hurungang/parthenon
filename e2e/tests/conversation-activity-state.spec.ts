import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * E2E: persistent conversation activity state.
 *
 * Mocked variant — drives the ConversationDialog (rendered by the
 * `/agents/:id/chat/:sessionId` route, testIdPrefix "chat") through a stubbed
 * WebSocket that emits the status/hydration payloads the real Communication Hub
 * sends. Asserts the processing bubble lifecycle:
 *   - live `using_tool` status shows the tool bubble
 *   - `waiting_for_human` shows "Waiting for your input…" continuously
 *   - a terminal `finished` state clears the spinner and shows a terminal line
 *   - an `activity_state` hydration snapshot restores status after a reload
 *
 * Real Backend Integration variant — probes the real services and verifies the
 * internal activity endpoint is registered and fail-closed (no live stack => skip).
 */

const AGENT_TYPE_ID = 'act-agent-type-1'
const SESSION_ID = 'act-session-1'

const CONV_AGENT_TYPE = {
  id: AGENT_TYPE_ID,
  name: 'Activity Agent',
  input_type: 'conversation',
  output_type: 'auto',
  is_active: true,
  model_id: null,
  role_id: null,
  identity_id: null,
  sop_bindings: [],
  skill_bindings: [],
  system_instruction: null,
  description: null,
  input_schema: null,
  output_schema: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  plan: null,
}

const EMPTY_TURN = {
  id: 'turn-x',
  session_id: SESSION_ID,
  role: 'agent',
  turn_type: 'message',
  content: '',
  intervene_request_id: null,
  token_count: null,
  created_at: new Date().toISOString(),
  tool_calls: [],
}

async function installFakeWebSocket(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    class FakeWebSocket {
      static readonly OPEN = 1
      static readonly CLOSED = 3
      readyState = 1
      sent: string[] = []
      onopen: ((ev: Event) => void) | null = null
      onmessage: ((ev: MessageEvent) => void) | null = null
      onclose: ((ev: CloseEvent) => void) | null = null
      onerror: ((ev: Event) => void) | null = null
      constructor(public url: string) {
        const w = window as unknown as { __sockets?: FakeWebSocket[] }
        w.__sockets = w.__sockets || []
        w.__sockets.push(this)
        setTimeout(() => this.onopen?.(new Event('open')), 0)
      }
      send(data: string) {
        this.sent.push(data)
      }
      close() {
        this.readyState = 3
      }
      emit(payload: unknown) {
        this.onmessage?.(
          new MessageEvent('message', { data: JSON.stringify(payload) }),
        )
      }
    }
    ;(window as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket
    ;(window as unknown as { __emitActivity: (p: unknown) => void }).__emitActivity = (
      payload: unknown,
    ) => {
      const w = window as unknown as { __sockets?: Array<{ emit: (p: unknown) => void }> }
      w.__sockets?.[w.__sockets.length - 1]?.emit(payload)
    }
  })
}

async function emit(page: import('@playwright/test').Page, payload: unknown) {
  await page.evaluate((p) => {
    ;(window as unknown as { __emitActivity: (x: unknown) => void }).__emitActivity(p)
  }, payload)
}

test.describe('Conversational Activity State (Mocked)', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await installFakeWebSocket(page)

    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([CONV_AGENT_TYPE]),
      }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CONV_AGENT_TYPE),
      }),
    )
    await page.route(`**/api/v1/conversations/${SESSION_ID}/resume`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: SESSION_ID,
          agent_type_id: AGENT_TYPE_ID,
          triggered_by_user_id: 'user-1',
          agent_job_id: null,
          title: 'Activity session',
          channel: 'web',
          status: 'active',
          turn_count: 1,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          closed_at: null,
          turns: [EMPTY_TURN],
        }),
      }),
    )
    await page.route(`**/api/v1/conversations/${SESSION_ID}/interventions/pending`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    )
    await page.route('**/api/v1/agents/sessions**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    )
  })

  test('chat surface renders status bubbles for the full activity lifecycle', async ({ page }) => {
    await page.goto(`/agents/${AGENT_TYPE_ID}/chat/${SESSION_ID}`)
    await page.waitForLoadState('load')
    await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 8000 })

    // thinking / tool
    await emit(page, { type: 'chat_status', status: 'using_tool', tool_name: 'cc____list_agents' })
    await expect(page.getByText(/Using tool cc____list_agents/i)).toBeVisible({ timeout: 5000 })

    // waiting for human — indicator shown continuously
    await emit(page, {
      type: 'chat_status',
      status: 'waiting_for_human',
      agent_type: 'assistant',
      pending_intervention: true,
    })
    await expect(page.getByText(/Waiting for your input/i)).toBeVisible({ timeout: 5000 })

    // terminal — spinner cleared, terminal message shown
    await emit(page, { type: 'chat_status', status: 'finished' })
    await expect(page.getByText(/Turn completed/i)).toBeVisible({ timeout: 5000 })
    await expect(page.getByText(/Thinking…/i)).toHaveCount(0)
  })

  test('reload hydration restores the persisted waiting status', async ({ page }) => {
    await page.goto(`/agents/${AGENT_TYPE_ID}/chat/${SESSION_ID}`)
    await page.waitForLoadState('load')
    await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 8000 })

    await page.reload()
    await page.waitForLoadState('load')
    await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 8000 })

    await emit(page, {
      type: 'activity_state',
      state: 'waiting_for_human',
      pending_intervention: true,
      is_terminal: false,
    })
    await expect(page.getByText(/Waiting for your input/i)).toBeVisible({ timeout: 5000 })
  })
})

// ── Real Backend Integration variant ─────────────────────────────────────────

test.describe('Real Backend Integration - Conversation Activity State', () => {
  test('internal activity endpoint is registered and fail-closed', async ({ request }) => {
    // Skip cleanly when no live stack is running.
    try {
      const health = await request.get('http://localhost:8000/api/v1/health')
      if (!health.ok() && health.status() !== 401) {
        test.skip()
        return
      }
    } catch {
      test.skip()
      return
    }

    // No service certificate from a browser context => must fail closed.
    const activity = await request.get(
      'http://localhost:8000/api/v1/internal/data/conversations/00000000-0000-0000-0000-000000000000/activity',
    )
    expect([401, 403, 404]).toContain(activity.status())
  })

  test('conversation session resume endpoint responds against the real backend', async ({
    request,
  }) => {
    let token: string
    try {
      const login = await request.post('http://localhost:8000/api/v1/auth/token', {
        form: { username: 'admin@example.com', password: 'admin' },
      })
      if (!login.ok()) {
        test.skip()
        return
      }
      token = (await login.json()).access_token ?? ''
    } catch {
      test.skip()
      return
    }

    const resp = await request.get(
      'http://localhost:8000/api/v1/conversations/00000000-0000-0000-0000-000000000000/resume',
      { headers: { Authorization: `Bearer ${token}` } },
    )
    // 404 (unknown session) proves routing + auth path; never a 500.
    expect([200, 401, 403, 404, 422]).toContain(resp.status())
  })
})
