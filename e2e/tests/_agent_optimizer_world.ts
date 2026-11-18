import { expect, test, type Locator, type Page, type Route } from '@playwright/test'

/**
 * Shared mocked world for the conversational-optimizer E2E specs
 * (`agent-optimizer-conversation`, `agent-optimizer-live-test-approval`,
 * `agent-optimizer-model-config`).
 *
 * Conventions (mirrors `_agent_panel_world.ts`):
 *  - `mockApiCatchAllProxyAware` + `standardSetup` + `mockPanelWorld` are
 *    registered by the spec BEFORE this world, so this file's routes win
 *    (Playwright resolves route handlers last-registered-first).
 *  - Every route regex matches BOTH the absolute `http://localhost:8000/api/v1`
 *    base the E2E build uses and the same-origin proxy form.
 *  - A highest-priority request observer (registered LAST, `route.fallback()`)
 *    records every API call into `state.requests`, so specs can assert that a
 *    declined / informational path wrote nothing.
 *  - `installFakeChatSocket` replaces `window.WebSocket` with a stub the spec
 *    drives (`emitChat`) and inspects (`readChatFrames`) — the optimization
 *    conversation reuses the ordinary chat transport, so the frame log is the
 *    proof of what the UI actually sent (messages, approve/deny decisions).
 *
 * No live backend is contacted by the mocked specs.
 */

const T = '2026-06-01T00:00:00Z'

export const TYPED_AGENT_ID = 'at-a'
export const TYPED_AGENT_NAME = 'panel-e2e-alpha'
export const CONV_AGENT_ID = 'at-c'
export const CONV_AGENT_NAME = 'panel-e2e-conv'

/** Session id of the mocked optimization conversation created on first send. */
export const OPTIMIZATION_CONVERSATION_ID = 'conv-opt-1'
/** Session id of the mocked BUSINESS conversation (channel isolation checks). */
export const BUSINESS_CONVERSATION_ID = 'conv-biz-1'

// Copy resolved from `frontend/src/i18n/locales/en.json` (the only locale).
export const COPY = {
  talkToOptimizer: 'Talk to optimizer',
  scopedTo: (name: string) => `Scoped to ${name} only`,
  identityParity: 'Runs as this agent — same identity and permissions',
  modeOnAgent: (name: string) => `Optimization mode on ${name}`,
  scopePlan: (name: string) =>
    `Scope: ${name}'s optimized plan · its generated scripts · its execution history · its base plan`,
  scopeConversational: (name: string) =>
    `Scope: ${name} — no optimized plan yet · its own instructions · its execution history`,
  replayOnly: 'Replay-only',
  modelInherited: 'inherited from the plan authoring model',
  emptyTitle: 'Nothing to optimize yet — the conversation starts from your description.',
  noExecution:
    'Optimization needs at least one successful run of this agent so the optimizer has a real reference execution to replay against.',
  inputPlaceholder: 'Message the optimizer… (Enter to send)',
  inputBlockedBusy: 'The optimizer is working…',
  inputBlockedDecision: 'Waiting for your decision above…',
  inputBlockedModel: 'Configure an optimizer model to start',
  blockedDecision:
    'An answer is pending above. Respond to it before sending another message — nothing runs until you decide.',
  askTitle: 'The optimizer needs your decision',
  askChip: 'Needs your answer',
  // ── Single processing indicator (the only in-flight UI) ────────────────────
  statusThinking: 'Thinking…',
  statusUsingTool: (toolName: string) => `Using tool ${toolName}…`,
  // ── Compact "What ran in this session" bar (the only chat chrome) ──────────
  sessionBarTitle: 'What ran in this session',
  sessionBarExpand: 'Details',
  sessionBarCollapse: 'Hide details',
  auditReplay: (count: number) =>
    `${count} replay verification${count === 1 ? '' : 's'}`,
  auditLiveUsed: (count: number) =>
    `${count} approved live operation${count === 1 ? '' : 's'} · single use`,
  auditNoLive: '0 live operations',
  auditNoteReplayOnly:
    'Replay is the default. Anything live appears here only after you approved one specific test — nothing is running in the background.',
  liveRunning: 'Live test running…',
  liveUsedTitle: 'Single use — the approval is already spent',
  // ── Script-based live-test approval card ──────────────────────────────────
  approvalRunScriptTitle: 'Run this script live',
  approvalScriptVersion: (name: string, version: string) => `${name} (${version})`,
  approvalSubtitle: (name: string) =>
    `Verifies ${name}'s script end-to-end — MCP tools are assumed to work.`,
  approvalItWillCall: (tools: string) => `It will call: ${tools}`,
  approvalPreviewNote:
    'Informational only — approving runs the whole script once, not these calls individually.',
  approvalRunsOnceNote: (name: string) =>
    `Runs once as ${name}; not remembered. Replay stays the default until you approve.`,
  approvalApprove: 'Approve & run once',
  approvalDeny: 'Deny',
  approvalExpiryPrefix: 'Answer window: about',
  approvalPendingChip: 'needs your approval',
  approvalRunningChip: 'running once',
  approvalExecutedChip: 'ran once',
  approvalFailedChip: 'failed',
  approvalDeniedChip: 'denied',
  approvalExpiredChip: 'expired — closed',
  approvalCancelledChip: 'closed',
  approvalSummaryRunning: (name: string) => `Running once as ${name}…`,
  approvalSummaryExecuted: 'Ran once',
  approvalSummaryFailed: 'Run failed',
  approvalSummaryDenied: 'Denied — nothing ran live',
  approvalSummaryExpired: 'Expired unanswered — nothing ran',
  approvalUsedOncePrefix:
    'Approval used. It cannot be replayed and it is not remembered',
  approvalDeniedNotePrefix: 'Denied — nothing ran live.',
  approvalNoteExpiredPrefix: 'The tool-call preview is kept for audit.',
  approvalFailedReplayOnlyPrefix: 'The script run failed. Replay-only is in force again',
  approvalScriptOutput: 'Script output',
  approvalToolCallsTitle: 'Tool calls (telemetry)',
  approvalToolCalls: (count: number) =>
    `${count} tool call${count === 1 ? '' : 's'}`,
  outOfScope:
    'That request is outside this optimization conversation. Nothing was changed — this conversation can only work on its own agent type.',
  modelReasonsNotConfigured:
    'No usable optimizer model is configured for this workspace. Select one in System Config → Optimizer Model, or set the plan authoring model it inherits from.',
  modelAlertTitle: 'No usable optimizer model in this workspace',
  modelAlertBodyNotConfigured:
    'Optimization cannot start with an unapproved model. An administrator can choose one under System Config → Optimizer Model, or select the plan authoring model it inherits.',
  modelAlertBodyNotEnabledPrefix: 'The chosen optimizer model “retired-model” is no longer available',
  openSystemConfig: 'Open System Config',
  systemConfigSection: 'Optimizer Model',
  systemConfigScope: 'Applies to this workspace only',
  systemConfigReminderUnset:
    'No usable optimizer model is configured for this workspace. Optimization conversations cannot start until you select one — or set the plan authoring model they inherit from.',
  systemConfigInheritOption: 'Inherit the plan authoring model',
  systemConfigStateInherited: (modelId: string) =>
    `Inheriting “${modelId}” from the plan authoring model.`,
  systemConfigStateSelected: (modelId: string) => `Optimization runs on “${modelId}”.`,
  systemConfigNoSubstitutionPrefix: 'No substitution:',
  saveSuccess: 'Settings saved successfully',
} as const

/** Optimizer-model catalogue used by the System Config + gate mocks. */
export const OPTIMIZER_MODEL_OPTIONS = [
  {
    model_id: 'gpt-4o',
    config_id: 'cfg-1',
    config_display_name: 'Panel E2E GPT',
    provider_type: 'openai',
  },
  {
    model_id: 'claude-sonnet',
    config_id: 'cfg-2',
    config_display_name: 'Anthropic',
    provider_type: 'anthropic',
  },
]

export interface OptimizationAuditPayload {
  replay_verifications: number
  live_operations: number
  last_live_at: string | null
  replay_only: boolean
}

export interface OptimizerWorldState {
  agentId: string
  agentName: string
  isConversational: boolean
  /** The mocked `OptimizationGateRead` payload the tab + chat read. */
  gate: Record<string, unknown>
  /** Computed availability projection returned by create + read. */
  availability: Record<string, unknown>
  audit: OptimizationAuditPayload
  /** Current optimized plan (null ⇒ 404, no plan yet). */
  plan: Record<string, unknown> | null
  planReads: number
  /** Bodies of POST /conversations/optimization (subject-only contract). */
  createRequests: Record<string, unknown>[]
  /** Bodies of POST /conversations (business create — must never be used). */
  businessCreateRequests: Record<string, unknown>[]
  /** The session's live-test ledger rows (GET …/live-test-requests). */
  liveTestRequests: Record<string, unknown>[]
  /** Pending interventions returned by the REST reconnect read. */
  pendingInterventions: Record<string, unknown>[]
  /** Bodies of POST …/interventions/{id}/respond (REST fallback path). */
  respondRequests: Record<string, unknown>[]
  /** Every /api/v1 request seen: "METHOD /pathname". */
  requests: string[]
  /** Wake-up tools the optimizer turn looked at (activity timeline). */
  liveSessionCreatedFor: string | null
}

export function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/** Default gate for a fully usable typed subject. */
export function typedGate(overrides: Record<string, unknown> = {}) {
  return {
    can_optimize: true,
    can_generate_plan: true,
    successful_executions: 2,
    workflow_model_configured: true,
    workflow_model_id: 'gpt-4o',
    is_conversational: false,
    reason_code: null,
    reason: null,
    optimization_conversation_available: true,
    optimization_conversation_reason_code: null,
    optimizer_model_configured: true,
    optimizer_model_id: 'gpt-4o',
    optimizer_model_source: 'optimizer',
    optimizer_model_reason_code: null,
    ...overrides,
  }
}

/** Availability projection for a subject that can start optimization work. */
export function availableNow(overrides: Record<string, unknown> = {}) {
  return {
    available: true,
    reason_code: null,
    reason: null,
    can_start_work: true,
    plan_present: true,
    optimized_plan_status: 'ready',
    successful_executions: 2,
    optimizer_model: {
      model_id: null,
      effective_model_id: 'gpt-4o',
      source: 'authoring',
      configured: true,
      enabled: true,
      reason_code: null,
    },
    ...overrides,
  }
}

/** A `ready` optimized plan as the Optimized Plan tab renders it. */
export function readyPlan(agentTypeId: string, overrides: Record<string, unknown> = {}) {
  return {
    id: 'oplan-e2e-1',
    agent_type_id: agentTypeId,
    agent_plan_id: `plan-${agentTypeId}`,
    status: 'ready',
    fully_scripted: false,
    error: null,
    steps: [
      {
        order: 1,
        type: 'tool_call',
        name: 'Query refunds (conversational)',
        description: 'Authored in the optimization conversation',
        python_source: null,
        scriptable: true,
      },
    ],
    steps_count: 1,
    scripts_authored: 1,
    feedback_comments: [],
    generated_at: T,
    ...overrides,
  }
}

function conversationFixture(id: string, agentTypeId: string, channel: string) {
  return {
    id,
    agent_type_id: agentTypeId,
    triggered_by_user_id: 'e2e-admin',
    agent_job_id: null,
    title: null,
    channel,
    status: 'active',
    turn_count: 0,
    created_at: T,
    updated_at: T,
    closed_at: null,
  }
}

/**
 * Registers the whole optimizer API surface for one subject agent type.
 * MUST be called AFTER `mockPanelWorld` (routes resolve last-registered-first).
 */
export async function mockOptimizerApi(
  page: Page,
  state: OptimizerWorldState,
): Promise<OptimizerWorldState> {
  const conversationId = OPTIMIZATION_CONVERSATION_ID

  // ── Composed plan/optimize gate (drives the tab entry + chat model state) ──
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimization-gate$/, (route) =>
    json(route, 200, state.gate),
  )

  // ── Optimized plan (current server-side state) ────────────────────────────
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimized-plan(\?.*)?$/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    state.planReads += 1
    if (!state.plan) {
      return json(route, 404, { detail: 'No optimized plan for this agent type' })
    }
    return json(route, 200, state.plan)
  })
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimized-plan\/retire$/, (route) => {
    if (state.plan) state.plan = { ...state.plan, status: 'retired' }
    return json(route, 200, state.plan ?? {})
  })
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimize-plan\/feedback$/, (route) =>
    json(route, 200, {}),
  )
  // The one-shot Optimize path is NOT part of the conversational journey — the
  // route exists only so a regression that triggers it is observable.
  await page.route(/\/api\/v1\/agents\/sessions\/optimize$/, (route) =>
    json(route, 202, {
      id: 'sess-opt-regression',
      agent_type_id: state.agentId,
      status: 'queued',
      created_at: T,
    }),
  )
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/regenerate-plan$/, (route) =>
    json(route, 412, { detail: { error: 'plan_generation_unavailable' } }),
  )

  // ── Optimization conversation create (subject only, starts no work) ───────
  await page.route(/\/api\/v1\/conversations\/optimization$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    state.createRequests.push(route.request().postDataJSON())
    state.liveSessionCreatedFor = conversationId
    return json(route, 201, {
      conversation: conversationFixture(conversationId, state.agentId, 'optimization'),
      subject: {
        agent_type_id: state.agentId,
        name: state.agentName,
        input_type: state.isConversational ? 'conversation' : 'none',
        is_conversational: state.isConversational,
      },
      availability: state.availability,
    })
  })

  // ── Business conversation create (must never be used in optimization mode) ─
  await page.route(/\/api\/v1\/conversations(\?.*)?$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    state.businessCreateRequests.push(route.request().postDataJSON())
    return json(route, 201, {
      ...conversationFixture(BUSINESS_CONVERSATION_ID, state.agentId, 'web'),
    })
  })

  // ── Conversation read: subject + availability + replay/live audit ─────────
  await page.route(/\/api\/v1\/conversations\/[^/]+\/optimization$/, (route) =>
    json(route, 200, {
      conversation: conversationFixture(conversationId, state.agentId, 'optimization'),
      subject: {
        agent_type_id: state.agentId,
        name: state.agentName,
        input_type: state.isConversational ? 'conversation' : 'none',
        is_conversational: state.isConversational,
      },
      availability: state.availability,
      audit: state.audit,
    }),
  )

  // ── Live-test ledger ──────────────────────────────────────────────────────
  await page.route(/\/api\/v1\/conversations\/[^/]+\/live-test-requests$/, (route) =>
    json(route, 200, state.liveTestRequests),
  )

  // ── Pending interventions (reconnect re-surface read) ─────────────────────
  await page.route(/\/api\/v1\/conversations\/[^/]+\/interventions\/pending$/, (route) =>
    json(route, 200, state.pendingInterventions),
  )

  // ── Intervention respond (REST fallback when the socket is unavailable) ────
  await page.route(/\/api\/v1\/conversations\/[^/]+\/interventions\/[^/]+\/respond$/, (route) => {
    const body = route.request().postDataJSON()
    state.respondRequests.push(body)
    return json(route, 200, {
      id: 'resp-e2e-1',
      request_id: body?.request_id ?? 'req-e2e',
      operator_user_id: 'e2e-admin',
      approval_value: body?.approval_value ?? null,
      responded_at: T,
    })
  })
  await page.route(/\/api\/v1\/intervene\/requests\/[^/]+\/cancel$/, (route) =>
    json(route, 200, { id: 'req-e2e', status: 'cancelled' }),
  )

  // ── Session lifecycle (resume / end / archive) ────────────────────────────
  await page.route(/\/api\/v1\/conversations\/[^/]+\/resume$/, (route) =>
    json(route, 200, { id: conversationId, turns: [], guardrail_usage: null }),
  )
  await page.route(/\/api\/v1\/conversations\/[^/]+\/end$/, (route) =>
    json(route, 200, conversationFixture(conversationId, state.agentId, 'optimization')),
  )
  await page.route(/\/api\/v1\/conversations\/[^/]+\/archive$/, (route) =>
    json(route, 200, conversationFixture(conversationId, state.agentId, 'optimization')),
  )

  // ── Request observer (highest priority — registered LAST) ─────────────────
  await page.route(/\/api\/v1\//, (route) => {
    const req = route.request()
    let pathname = req.url()
    try {
      pathname = new URL(req.url()).pathname
    } catch {
      // keep the raw url
    }
    state.requests.push(`${req.method()} ${pathname}`)
    return route.fallback()
  })

  return state
}

/** Fresh mutable state for a typed subject. */
export function typedWorldState(overrides: Partial<OptimizerWorldState> = {}): OptimizerWorldState {
  return {
    agentId: TYPED_AGENT_ID,
    agentName: TYPED_AGENT_NAME,
    isConversational: false,
    gate: typedGate(),
    availability: availableNow(),
    audit: {
      replay_verifications: 0,
      live_operations: 0,
      last_live_at: null,
      replay_only: true,
    },
    plan: null,
    planReads: 0,
    createRequests: [],
    businessCreateRequests: [],
    liveTestRequests: [],
    pendingInterventions: [],
    respondRequests: [],
    requests: [],
    liveSessionCreatedFor: null,
    ...overrides,
  }
}

/** Fresh mutable state for a conversational subject with no plan. */
export function conversationalWorldState(
  overrides: Partial<OptimizerWorldState> = {},
): OptimizerWorldState {
  return typedWorldState({
    agentId: CONV_AGENT_ID,
    agentName: CONV_AGENT_NAME,
    isConversational: true,
    gate: typedGate({
      can_optimize: false,
      can_generate_plan: false,
      successful_executions: 0,
      reason_code: 'conversational_agent',
      is_conversational: true,
      optimizer_model_id: 'gpt-4o',
      optimizer_model_source: 'authoring',
    }),
    availability: availableNow({
      available: false,
      reason_code: 'no_successful_execution',
      reason: COPY.noExecution,
      can_start_work: false,
      plan_present: false,
      optimized_plan_status: null,
      successful_executions: 0,
      optimizer_model: {
        model_id: null,
        effective_model_id: 'gpt-4o',
        source: 'authoring',
        configured: true,
        enabled: true,
        reason_code: null,
      },
    }),
    plan: null,
    ...overrides,
  })
}

// ── Fake chat WebSocket ────────────────────────────────────────────────────────

/** Installs a drivable fake `WebSocket` before any page script runs. */
export async function installFakeChatSocket(page: Page) {
  await page.addInitScript(() => {
    class FakeWebSocket {
      static readonly CONNECTING = 0
      static readonly OPEN = 1
      static readonly CLOSING = 2
      static readonly CLOSED = 3
      readyState = 1
      sent: string[] = []
      onopen: ((ev: Event) => void) | null = null
      onmessage: ((ev: MessageEvent) => void) | null = null
      onclose: ((ev: CloseEvent) => void) | null = null
      onerror: ((ev: Event) => void) | null = null
      constructor(public url: string) {
        const w = window as unknown as { __chatSockets?: FakeWebSocket[] }
        w.__chatSockets = w.__chatSockets || []
        w.__chatSockets.push(this)
        setTimeout(() => this.onopen?.(new Event('open')), 0)
      }
      send(data: string) {
        this.sent.push(data)
      }
      close() {
        this.readyState = 3
      }
      emit(payload: unknown) {
        this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
      }
    }

    const w = window as unknown as {
      WebSocket: unknown
      __chatSockets?: FakeWebSocket[]
      __emitChat?: (payload: unknown) => void
      __chatFrames?: () => unknown[]
      __chatSocketCount?: () => number
    }
    w.WebSocket = FakeWebSocket
    w.__emitChat = (payload: unknown) => {
      const sockets = w.__chatSockets ?? []
      sockets[sockets.length - 1]?.emit(payload)
    }
    w.__chatFrames = () => {
      const sockets = w.__chatSockets ?? []
      const last = sockets[sockets.length - 1]
      return (last?.sent ?? []).map((frame) => {
        try {
          return JSON.parse(frame)
        } catch {
          return frame
        }
      })
    }
    w.__chatSocketCount = () => (w.__chatSockets ?? []).length
  })
}

/** Pushes one server event onto the newest chat socket. */
export async function emitChat(page: Page, payload: unknown) {
  await page.evaluate((p) => {
    ;(window as unknown as { __emitChat: (x: unknown) => void }).__emitChat(p)
  }, payload)
}

/** Every frame the UI sent on the newest chat socket (parsed). */
export async function readChatFrames(page: Page): Promise<Record<string, unknown>[]> {
  return page.evaluate(() => {
    const read = (window as unknown as { __chatFrames?: () => unknown[] }).__chatFrames
    return (read?.() ?? []) as Record<string, unknown>[]
  })
}

/** Waits for the chat socket to exist and to have sent at least one frame. */
export async function waitForChatSocket(page: Page) {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const count = (window as unknown as { __chatSocketCount?: () => number })
            .__chatSocketCount
          return count?.() ?? 0
        }),
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0)
}

/** Non-GET requests observed — the "zero writes" assertion surface. */
export function mutationRequests(state: OptimizerWorldState): string[] {
  return state.requests.filter((entry) => !entry.startsWith('GET '))
}

// ── Navigation / interaction helpers ─────────────────────────────────────────

/** Navigates to the agent list and skips cleanly if auth diverted the page. */
export async function gotoAgentsList(page: Page, agentName: string): Promise<boolean> {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  await expect(page.getByText(agentName, { exact: true }).first()).toBeVisible()
  return true
}

/** Opens the agent-type detail dialog (a UI click, no navigation). */
export async function openAgentDialog(page: Page, agentName: string) {
  await page.getByText(agentName, { exact: true }).first().click()
  const dialog = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('tab', { name: 'Optimized Plan' }) })
  await expect(dialog.getByRole('tab', { name: 'Optimized Plan' })).toBeVisible()
  return dialog
}

/** Opens the "Optimized Plan" tab of the details dialog. */
export async function openOptimizedPlanTab(dialog: Locator) {
  await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
}

/** The optimization-mode conversation dialog (pinned by its mode chip). */
export function optimizerChatDialog(page: Page): Locator {
  return page
    .getByRole('dialog')
    .filter({ has: page.getByTestId('optimization-conversation-dialog-optimization-mode-chip') })
}

/** Opens the optimizer chat from the tab entry and returns its dialog. */
export async function openOptimizerChat(page: Page, dialog: Locator): Promise<Locator> {
  await dialog.getByTestId('talk-to-optimizer').click()
  const chat = optimizerChatDialog(page)
  await expect(chat).toBeVisible()
  // The only chrome above the transcript is the compact "What ran in this
  // session" bar, and it starts collapsed.
  const bar = chat.getByTestId('optimization-conversation-dialog-optimization-session-bar')
  await expect(bar).toBeVisible()
  await expect(bar).toHaveAttribute('data-expanded', 'false')
  return chat
}

/** Expands the collapsed "What ran in this session" bar (audit + scope detail). */
export async function expandSessionBar(chat: Locator): Promise<Locator> {
  const bar = chat.getByTestId('optimization-conversation-dialog-optimization-session-bar')
  if ((await bar.getAttribute('data-expanded')) !== 'true') {
    await bar.getByTestId('optimization-conversation-dialog-optimization-session-bar-toggle').click()
  }
  await expect(bar).toHaveAttribute('data-expanded', 'true')
  return bar
}

/** Expands a decided live-test card (pending is already expanded). */
export async function expandLiveTestCard(card: Locator) {
  if ((await card.getAttribute('data-expanded')) !== 'true') {
    await card.getByTestId(`${await card.getAttribute('data-testid')}-toggle`).click()
  }
  await expect(card).toHaveAttribute('data-expanded', 'true')
}

/** Collapses a decided live-test card back to its one-line history summary. */
export async function collapseLiveTestCard(card: Locator) {
  if ((await card.getAttribute('data-expanded')) === 'true') {
    await card.getByTestId(`${await card.getAttribute('data-testid')}-toggle`).click()
  }
  await expect(card).toHaveAttribute('data-expanded', 'false')
}

/** Types and sends one message in the (optimization) chat composer. */
export async function sendChatMessage(page: Page, chat: Locator, text: string) {
  const composer = chat.getByPlaceholder(COPY.inputPlaceholder)
  await composer.fill(text)
  await chat.getByRole('button', { name: 'Send', exact: true }).click()
  await waitForChatSocket(page)
}

/** Waits until the UI sent a frame matching `predicate`. */
export async function waitForFrame(
  page: Page,
  predicate: (frame: Record<string, unknown>) => boolean,
) {
  await expect
    .poll(
      async () => (await readChatFrames(page)).some((frame) => predicate(frame)),
      { timeout: 15_000 },
    )
    .toBe(true)
}

/** Closes the chat dialog through its Exit action (never a page reload). */
export async function closeChatDialog(chat: Locator) {
  await chat.getByRole('button', { name: 'Exit', exact: true }).click()
  await expect(chat).toBeHidden()
}

export async function markNoReload(page: Page) {
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).__e2e_no_reload = true
  })
}

export async function assertNoReload(page: Page) {
  const marker = await page.evaluate(
    () => (window as unknown as Record<string, unknown>).__e2e_no_reload,
  )
  expect(marker).toBe(true)
}

/** The saved script version the mocked approval names (the unit of approval). */
export const LIVE_TEST_SCRIPT = {
  script_version_id: 'sv-e2e-1',
  script_name: 'refund-verification',
  script_version_label: 'v3',
} as const

/** The server-derived tool-call preview (evidence, never the unit of run). */
export const SCRIPT_PREVIEW = [
  { tool_name: 'crm____lookup_contact', arguments: {}, purpose: 'called by the script' },
  { tool_name: 'crm____list_deals', arguments: {}, purpose: 'called by the script' },
]

/** One `{kind: "script_run", …}` record — what the approved script did. */
export function scriptRunRecord(overrides: Record<string, unknown> = {}) {
  return {
    kind: 'script_run',
    script_version_id: LIVE_TEST_SCRIPT.script_version_id,
    script_name: LIVE_TEST_SCRIPT.script_name,
    script_version_label: LIVE_TEST_SCRIPT.script_version_label,
    status: 'success',
    result_summary: '{"refunded": true, "deals": 2}',
    error: null,
    duration_ms: 4200,
    tool_calls: [
      {
        tool_name: 'crm____lookup_contact',
        status: 'success',
        duration_ms: 120,
        result_summary: 'contact found',
        error: null,
      },
      {
        tool_name: 'crm____list_deals',
        status: 'success',
        duration_ms: 240,
        result_summary: '2 open deals',
        error: null,
      },
    ],
    telemetry: { tool_call_count: 2, duration_ms: 4200 },
    ...overrides,
  }
}

/** A live-test approval proposal attached to an `intervene_request` event. */
export function liveTestProposal(overrides: Record<string, unknown> = {}) {
  return {
    live_test_request_id: 'ltr-e2e-1',
    status: 'pending',
    expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    ...LIVE_TEST_SCRIPT,
    // Tool-call PREVIEW only — approving runs the whole script once.
    operations: SCRIPT_PREVIEW,
    executed_operations: null,
    target_agent_type_id: TYPED_AGENT_ID,
    ...overrides,
  }
}

/** A ledger row as `GET /conversations/{id}/live-test-requests` returns it. */
export function ledgerRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ltr-e2e-1',
    status: 'pending',
    target_agent_type_id: TYPED_AGENT_ID,
    ...LIVE_TEST_SCRIPT,
    requested_operations: SCRIPT_PREVIEW,
    executed_operations: null,
    expires_at: new Date(Date.now() + 10 * 60_000).toISOString(),
    execution_started_at: null,
    execution_finished_at: null,
    decision: null,
    created_at: T,
    ...overrides,
  }
}
