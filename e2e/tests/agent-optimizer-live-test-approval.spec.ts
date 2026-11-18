import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'
import {
  COPY,
  LIVE_TEST_SCRIPT,
  SCRIPT_PREVIEW,
  TYPED_AGENT_ID,
  TYPED_AGENT_NAME,
  closeChatDialog,
  emitChat,
  collapseLiveTestCard,
  expandLiveTestCard,
  expandSessionBar,
  gotoAgentsList,
  installFakeChatSocket,
  ledgerRow,
  liveTestProposal,
  mockOptimizerApi,
  mutationRequests,
  openAgentDialog,
  openOptimizedPlanTab,
  openOptimizerChat,
  readChatFrames,
  readyPlan,
  scriptRunRecord,
  sendChatMessage,
  typedWorldState,
  waitForFrame,
  type OptimizerWorldState,
} from './_agent_optimizer_world'

/**
 * E2E: the single-use live-test approval of the conversational optimizer
 * (`docs/changes/optimizer-conversational-agent/test-plan.md` → Live-test
 * approval: approve / deny / expiry).
 *
 * A live test runs the **SAVED SCRIPT** end-to-end — never an individual MCP
 * tool call; MCP tools are assumed to work. The card is therefore script-based:
 * it names the script + version, shows the server-derived tool-call preview as
 * INFORMATION, and says the run is one end-to-end execution as this agent.
 *
 * Guarantees under test (UI contract):
 *   - pending is the only expanded card state; it names exactly the script that
 *     would run and its informational preview, and says once / not remembered;
 *   - approve is submitted once, the card moves pending → running → executed and
 *     then COLLAPSES into a one-line history summary that expands to the script
 *     run record (output, telemetry, per-`tools.call` outcomes);
 *   - the decided card is INLINE TIMELINE HISTORY at its decision position —
 *     after the request and before the assistant's final summary — never a
 *     trailing section appended after the whole transcript;
 *   - the compact "What ran in this session" bar keeps replay-vs-live
 *     unambiguous (replay-only ⇄ N approved live operations);
 *   - deny runs nothing: the card ends `denied` (collapsed), the session stays
 *     replay-only and the request is not retried;
 *   - expiry is a DISTINCT terminal state (dashed, audit kept, nothing ran, no
 *     retry);
 *   - a re-delivered decision for an already-executed request is read-only
 *     evidence — the UI never re-sends it (no second execution).
 *
 * Fully mocked (`page.route()` + fake chat socket): no live backend.
 */

test.describe.configure({ timeout: 120_000 })

const CARD = 'optimization-conversation-dialog-live-test-approval'
const RESOLVED_CARD = 'optimization-conversation-dialog-live-test-resolved-0'
const SESSION_BAR = 'optimization-conversation-dialog-optimization-session-bar'

/** The operator's request that starts the turn (the card's timeline anchor). */
const REQUEST = 'Verify the refund script against the reference run.'
/** The assistant's final summary of the turn. */
const FINAL_REPLY =
  'The live result confirmed the payload shape — the optimized plan is updated.'

async function seed(page: import('@playwright/test').Page, state: OptimizerWorldState) {
  await mockApiCatchAllProxyAware(page)
  await page.addInitScript((token: string) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
  await standardSetup(page)
  await installFakeChatSocket(page)
  await mockPanelWorld(page, { agents: seedAgents() })
  await mockOptimizerApi(page, state)
}

/** Opens the optimizer chat on the typed subject and sends one turn. */
async function startOptimizerChat(page: import('@playwright/test').Page, state: OptimizerWorldState) {
  if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return null
  const details = await openAgentDialog(page, TYPED_AGENT_NAME)
  await openOptimizedPlanTab(details)
  const chat = await openOptimizerChat(page, details)
  await sendChatMessage(page, chat, REQUEST)
  await expect.poll(() => state.createRequests.length).toBe(1)
  return { details, chat }
}

test.describe('Live-test approval — approve runs the approved script once', () => {
  test('review script → approve → running → executed run record → plan ready', async ({
    page,
  }) => {
    const state = typedWorldState({ plan: readyPlan(TYPED_AGENT_ID) })
    await seed(page, state)
    const opened = await startOptimizerChat(page, state)
    if (!opened) return
    const { details, chat } = opened

    // ── 1. The optimizer asks to run ONE saved script, with its preview ─────
    state.liveTestRequests = [ledgerRow()]
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-live-1',
      intervention_type: 'approval',
      reason: 'Replay could not prove the totals step.',
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: liveTestProposal(),
    })

    const card = chat.getByTestId(CARD)
    await expect(card).toBeVisible()
    await expect(card).toHaveAttribute('data-state', 'pending')
    // Pending is the only expanded state.
    await expect(card).toHaveAttribute('data-expanded', 'true')
    await expect(card).toContainText(COPY.approvalRunScriptTitle)
    await expect(card).toContainText(COPY.approvalPendingChip)
    // It names the exact script + version that would run…
    await expect(card.getByTestId(`${CARD}-script`)).toHaveText(
      COPY.approvalScriptVersion(
        LIVE_TEST_SCRIPT.script_name,
        LIVE_TEST_SCRIPT.script_version_label,
      ),
    )
    // …and states plainly that this is the whole script, end to end.
    await expect(card.getByTestId(`${CARD}-subtitle`)).toHaveText(
      COPY.approvalSubtitle(TYPED_AGENT_NAME),
    )
    // The tool-call preview is informational evidence, not the unit of run.
    await expect(card.getByTestId(`${CARD}-preview`)).toContainText(
      COPY.approvalItWillCall(SCRIPT_PREVIEW.map((entry) => entry.tool_name).join(', ')),
    )
    await expect(card.getByTestId(`${CARD}-preview`)).toContainText(COPY.approvalPreviewNote)
    // Single use + not remembered + the answer window are stated.
    await expect(card.getByTestId(`${CARD}-note`)).toContainText(
      COPY.approvalRunsOnceNote(TYPED_AGENT_NAME),
    )
    await expect(card).toContainText(COPY.approvalExpiryPrefix)
    await expect(card.getByTestId(`${CARD}-approve`)).toHaveText(COPY.approvalApprove)
    await expect(card.getByTestId(`${CARD}-deny`)).toBeVisible()
    // Approval card replaces the generic ask card, and input is blocked.
    await expect(chat.getByTestId('optimization-conversation-dialog-optimizer-ask')).toHaveCount(0)
    await expect(chat.getByPlaceholder(COPY.inputBlockedDecision)).toBeDisabled()
    // Nothing has run yet: replay-only is still in force.
    const sessionBar = chat.getByTestId(SESSION_BAR)
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-live-chip`)).toHaveText(
      COPY.auditNoLive,
    )
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-replay-only-chip`)).toHaveText(
      COPY.replayOnly,
    )

    // ── 2. Approve — one decision frame, then the run is in flight ─────────
    await card.getByTestId(`${CARD}-approve`).click()
    await waitForFrame(
      page,
      (frame) =>
        frame.type === 'intervene_response' &&
        frame.request_id === 'req-live-1' &&
        frame.approval_value === true,
    )
    const approvalFrames = (await readChatFrames(page)).filter(
      (frame) => frame.type === 'intervene_response' && frame.request_id === 'req-live-1',
    )
    expect(approvalFrames).toHaveLength(1)

    state.liveTestRequests = [ledgerRow({ status: 'approved' })]
    await emitChat(page, { type: 'intervene_status', request_id: 'req-live-1', status: 'responded' })

    // The answered card collapses into a one-line history summary.
    const running = chat.getByTestId(RESOLVED_CARD)
    await expect(running).toBeVisible()
    await expect(running).toHaveAttribute('data-state', 'running')
    await expect(running).toHaveAttribute('data-expanded', 'false')
    await expect(running).toContainText(COPY.approvalRunningChip)
    await expect(running.getByTestId(`${RESOLVED_CARD}-summary`)).toHaveText(
      COPY.approvalSummaryRunning(TYPED_AGENT_NAME),
    )
    // No actionable controls once the decision is made.
    await expect(running.getByTestId(`${RESOLVED_CARD}-approve`)).toHaveCount(0)
    await expect(running.getByTestId(`${RESOLVED_CARD}-deny`)).toHaveCount(0)
    // Collapsed by the decision: the one-line summary is visible, the detail
    // body stays hidden until the operator expands it, and the decided card is
    // the ONLY processing UI (no second spinner / activity block).
    await expect(running.getByTestId(`${RESOLVED_CARD}-summary`)).toBeVisible()
    await expect(running.getByTestId(`${RESOLVED_CARD}-details`)).toBeHidden()
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimizer-activity'),
    ).toHaveCount(0)
    // The bar says a run is in flight (replay-only chip is replaced).
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-running-chip`)).toHaveText(
      COPY.liveRunning,
    )

    // Expanding the collapsed card shows the script + its preview again.
    await expandLiveTestCard(running)
    await expect(running.getByTestId(`${RESOLVED_CARD}-preview`)).toContainText(
      'crm____lookup_contact',
    )
    // Re-collapse: the operator can expand history, but the default post-turn
    // state stays a one-line summary.
    await collapseLiveTestCard(running)

    // ── 3. The script run record returns into the conversation ─────────────
    const runRecord = scriptRunRecord()
    state.liveTestRequests = [
      ledgerRow({
        status: 'executed',
        executed_operations: [runRecord],
        execution_started_at: '2026-06-01T00:00:05Z',
        execution_finished_at: '2026-06-01T00:00:09Z',
        decision: {
          approval_value: true,
          operator_user_id: 'e2e-admin',
          responded_at: '2026-06-01T00:00:04Z',
        },
      }),
    ]
    state.audit = {
      replay_verifications: 1,
      live_operations: 2,
      last_live_at: '2026-06-01T00:00:09Z',
      replay_only: false,
    }
    await emitChat(page, {
      type: 'live_test_result',
      live_test_request_id: 'ltr-e2e-1',
      live_test_status: 'executed',
      executed_operations: [runRecord],
      script_run: runRecord,
    })

    const executed = chat.getByTestId(RESOLVED_CARD)
    await expect(executed).toHaveAttribute('data-state', 'executed')
    // Collapsed to a one-line history summary (chip + script + short result).
    await expect(executed).toHaveAttribute('data-expanded', 'false')
    await expect(executed).toContainText(COPY.approvalExecutedChip)
    await expect(executed.getByTestId(`${RESOLVED_CARD}-script`)).toHaveText(
      LIVE_TEST_SCRIPT.script_name,
    )
    await expect(executed.getByTestId(`${RESOLVED_CARD}-summary`)).toContainText(
      'refunded',
    )
    // Expand to the script run record: output, telemetry, per-call outcomes.
    await expandLiveTestCard(executed)
    await expect(executed.getByTestId(`${RESOLVED_CARD}-result`)).toContainText('refunded')
    await expect(executed.getByTestId(`${RESOLVED_CARD}-telemetry`)).toContainText(
      COPY.approvalToolCalls(2),
    )
    await expect(executed.getByTestId(`${RESOLVED_CARD}-tool-call-0`)).toContainText(
      'crm____lookup_contact',
    )
    await expect(executed.getByTestId(`${RESOLVED_CARD}-tool-call-0`)).toContainText('contact found')
    await expect(executed.getByTestId(`${RESOLVED_CARD}-tool-call-1`)).toContainText(
      'crm____list_deals',
    )
    await expect(executed.getByTestId(`${RESOLVED_CARD}-tool-call-1`)).toContainText('2 open deals')
    await expect(executed).toContainText(COPY.approvalUsedOncePrefix)
    // The used approval is not actionable again — content, not controls.
    await expect(executed.getByTestId(`${RESOLVED_CARD}-approve`)).toHaveCount(0)
    await expect(executed.getByTestId(`${RESOLVED_CARD}-deny`)).toHaveCount(0)
    // Re-collapse after inspecting: it stays a one-line history summary by default.
    await collapseLiveTestCard(executed)

    // The in-flight marker is cleared: the bar reports the used test.
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-running-chip`)).toHaveCount(0)
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-live-chip`)).toHaveText(
      COPY.auditLiveUsed(2),
    )

    // ── 4. Replay vs live is unambiguous (collapsed bar's audit detail) ────
    await expandSessionBar(chat)
    const audit = sessionBar.getByTestId(`${SESSION_BAR}-audit`)
    await expect(audit).toBeVisible()
    await expect(audit.getByTestId(`${SESSION_BAR}-audit-replay`)).toContainText(
      COPY.auditReplay(1),
    )
    await expect(audit.getByTestId(`${SESSION_BAR}-audit-live`)).toContainText(
      COPY.auditLiveUsed(2),
    )
    await expect(audit.getByTestId(`${SESSION_BAR}-audit-replay-only`)).toHaveCount(0)
    await expect(audit).toContainText('single use')

    // ── 5. The refinement continues and the plan lands without a reload ────
    const planReadsBefore = state.planReads
    state.plan = readyPlan(TYPED_AGENT_ID)
    await emitChat(page, {
      sender_role: 'agent',
      content: FINAL_REPLY,
      final: true,
    })
    await expect(chat.getByText(FINAL_REPLY)).toBeVisible()
    await expect.poll(() => state.planReads, { timeout: 20_000 }).toBeGreaterThan(planReadsBefore)

    // ── 5b. Inline timeline placement ─────────────────────────────────────
    // The decided card is CHAT HISTORY at its decision position — after the
    // operator's request and BEFORE the assistant's final summary. It must
    // never be appended as a trailing section after everything else.
    const decidedCard = chat.getByTestId(RESOLVED_CARD)
    const requestBubble = chat.getByText(REQUEST).first()
    const summaryBubble = chat.getByText(FINAL_REPLY).first()
    const [requestBox, cardBox, summaryBox] = await Promise.all([
      requestBubble.boundingBox(),
      decidedCard.boundingBox(),
      summaryBubble.boundingBox(),
    ])
    expect(requestBox).not.toBeNull()
    expect(cardBox).not.toBeNull()
    expect(summaryBox).not.toBeNull()
    expect(cardBox!.y).toBeGreaterThan(requestBox!.y)
    expect(cardBox!.y).toBeLessThan(summaryBox!.y)
    // And it stays collapsed in history once the turn finished.
    await expect(decidedCard).toHaveAttribute('data-expanded', 'false')

    await closeChatDialog(chat)
    await expect(details.getByTestId('optimized-plan-status')).toHaveText('ready')

    // ── 6. A further need requires a NEW request + NEW approval ────────────
    // Reopening starts a fresh chat surface (the optimization session is
    // per-conversation), so nothing from the used approval is actionable or
    // inherited — the previous request can only reappear via its own ledger
    // read once a session exists again.
    await openOptimizedPlanTab(details)
    const reopen = await openOptimizerChat(page, details)
    await expect(reopen.getByTestId(CARD)).toHaveCount(0)
    await expect(reopen.getByTestId(RESOLVED_CARD)).toHaveCount(0)
    await sendChatMessage(page, reopen, 'Now optimise the tool-call path too.')
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-live-2',
      intervention_type: 'approval',
      reason: 'A second live test is needed.',
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: liveTestProposal({
        live_test_request_id: 'ltr-e2e-2',
        script_name: 'refund-verification-v2',
        script_version_label: 'v4',
        operations: [SCRIPT_PREVIEW[0]],
      }),
    })
    const second = reopen.getByTestId(CARD)
    await expect(second).toHaveAttribute('data-state', 'pending')
    await expect(second).toHaveAttribute('data-expanded', 'true')
    await expect(second.getByTestId(`${CARD}-approve`)).toBeEnabled()
    // A fresh script — nothing was inherited from the used approval.
    await expect(second.getByTestId(`${CARD}-script`)).toHaveText(
      COPY.approvalScriptVersion('refund-verification-v2', 'v4'),
    )
    await expect(second.getByTestId(`${CARD}-preview`)).toContainText('crm____lookup_contact')
    await expect(second.getByTestId(`${CARD}-preview`)).not.toContainText('crm____list_deals')
  })

  test('deny runs nothing, keeps replay-only and does not retry', async ({ page }) => {
    const state = typedWorldState({ plan: readyPlan(TYPED_AGENT_ID) })
    // A replay verification already happened in this session; nothing went live.
    state.audit = {
      replay_verifications: 1,
      live_operations: 0,
      last_live_at: null,
      replay_only: true,
    }
    await seed(page, state)
    const opened = await startOptimizerChat(page, state)
    if (!opened) return
    const { chat } = opened

    state.liveTestRequests = [ledgerRow()]
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-live-deny',
      intervention_type: 'approval',
      reason: 'Approve one live script run?',
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: liveTestProposal(),
    })
    const card = chat.getByTestId(CARD)
    await expect(card).toHaveAttribute('data-state', 'pending')

    await card.getByTestId(`${CARD}-deny`).click()
    await waitForFrame(
      page,
      (frame) =>
        frame.type === 'intervene_response' &&
        frame.request_id === 'req-live-deny' &&
        frame.approval_value === false,
    )
    // Never an approval for the denied request.
    const frames = (await readChatFrames(page)).filter(
      (frame) => frame.type === 'intervene_response' && frame.request_id === 'req-live-deny',
    )
    expect(frames.filter((frame) => frame.approval_value === true)).toEqual([])

    // Server records the denial — attribution + empty evidence.
    state.liveTestRequests = [
      ledgerRow({
        status: 'denied',
        executed_operations: null,
        decision: {
          approval_value: false,
          operator_user_id: 'e2e-admin',
          responded_at: '2026-06-01T00:00:04Z',
        },
      }),
    ]
    await emitChat(page, { type: 'intervene_status', request_id: 'req-live-deny', status: 'responded' })

    const denied = chat.getByTestId(RESOLVED_CARD)
    await expect(denied).toHaveAttribute('data-state', 'denied')
    await expect(denied).toHaveAttribute('data-expanded', 'false')
    await expect(denied).toContainText(COPY.approvalDeniedChip)
    await expect(denied.getByTestId(`${RESOLVED_CARD}-summary`)).toHaveText(
      COPY.approvalSummaryDenied,
    )
    await expect(denied.getByTestId(`${RESOLVED_CARD}-approve`)).toHaveCount(0)
    await expandLiveTestCard(denied)
    await expect(denied).toContainText(COPY.approvalDeniedNotePrefix)

    // Still replay-only: nothing live ran, nothing is retried.
    const sessionBar = chat.getByTestId(SESSION_BAR)
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-live-chip`)).toHaveText(
      COPY.auditNoLive,
    )
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-replay-only-chip`)).toHaveText(
      COPY.replayOnly,
    )
    await expandSessionBar(chat)
    const audit = sessionBar.getByTestId(`${SESSION_BAR}-audit`)
    await expect(audit.getByTestId(`${SESSION_BAR}-audit-live`)).toContainText(
      COPY.auditNoLive,
    )
    await expect(audit.getByTestId(`${SESSION_BAR}-audit-replay-only`)).toBeVisible()
    expect(state.liveTestRequests[0]).toMatchObject({ status: 'denied', executed_operations: null })
    expect(state.liveTestRequests).toHaveLength(1)

    // The turn ends with a bounded stop and no further live request.
    await emitChat(page, {
      sender_role: 'agent',
      content: 'Without the live check I stopped here — the plan needs the payload shape you can describe.',
      final: true,
    })
    await expect(chat.getByText(/Without the live check I stopped here/)).toBeVisible()
    expect(state.liveTestRequests).toHaveLength(1)
    // Only the conversation create was ever written.
    expect(mutationRequests(state)).toEqual(['POST /api/v1/conversations/optimization'])
  })

  test('expiry is a distinct terminal state — nothing ran and no retry', async ({ page }) => {
    const state = typedWorldState({ plan: readyPlan(TYPED_AGENT_ID) })
    await seed(page, state)
    const opened = await startOptimizerChat(page, state)
    if (!opened) return
    const { chat } = opened

    const expiredAt = new Date(Date.now() - 60_000).toISOString()
    state.liveTestRequests = [ledgerRow({ expires_at: expiredAt })]
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-live-expired',
      intervention_type: 'approval',
      reason: 'Approve this live script run?',
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: liveTestProposal({ expires_at: expiredAt }),
    })
    // While unanswered the card is still a pending decision.
    await expect(chat.getByTestId(CARD)).toHaveAttribute('data-state', 'pending')

    // The answer window closes: the sweep closes the intervention and the
    // stored outcome is surfaced (no execution evidence).
    state.liveTestRequests = [
      ledgerRow({ status: 'expired', expires_at: expiredAt, executed_operations: null }),
    ]
    await emitChat(page, { type: 'intervene_status', request_id: 'req-live-expired', status: 'expired' })

    const expired = chat.getByTestId(RESOLVED_CARD)
    await expect(expired).toHaveAttribute('data-state', 'expired')
    await expect(expired).toHaveAttribute('data-expanded', 'false')
    await expect(expired.getByTestId(`${RESOLVED_CARD}-expired-chip`)).toContainText(
      COPY.approvalExpiredChip,
    )
    await expect(expired.getByTestId(`${RESOLVED_CARD}-summary`)).toHaveText(
      COPY.approvalSummaryExpired,
    )
    // Distinct copy: the preview is kept for audit, nothing ran, it is not
    // retried — and the collapsed summary says so at a glance.
    await expandLiveTestCard(expired)
    await expect(expired).toContainText(COPY.approvalNoteExpiredPrefix)
    await expect(expired.getByTestId(`${RESOLVED_CARD}-approve`)).toHaveCount(0)
    await expect(expired.getByTestId(`${RESOLVED_CARD}-deny`)).toHaveCount(0)

    // Replay-only is still in force, and no approval frame was ever sent.
    const sessionBar = chat.getByTestId(SESSION_BAR)
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-live-chip`)).toHaveText(
      COPY.auditNoLive,
    )
    await expect(sessionBar.getByTestId(`${SESSION_BAR}-replay-only-chip`)).toHaveText(
      COPY.replayOnly,
    )
    const frames = await readChatFrames(page)
    expect(frames.filter((frame) => frame.type === 'intervene_response')).toEqual([])
    expect(state.liveTestRequests[0]).toMatchObject({
      status: 'expired',
      executed_operations: null,
      decision: null,
    })
    expect(state.liveTestRequests).toHaveLength(1)
  })

  test('a re-delivered decision for an already-executed request executes nothing', async ({
    page,
  }) => {
    const state = typedWorldState({ plan: readyPlan(TYPED_AGENT_ID) })
    const runRecord = scriptRunRecord()
    state.liveTestRequests = [
      ledgerRow({
        status: 'executed',
        executed_operations: [runRecord],
        execution_started_at: '2026-06-01T00:00:05Z',
        execution_finished_at: '2026-06-01T00:00:09Z',
        decision: {
          approval_value: true,
          operator_user_id: 'e2e-admin',
          responded_at: '2026-06-01T00:00:04Z',
        },
      }),
    ]
    state.audit = {
      replay_verifications: 0,
      live_operations: 2,
      last_live_at: '2026-06-01T00:00:09Z',
      replay_only: false,
    }
    await seed(page, state)
    const opened = await startOptimizerChat(page, state)
    if (!opened) return
    const { chat } = opened

    // A stale/replayed decision arrives for the used request.
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-live-replay',
      intervention_type: 'approval',
      reason: 'Approve this live script run?',
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: liveTestProposal({
        status: 'executed',
        executed_operations: [runRecord],
      }),
    })

    const card = chat.getByTestId(CARD)
    await expect(card).toHaveAttribute('data-state', 'executed')
    // Already decided → collapsed read-only history, never a live card.
    await expect(card).toHaveAttribute('data-expanded', 'false')
    await expect(card).toContainText(COPY.approvalExecutedChip)
    await expandLiveTestCard(card)
    await expect(card).toContainText(COPY.approvalUsedOncePrefix)
    // No way to approve/deny it again, and the UI sent no second decision.
    await expect(card.getByTestId(`${CARD}-approve`)).toHaveCount(0)
    await expect(card.getByTestId(`${CARD}-deny`)).toHaveCount(0)
    const frames = await readChatFrames(page)
    expect(frames.filter((frame) => frame.type === 'intervene_response')).toEqual([])
    // Only the conversation-create write happened in this session.
    expect(mutationRequests(state)).toEqual(['POST /api/v1/conversations/optimization'])
    expect(TYPED_AGENT_ID).toBe('at-a')
  })

  /**
   * Session bar after an approved live test finished (was FIXME).
   *
   * `ConversationDialog` sets `liveTestApprovedRequestId` on approve and used to
   * clear it only on close/reset, while the chrome treated a non-null value as
   * "running" — so a completed run kept claiming to be in flight next to a
   * run record that correctly said it ran once and is spent. Fix: the marker is
   * cleared when the result chunk (or a terminal ledger row) for that request
   * arrives, so the bar falls back to "N approved live operations".
   */
  test(
    'the session bar reports the used live test after its result landed',
    async ({ page }) => {
      const state = typedWorldState({ plan: readyPlan(TYPED_AGENT_ID) })
      await seed(page, state)
      const opened = await startOptimizerChat(page, state)
      if (!opened) return
      const { chat } = opened

      state.liveTestRequests = [ledgerRow()]
      await emitChat(page, {
        type: 'intervene_request',
        request_id: 'req-live-chip',
        intervention_type: 'approval',
        reason: 'Approve this live script run?',
        delegation_depth: 0,
        conversation_session_id: 'conv-opt-1',
        live_test: liveTestProposal(),
      })
      await chat.getByTestId(`${CARD}-approve`).click()
      const sessionBar = chat.getByTestId(SESSION_BAR)
      await expect(sessionBar.getByTestId(`${SESSION_BAR}-running-chip`)).toBeVisible()

      const runRecord = scriptRunRecord()
      state.audit = {
        replay_verifications: 0,
        live_operations: 2,
        last_live_at: '2026-06-01T00:00:09Z',
        replay_only: false,
      }
      await emitChat(page, {
        type: 'live_test_result',
        live_test_request_id: 'ltr-e2e-1',
        live_test_status: 'executed',
        executed_operations: [runRecord],
        script_run: runRecord,
      })

      await expect(chat.getByTestId(RESOLVED_CARD)).toHaveAttribute('data-state', 'executed')
      // The bar must stop claiming a run is in flight once the result arrived.
      await expect(sessionBar.getByTestId(`${SESSION_BAR}-running-chip`)).toHaveCount(0)
      await expect(sessionBar.getByTestId(`${SESSION_BAR}-live-chip`)).toHaveText(
        COPY.auditLiveUsed(2),
      )
    },
  )
})
