import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'
import {
  BUSINESS_CONVERSATION_ID,
  CONV_AGENT_ID,
  CONV_AGENT_NAME,
  COPY,
  TYPED_AGENT_ID,
  TYPED_AGENT_NAME,
  assertNoReload,
  closeChatDialog,
  conversationalWorldState,
  emitChat,
  gotoAgentsList,
  installFakeChatSocket,
  markNoReload,
  mockOptimizerApi,
  mutationRequests,
  openAgentDialog,
  openOptimizedPlanTab,
  openOptimizerChat,
  readChatFrames,
  readyPlan,
  sendChatMessage,
  expandSessionBar,
  typedWorldState,
  waitForChatSocket,
  waitForFrame,
  type OptimizerWorldState,
} from './_agent_optimizer_world'

/**
 * E2E: the conversational optimizer on the subject agent type itself
 * (`docs/changes/optimizer-conversational-agent/test-plan.md` → E2E layer).
 *
 * Fully mocked (`page.route()` + a fake chat socket): no live backend.
 *
 * Journeys:
 *   1. TYPED subject: the Optimized Plan tab offers "Talk to optimizer" scoped
 *      to that agent → the chat opens already in optimization mode (subject
 *      identity, replay-only, scope bar, no separate optimizer chrome) → the
 *      first message creates the optimization conversation through the
 *      SUBJECT-ONLY endpoint → the streaming turn shows exactly ONE processing
 *      indicator (the chat-status indicator; the old folded "optimizer
 *      activity" block is gone) → the plan refreshes after the turn without a
 *      reload.
 *   2. CONVERSATIONAL subject: the same entry opens the same chat with the
 *      conversational scope; a missing plan is informational and opening starts
 *      no work.
 *   3. In-chat ask/decide: a question pauses the turn, blocks the composer and
 *      is answered once from inside the conversation.
 *   4. Out-of-scope request: the refusal is explained in the conversation and
 *      nothing is written.
 *   5. Business conversation on the same agent type keeps the ordinary chat —
 *      no optimization chrome, no optimizer model/ledger reads.
 */

test.describe.configure({ timeout: 120_000 })

const MESSAGE = 'Tighten the refund verification script using the reference run.'
const REPLY =
  'I replayed the reference run, authored a refund script and verified it — the optimized plan is ready.'

const INITIAL_PLAN_STEP = 'Query refunds (initial plan)'
const REFRESHED_PLAN_STEP = 'Query refunds (conversation-authored)'

async function seed(page: import('@playwright/test').Page, state: OptimizerWorldState) {
  // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
  await mockApiCatchAllProxyAware(page)
  await page.addInitScript((token: string) => {
    localStorage.setItem('access_token', token)
  }, FAKE_TOKEN)
  await standardSetup(page)
  await installFakeChatSocket(page)
  await mockPanelWorld(page, { agents: seedAgents() })
  await mockOptimizerApi(page, state)
}

/** A typed subject that already has an optimized plan (the normal case). */
function typedWorldWithPlan(
  stepName: string,
  overrides: Partial<OptimizerWorldState> = {},
): OptimizerWorldState {
  return typedWorldState({
    plan: readyPlan(TYPED_AGENT_ID, {
      steps: [
        {
          order: 1,
          type: 'tool_call',
          name: stepName,
          description: 'From the current optimized plan',
          python_source: null,
          scriptable: true,
        },
      ],
    }),
    ...overrides,
  })
}

test.describe('Conversational optimizer — conversation journey (mocked)', () => {
  test('typed agent: entry → scoped chat → single status indicator → plan refresh without a reload', async ({
    page,
  }) => {
    const state = typedWorldWithPlan(INITIAL_PLAN_STEP)
    await seed(page, state)
    if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return

    const details = await openAgentDialog(page, TYPED_AGENT_NAME)
    await openOptimizedPlanTab(details)

    // ── 1. The entry is a mode of THIS agent, not a separate optimizer ──────
    const entry = details.getByTestId('talk-to-optimizer-entry')
    await expect(entry).toBeVisible()
    const talk = details.getByTestId('talk-to-optimizer')
    await expect(talk).toBeEnabled()
    await expect(talk).toHaveText(COPY.talkToOptimizer)
    await expect(details.getByTestId('talk-to-optimizer-identity')).toHaveText(
      COPY.identityParity,
    )
    await expect(entry).toContainText(COPY.scopedTo(TYPED_AGENT_NAME))
    // The workspace optimizer model it would run on is disclosed.
    await expect(entry).toContainText('gpt-4o')
    // The existing one-shot plan actions are retained beside the entry.
    await expect(details.getByTestId('optimized-plan-status')).toHaveText('ready')
    await expect(details.getByTestId('retire-optimized-plan')).toBeVisible()
    await expect(details.getByText(INITIAL_PLAN_STEP)).toBeVisible()

    await markNoReload(page)
    const chat = await openOptimizerChat(page, details)

    // ── 2. The chat IS the agent in optimization mode ──────────────────────
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimization-mode-chip'),
    ).toHaveText(COPY.modeOnAgent(TYPED_AGENT_NAME))
    // Identity parity is the chip's tooltip (no header block).
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimization-identity'),
    ).toHaveAttribute('title', COPY.identityParity)

    // The only chrome above the transcript is the compact "What ran in this
    // session" bar, and it is collapsed by default.
    const sessionBar = chat.getByTestId(
      'optimization-conversation-dialog-optimization-session-bar',
    )
    await expect(sessionBar).toContainText(COPY.sessionBarTitle)
    await expect(sessionBar).toHaveAttribute('data-expanded', 'false')
    // Replay-only is the default and is stated up front (summary chips).
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-live-chip',
      ),
    ).toHaveText(COPY.auditNoLive)
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-replay-only-chip',
      ),
    ).toHaveText(COPY.replayOnly)
    // No scope header block exists any more.
    expect(await chat.getByTestId('optimization-conversation-dialog-optimization-mode-bar').count()).toBe(0)

    // Expanding reveals the audit detail, identity parity and the scope.
    await expandSessionBar(chat)
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-identity',
      ),
    ).toHaveText(COPY.identityParity)
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-scope',
      ),
    ).toHaveText(COPY.scopePlan(TYPED_AGENT_NAME))
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-audit',
      ),
    ).toBeVisible()
    // No invented optimizer persona/identity anywhere on the chat surface.
    const chatText = (await chat.textContent()) ?? ''
    expect(chatText).not.toMatch(/separate optimizer agent/i)
    expect(chatText).not.toMatch(/optimizer agent type/i)
    expect(chatText).not.toMatch(/optimizer role/i)

    // ── 3. Opening starts no work (no session, no turn, no write) ──────────
    expect(state.createRequests).toHaveLength(0)
    expect(mutationRequests(state)).toEqual([])

    // ── 4. The first message creates the subject-only optimization session ─
    await sendChatMessage(page, chat, MESSAGE)
    await expect.poll(() => state.createRequests.length).toBe(1)
    // Exactly the subject — no channel/scope/second agent type is client-sent.
    expect(state.createRequests[0]).toEqual({ agent_type_id: TYPED_AGENT_ID })
    await waitForFrame(page, (frame) => frame.message === MESSAGE)
    expect(state.businessCreateRequests).toEqual([])
    // The turn is now streaming: the composer reports that it is working.
    await expect(chat.getByPlaceholder('The optimizer is working…')).toBeVisible()

    // ── 5. The ONLY processing UI is the single chat-status indicator ────────
    // The separate folded "optimizer activity" block was removed: the normal
    // chat-status indicator is the only processing surface during a turn.
    const activityBlock = chat.getByTestId(
      'optimization-conversation-dialog-optimizer-activity',
    )
    await expect(activityBlock).toHaveCount(0)
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimizer-activity-toggle'),
    ).toHaveCount(0)
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimizer-activity-step'),
    ).toHaveCount(0)

    const indicator = chat.getByTestId(
      'optimization-conversation-dialog-chat-status-indicator',
    )
    // Exactly one indicator while the turn streams — never a second spinner.
    await expect(indicator).toHaveCount(1)
    await emitChat(page, { type: 'chat_status', status: 'thinking' })
    await expect(indicator).toHaveCount(1)
    await expect(indicator).toContainText(COPY.statusThinking)

    await emitChat(page, { type: 'chat_status', status: 'using_tool', tool_name: 'execute_script' })
    // Still one indicator: the status updates in place, it does not accumulate.
    await expect(indicator).toHaveCount(1)
    await expect(indicator).toContainText(COPY.statusUsingTool('execute_script'))
    await emitChat(page, { type: 'chat_status', status: 'using_tool', tool_name: 'generate_script' })
    await expect(indicator).toHaveCount(1)
    await expect(indicator).toContainText(COPY.statusUsingTool('generate_script'))
    await expect(
      chat.getByTestId('optimization-conversation-dialog-chat-status-indicator'),
    ).toHaveCount(1)

    // ── 6. The finished turn reports its outcome ───────────────────────────
    const planReadsBefore = state.planReads
    // The turn authored a new plan server-side while the operator watched.
    state.plan = readyPlan(TYPED_AGENT_ID, {
      id: 'oplan-e2e-2',
      steps: [
        {
          order: 1,
          type: 'tool_call',
          name: REFRESHED_PLAN_STEP,
          description: 'Authored in the optimization conversation',
          python_source: null,
          scriptable: true,
        },
      ],
    })
    await emitChat(page, { sender_role: 'agent', content: REPLY, final: true })

    await expect(chat.getByText(REPLY)).toBeVisible()
    // No processing UI at all once the turn is terminal — the indicator is gone
    // and the folded activity block never appears as a stand-in.
    await expect(
      chat.getByTestId('optimization-conversation-dialog-chat-status-indicator'),
    ).toHaveCount(0)
    await expect(activityBlock).toHaveCount(0)
    // The turn finished — the composer is ready for the next message.
    await expect(chat.getByPlaceholder(COPY.inputPlaceholder)).toBeVisible()

    // ── 7. The plan refreshes after the turn — no manual reload ────────────
    await expect.poll(() => state.planReads, { timeout: 20_000 }).toBeGreaterThan(planReadsBefore)
    await closeChatDialog(chat)
    await expect(details.getByTestId('optimized-plan-status')).toHaveText('ready')
    await expect(details.getByText(REFRESHED_PLAN_STEP)).toBeVisible()
    await expect(details.getByText(INITIAL_PLAN_STEP)).toHaveCount(0)
    // The one-shot Optimize path was never triggered by the conversation.
    expect(state.requests.filter((r) => r.includes('/agents/sessions/optimize'))).toEqual([])
    await assertNoReload(page)
  })

  test('conversational agent: same entry, informational empty state, no work started', async ({
    page,
  }) => {
    const state = conversationalWorldState()
    await seed(page, state)
    if (!(await gotoAgentsList(page, CONV_AGENT_NAME))) return

    const details = await openAgentDialog(page, CONV_AGENT_NAME)
    await openOptimizedPlanTab(details)

    // The previous conversational restriction is gone: the same action exists,
    // annotated with the same scope promise.
    const talk = details.getByTestId('talk-to-optimizer')
    await expect(talk).toBeVisible()
    await expect(talk).toBeEnabled()
    await expect(details.getByTestId('talk-to-optimizer-entry')).toContainText(
      COPY.scopedTo(CONV_AGENT_NAME),
    )
    // Unset model inherits the plan-authoring model, and the entry says so.
    await expect(details.getByTestId('talk-to-optimizer-entry')).toContainText(
      COPY.modelInherited,
    )
    // A missing optimized plan is INFORMATION, not a hidden entry.
    await expect(details.getByTestId('optimized-plan-absent')).toBeVisible()
    await expect(details.getByText(COPY.emptyTitle)).toBeVisible()
    await expect(details.getByText('No optimized plan.')).toBeVisible()

    await markNoReload(page)
    const chat = await openOptimizerChat(page, details)

    // Conversational scope, and it is still the agent itself.
    const sessionBar = chat.getByTestId(
      'optimization-conversation-dialog-optimization-session-bar',
    )
    await expect(sessionBar).toHaveAttribute('data-expanded', 'false')
    await expandSessionBar(chat)
    await expect(
      sessionBar.getByTestId(
        'optimization-conversation-dialog-optimization-session-bar-scope',
      ),
    ).toHaveText(COPY.scopeConversational(CONV_AGENT_NAME))
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimization-mode-chip'),
    ).toHaveText(COPY.modeOnAgent(CONV_AGENT_NAME))

    // Opening starts no work: no session, no plan generation, no live request.
    expect(state.createRequests).toHaveLength(0)
    expect(mutationRequests(state)).toEqual([])
    expect(state.requests.filter((r) => r.includes('/agents/sessions/optimize'))).toEqual([])
    expect(state.requests.filter((r) => r.includes('regenerate-plan'))).toEqual([])
    expect(state.requests.filter((r) => r.includes('/live-test-requests'))).toEqual([])

    // Nothing was fabricated for a conversational agent: still no plan.
    await closeChatDialog(chat)
    await expect(details.getByTestId('optimized-plan-absent')).toBeVisible()
    await assertNoReload(page)
  })

  test('in-chat ask/decide: the question pauses the turn and is answered once', async ({ page }) => {
    const state = typedWorldWithPlan(INITIAL_PLAN_STEP)
    await seed(page, state)
    if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return

    const details = await openAgentDialog(page, TYPED_AGENT_NAME)
    await openOptimizedPlanTab(details)
    const chat = await openOptimizerChat(page, details)
    await sendChatMessage(page, chat, MESSAGE)
    await expect.poll(() => state.createRequests.length).toBe(1)

    // ── The optimizer asks, in-chat (not the interventions dashboard) ──────
    await emitChat(page, {
      type: 'intervene_request',
      request_id: 'req-ask-1',
      intervention_type: 'choice',
      reason: 'Which field should the refined script summarise?',
      choices: ['summary', 'raw_json'],
      delegation_depth: 0,
      conversation_session_id: 'conv-opt-1',
      live_test: null,
    })

    const ask = chat.getByTestId('optimization-conversation-dialog-optimizer-ask')
    await expect(ask).toBeVisible()
    await expect(ask).toContainText('Which field should the refined script summarise?')
    await expect(chat.getByTestId('optimization-conversation-dialog-optimizer-ask-chip')).toHaveText(
      COPY.askChip,
    )
    // The composer is blocked until the operator decides — no second turn.
    await expect(chat.getByPlaceholder(COPY.inputBlockedDecision)).toBeDisabled()

    // ── Answering resolves the request once through the chat socket ────────
    await ask
      .getByTestId('optimization-conversation-dialog-optimizer-ask-choice-summary')
      .click()
    await waitForFrame(
      page,
      (frame) =>
        frame.type === 'intervene_response' &&
        frame.request_id === 'req-ask-1' &&
        frame.selected_choice === 'summary',
    )
    const answerFrames = (await readChatFrames(page)).filter(
      (frame) => frame.type === 'intervene_response' && frame.request_id === 'req-ask-1',
    )
    expect(answerFrames).toHaveLength(1)

    // Server confirms the pause resolved — the answer stays in the record.
    await emitChat(page, { type: 'intervene_status', request_id: 'req-ask-1', status: 'responded' })
    await expect(page.getByTestId('resolved-intervention-bubble').last()).toContainText('summary')
    await expect(ask).toHaveCount(0)

    await emitChat(page, {
      sender_role: 'agent',
      content: 'Thanks — summarising the record now.',
      final: true,
    })
    await expect(chat.getByText('Thanks — summarising the record now.')).toBeVisible()
  })

  test('an out-of-scope request is declined in the conversation with zero writes', async ({
    page,
  }) => {
    const state = typedWorldWithPlan(INITIAL_PLAN_STEP)
    await seed(page, state)
    if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return

    const details = await openAgentDialog(page, TYPED_AGENT_NAME)
    await openOptimizedPlanTab(details)
    const chat = await openOptimizerChat(page, details)
    await sendChatMessage(page, chat, 'Read the other agent type’s scripts and delete its plan.')
    await expect.poll(() => state.createRequests.length).toBe(1)
    await waitForChatSocket(page)

    const mutationsBefore = mutationRequests(state).length

    // The server refuses the scope drift; the UI explains it in-channel.
    await emitChat(page, {
      type: 'chat_error',
      code: 'optimization_out_of_scope',
      message: 'Nothing was changed.',
    })
    await expect(
      chat.getByTestId('optimization-conversation-dialog-optimizer-chat-error'),
    ).toContainText(COPY.outOfScope)

    // Zero writes: the refusal created no turn, no plan and no approval.
    expect(mutationRequests(state)).toHaveLength(mutationsBefore)
    expect(state.liveTestRequests).toEqual([])
    expect(state.respondRequests).toEqual([])
    // And no other agent type's plan/scripts/logs were read or written.
    expect(
      state.requests.filter(
        (r) =>
          r.includes(`/agents/types/${CONV_AGENT_ID}/optimized-plan`) ||
          r.includes(`/agents/types/${CONV_AGENT_ID}/regenerate-plan`) ||
          r.includes(`/agents/types/${CONV_AGENT_ID}/scripts`) ||
          r.includes(`/agents/types/${CONV_AGENT_ID}/execution-log`),
      ),
    ).toEqual([])
  })

  test('a business conversation on the same agent type keeps the ordinary chat', async ({ page }) => {
    const state = conversationalWorldState()
    await seed(page, state)
    if (!(await gotoAgentsList(page, CONV_AGENT_NAME))) return

    const details = await openAgentDialog(page, CONV_AGENT_NAME)
    // Business chat is started from the details dialog footer.
    await details.getByRole('button', { name: 'Start Chat' }).click()

    const businessChat = page
      .getByRole('dialog')
      .filter({ has: page.getByPlaceholder(/Type a message/) })
    await expect(businessChat).toBeVisible()

    // No optimization chrome leaks into a business conversation.
    await expect(
      businessChat.getByTestId('conversation-dialog-optimization-mode-chip'),
    ).toHaveCount(0)
    await expect(
      businessChat.getByTestId('conversation-dialog-optimization-session-bar'),
    ).toHaveCount(0)
    await expect(
      businessChat.getByTestId('conversation-dialog-optimizer-model-alert'),
    ).toHaveCount(0)
    await expect(businessChat.getByTestId('conversation-dialog-optimizer-audit')).toHaveCount(0)

    // The composer keeps the ordinary business placeholder.
    const composer = businessChat.getByPlaceholder(/Type a message/)
    await expect(composer).toBeEnabled()
    await composer.fill('Hello from a business conversation.')
    await businessChat.getByRole('button', { name: 'Send', exact: true }).click()

    // It creates a BUSINESS conversation — never the optimization endpoint.
    await expect.poll(() => state.businessCreateRequests.length).toBe(1)
    await waitForChatSocket(page)
    expect(state.businessCreateRequests[0]).toEqual({ agent_type_id: CONV_AGENT_ID })
    expect(state.createRequests).toEqual([])
    // And it never touches the optimizer model / ledger surfaces.
    expect(state.requests.filter((r) => r.endsWith('/optimization'))).toEqual([])
    expect(state.requests.filter((r) => r.includes('/live-test-requests'))).toEqual([])

    await emitChat(page, { sender_role: 'agent', content: 'Hello! How can I help?', final: true })
    await expect(businessChat.getByText('Hello! How can I help?')).toBeVisible()
    // Activity expansion is optimization-only.
    await expect(businessChat.getByTestId('conversation-dialog-optimizer-activity')).toHaveCount(0)
    expect(BUSINESS_CONVERSATION_ID).toBeTruthy()
  })

  /**
   * Session survival on a subject WITHOUT an optimized plan (was FIXME).
   *
   * `AgentOptimizedPlanTab` used to render `ConversationDialog` from three
   * different return branches (loading spinner / "no plan" alert / full plan),
   * so any branch switch remounted the dialog and dropped its session state.
   * `ConversationDialog` also counted the conversation-create request as a turn
   * in flight (`isResuming` fed `turnStreaming`), so when the create resolved it
   * called `onOptimizationTurnSettled()` → the tab invalidated the plan queries
   * → the 404 plan query refetched with no data (`isLoading === true`) → the tab
   * flipped to the loading branch → the chat remounted, the websocket was closed
   * and the just-created session was forgotten.
   *
   * Fix: the dialog is mounted ONCE outside the plan section, and only REAL turn
   * activity (not the create request) is reported to the host.
   */
  test(
    'typed agent with NO optimized plan can send the first message and keep the session',
    async ({ page }) => {
      const state = typedWorldState()
      await seed(page, state)
      if (!(await gotoAgentsList(page, TYPED_AGENT_NAME))) return

      const details = await openAgentDialog(page, TYPED_AGENT_NAME)
      await openOptimizedPlanTab(details)
      await expect(details.getByTestId('optimized-plan-absent')).toBeVisible()
      const chat = await openOptimizerChat(page, details)
      await sendChatMessage(page, chat, MESSAGE)

      // The session must survive the plan invalidation triggered by the create.
      await expect.poll(() => state.createRequests.length).toBe(1)
      await waitForFrame(page, (frame) => frame.message === MESSAGE)
      await emitChat(page, { sender_role: 'agent', content: REPLY, final: true })
      await expect(chat.getByText(REPLY)).toBeVisible()
      // Exactly one conversation was ever opened.
      expect(state.createRequests).toHaveLength(1)
    },
  )
})
