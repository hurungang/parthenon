import { test, expect } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * E2E — resumable paused-turn recovery UI (resumable-agent-turn-persistence).
 *
 * Mocked variant. Drives the ConversationDialog rendered by
 * `/agents/:agentTypeId/chat/:sessionId` (testIdPrefix "chat") through a stubbed
 * WebSocket, emitting exactly the payloads Communication Hub sends for a
 * durable pause, a resume, and a terminal resolution. Asserts the operator-facing
 * contract from the PRD:
 *
 *  1. pending → approve → "Resumed · continuing" → resolved (input enabled);
 *  2. pending → deny → resumed → resolved;
 *  3. a no-longer-resumable turn renders the terminal card (expired body, next
 *     step, dismiss) instead of the legacy "timed out or failed" alert, and a
 *     stale/duplicate approval is never sent;
 *  4. reload hydration restores the same waiting/terminal state.
 */

const AGENT_TYPE_ID = 'resume-agent-type-1'
const SESSION_ID = 'resume-session-1'
const RESUME_ID = 'resume-1111'

const CONV_AGENT_TYPE = {
  id: AGENT_TYPE_ID,
  name: 'Resume Agent',
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

const SESSION_DETAIL = {
  id: SESSION_ID,
  agent_type_id: AGENT_TYPE_ID,
  triggered_by_user_id: 'user-1',
  agent_job_id: null,
  title: 'Resume session',
  channel: 'web',
  status: 'active',
  turn_count: 2,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  closed_at: null,
  turns: [
    {
      id: 'turn-u1',
      session_id: SESSION_ID,
      role: 'user',
      turn_type: 'message',
      content: 'Create the skill triage-inbox',
      intervene_request_id: null,
      token_count: null,
      created_at: new Date().toISOString(),
      tool_calls: [],
    },
  ],
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
    ;(window as unknown as { __sentFrames: () => string[] }).__sentFrames = () => {
      const w = window as unknown as { __sockets?: Array<{ sent: string[] }> }
      return w.__sockets?.flatMap((s) => s.sent) ?? []
    }
  })
}

async function emit(page: import('@playwright/test').Page, payload: unknown) {
  await page.waitForFunction(
    () => ((window as unknown as { __sockets?: unknown[] }).__sockets?.length ?? 0) > 0,
  )
  await page.evaluate((p) => {
    ;(window as unknown as { __emitActivity: (x: unknown) => void }).__emitActivity(p)
  }, payload)
}

async function sentFrames(page: import('@playwright/test').Page): Promise<any[]> {
  const raw = await page.evaluate(() =>
    ((window as unknown as { __sentFrames: () => string[] }).__sentFrames() ?? []).slice(),
  )
  return raw.map((frame) => JSON.parse(frame))
}

async function openChat(page: import('@playwright/test').Page) {
  await page.goto(`/agents/${AGENT_TYPE_ID}/chat/${SESSION_ID}`)
  await page.waitForLoadState('load')
  await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({
    timeout: 10000,
  })
}

async function mockBackend(page: import('@playwright/test').Page) {
  await mockApiCatchAllProxyAware(page)
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
      body: JSON.stringify(SESSION_DETAIL),
    }),
  )
  await page.route(`**/api/v1/conversations/${SESSION_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SESSION_DETAIL),
    }),
  )
  await page.route(
    `**/api/v1/conversations/${SESSION_ID}/interventions/pending`,
    (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
  await page.route('**/api/v1/agents/sessions**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
  )
}

const INTERVENE_REQUEST = {
  type: 'intervene_request',
  request_id: 'req-resume-1',
  intervention_type: 'approval',
  reason: '**Create Skill: triage-inbox** — confirm?',
  agent_type: 'assistant',
  delegation_depth: 0,
  conversation_session_id: SESSION_ID,
}

function pendingStatus(): Record<string, unknown> {
  return {
    type: 'chat_status',
    status: 'waiting_for_human',
    agent_type: 'assistant',
    pending_intervention: true,
    active_resume_id: RESUME_ID,
    resume_state: 'waiting_for_human',
  }
}

test.describe('Resumable Paused Turn Recovery (Mocked)', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await installFakeWebSocket(page)
    await mockBackend(page)
  })

  test('pending → approve → resumed and continuing → resolved (input re-enabled)', async ({
    page,
  }) => {
    await openChat(page)

    await emit(page, INTERVENE_REQUEST)
    await emit(page, pendingStatus())

    // "waiting for your input" — backed by the live resume id.
    await expect(page.getByTestId('chat-intervention-dialog')).toBeVisible()
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(
      /Waiting for your input/i,
    )
    await expect(page.getByText(/Thinking…/i)).toHaveCount(0)

    // The operator approves → the response is sent once over the socket.
    await page.getByRole('button', { name: /^approve$/i }).click()
    await expect
      .poll(async () => (await sentFrames(page)).some((f) => f.type === 'intervene_response'))
      .toBe(true)
    const approveFrame = (await sentFrames(page)).find(
      (f) => f.type === 'intervene_response',
    )
    expect(approveFrame.request_id).toBe('req-resume-1')
    expect(approveFrame.approval_value).toBe(true)

    // Server confirms the resume started: the turn reads "resumed · continuing".
    await emit(page, { type: 'intervene_status', request_id: 'req-resume-1', status: 'responded' })
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(
      /Resumed · continuing/i,
    )
    await expect(page.getByTestId('chat-intervention-pending-indicator')).toHaveCount(0)

    // The resumed turn keeps working (a tool call) and still reads as resumed.
    await emit(page, {
      type: 'chat_status',
      status: 'using_tool',
      tool_name: 'cc____create_skill',
      active_resume_id: RESUME_ID,
      resume_state: 'resuming',
    })
    await expect(page.getByText(/Using tool cc____create_skill/i)).toBeVisible()
    await expect(page.getByTestId('chat-resume-badge')).toBeVisible()

    // Resolved: no legacy timeout text, input is enabled again.
    await emit(page, {
      type: 'chat_status',
      status: 'finished',
      resume_state: 'resolved',
    })
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(/Resolved/i)
    await expect(page.getByText(/Resumed · continuing/i)).toHaveCount(0)
    await expect(
      page.getByPlaceholder(/Type a message/i).last(),
    ).toBeEnabled()
    await expect(page.getByText(/Delegated step timed out or failed/i)).toHaveCount(0)
  })

  test('pending → deny → resolved without a terminal card', async ({ page }) => {
    await openChat(page)

    await emit(page, INTERVENE_REQUEST)
    await emit(page, pendingStatus())
    await expect(page.getByTestId('chat-intervention-dialog')).toBeVisible()

    await page.getByRole('button', { name: /^deny$/i }).click()
    await expect
      .poll(async () => (await sentFrames(page)).some((f) => f.type === 'intervene_response'))
      .toBe(true)
    const denyFrame = (await sentFrames(page)).find(
      (f) => f.type === 'intervene_response',
    )
    expect(denyFrame.approval_value).toBe(false)

    await emit(page, { type: 'intervene_status', request_id: 'req-resume-1', status: 'responded' })
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(
      /Resumed · continuing/i,
    )

    await emit(page, {
      type: 'chat_status',
      status: 'finished',
      resume_state: 'resolved',
    })
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(/Resolved/i)
    // A clean denial is not an "unresumable" card.
    await expect(page.getByTestId('chat-terminal-card')).toHaveCount(0)
  })

  test('no-longer-resumable turn renders one reason-specific terminal card', async ({
    page,
  }) => {
    await openChat(page)

    await emit(page, {
      type: 'chat_status',
      status: 'timed_out',
      resume_state: 'unresumable',
      terminal_reason_code: 'expired',
      message: 'The confirmation expired. Ask again to generate a fresh preview.',
    })

    const card = page.getByTestId('chat-terminal-card')
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute('data-terminal-reason', 'expired')
    await expect(page.getByTestId('chat-terminal-card-body')).toContainText(
      /not answered within its validity window/i,
    )
    await expect(page.getByTestId('chat-terminal-card-body')).toContainText(
      /Nothing was written/i,
    )
    await expect(page.getByTestId('chat-terminal-card-next-step')).toBeVisible()
    await expect(page.getByTestId('chat-terminal-card-ask-again')).toBeVisible()
    await expect(page.getByTestId('chat-terminal-card-dismiss')).toBeVisible()
    // Exactly one card, and the legacy generic alert is replaced.
    await expect(page.getByTestId('chat-terminal-card')).toHaveCount(1)
    await expect(page.getByText(/Delegated step timed out or failed/i)).toHaveCount(0)
    // The turn is over: typing is possible again.
    await expect(page.getByPlaceholder(/Type a message/i).last()).toBeEnabled()

    // Dismissing retires the card and keeps the input enabled.
    await page.getByTestId('chat-terminal-card-dismiss').click()
    await expect(page.getByTestId('chat-terminal-card')).toHaveCount(0)
    await expect(page.getByPlaceholder(/Type a message/i).last()).toBeEnabled()
  })

  test('a stale approval on a terminal turn is never sent', async ({ page }) => {
    await openChat(page)

    // The confirmation is presented while the pause is still answerable…
    await emit(page, INTERVENE_REQUEST)
    await emit(page, pendingStatus())
    await expect(page.getByTestId('chat-intervention-dialog')).toBeVisible()

    // …then the turn expires while the dialog is open (reaper resolution).
    await emit(page, {
      type: 'chat_status',
      status: 'failed',
      resume_state: 'unresumable',
      terminal_reason_code: 'checkpoint_unavailable',
    })
    await expect(page.getByTestId('chat-terminal-card-body')).toContainText(
      /can no longer restore the pause point/i,
    )

    // A late click must not replay the confirmed action.
    await page.getByRole('button', { name: /^approve$/i }).click()

    await expect(page.getByTestId('chat-nothing-to-replay')).toBeVisible()
    const responses = (await sentFrames(page)).filter(
      (f) => f.type === 'intervene_response',
    )
    expect(responses).toHaveLength(0)
  })

  test('reload hydration restores the waiting state and the terminal message', async ({
    page,
  }) => {
    await openChat(page)
    await page.reload()
    await page.waitForLoadState('load')
    await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({
      timeout: 10000,
    })

    await emit(page, {
      type: 'activity_state',
      state: 'waiting_for_human',
      pending_intervention: true,
      is_terminal: false,
      active_resume_id: RESUME_ID,
      resume_state: 'waiting_for_human',
    })
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(
      /Waiting for your input/i,
    )

    // A terminal hydration preserves the reason (renders the same card).
    await emit(page, {
      type: 'activity_state',
      state: 'failed',
      pending_intervention: false,
      is_terminal: true,
      active_resume_id: null,
      resume_state: 'unresumable',
      terminal_reason_code: 'checkpoint_unavailable',
    })
    await expect(page.getByTestId('chat-terminal-card')).toBeVisible()
    await expect(page.getByTestId('chat-terminal-card-body')).toContainText(
      /can no longer restore the pause point/i,
    )
    await expect(page.getByTestId('chat-resume-state-chip')).toContainText(
      /No longer resumable/i,
    )
  })

  test('waiting activity without a live resume id is not presented as answerable', async ({
    page,
  }) => {
    await openChat(page)

    await emit(page, {
      type: 'activity_state',
      state: 'waiting_for_human',
      pending_intervention: false,
      is_terminal: false,
      active_resume_id: null,
      resume_state: null,
    })

    await expect(page.getByTestId('chat-resume-state-chip')).toHaveCount(0)
    await expect(page.getByTestId('chat-intervention-pending-indicator')).toHaveCount(0)
    await expect(page.getByText(/Waiting for your input/i)).toHaveCount(0)
  })
})
