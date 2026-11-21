import { expect, test, type Page, type Route } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'

/**
 * E2E: separate Optimization from Execution — the composed Optimize gate.
 *
 * Fully mocked (mock-first convention, `page.route()`): no live backend.
 *
 * The gate composes three preconditions in order
 * (docs/changes/separate-optimization-from-execution/test-plan.md —
 * "Gates: blocks & enables Optimize" + "Conversational Agents Excluded"):
 *   conversational_agent → authoring_model_not_configured/not_enabled →
 *   no_successful_execution.
 *
 * Journeys:
 *   1. Before any successful execution the Optimize action is disabled with the
 *      localized reason, while Run stays available — Run and Optimize are
 *      distinct actions.
 *   2. No usable workspace authoring model blocks Optimize (plan/optimize both
 *      need it) with actionable copy — no run can start.
 *   3. Conversational agents expose no Optimize action at all.
 *   4. A completed run satisfies the execution gate: Optimize becomes enabled
 *      without a manual page reload, and triggering it launches the DEDICATED
 *      optimization execution (`POST /agents/sessions/optimize`), never the
 *      Run dialog.
 *   5. Run is execution-only: the launch dialog carries no optimization
 *      affordance and `POST /agents/sessions` sends no `optimize` field.
 *   6. The UI gate state is not trusted alone: when the server re-checks and
 *      rejects with `412 optimize_gate_unmet`, the dialog surfaces the reason
 *      and stays open (nothing is launched) — including the structured
 *      `reason_code` payload that offers the System Config shortcut.
 */

test.describe.configure({ timeout: 120_000 })

const AGENT_ID = 'at-a'
const AGENT_NAME = 'panel-e2e-alpha'
const CONV_AGENT_NAME = 'panel-e2e-conv'

// Copy resolved from `frontend/src/i18n/locales/en.json` (the only locale) —
// the UI localizes the gate from `reason_code`, falling back to `reason`.
const NO_EXECUTION_COPY =
  'Optimization requires at least one successful execution of this agent. Run it successfully first so the optimizer has a real reference execution.'
const MODEL_NOT_CONFIGURED_COPY =
  'No authoring model is configured for this workspace. Select one in System Config before generating plans or optimizing.'
const MODEL_NOT_ENABLED_COPY =
  'The saved authoring model is no longer available in this workspace. Re-select an enabled model in System Config.'

const RUN_LABEL = 'Run Agent'

/** Which composed precondition the mocked backend reports. */
type GateMode = 'configured' | 'model_not_configured' | 'model_not_enabled' | 'conversational'

interface OptimizationState {
  /** Number of completed executions the mocked gate is computed from. */
  completedRuns: number
  /** Composed gate mode (precedence: conversational → model → executions). */
  mode: GateMode
  /** How many times the gate endpoint was read. */
  gateReads: number
  /** Bodies of POST /agents/sessions (normal runs). */
  runRequests: Record<string, unknown>[]
  /** Bodies of POST /agents/sessions/optimize. */
  optimizeRequests: Record<string, unknown>[]
  /** When set the optimize trigger answers 412 optimize_gate_unmet. */
  rejectOptimize: Record<string, unknown> | null
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function makeSession(id: string, status: string) {
  return {
    id,
    agent_type_id: AGENT_ID,
    triggered_by_user_id: 'e2e-admin',
    input_data: null,
    status,
    started_at: '2026-06-01T00:00:00Z',
    completed_at: status === 'completed' ? '2026-06-01T00:01:00Z' : null,
    output_data: null,
    error_message: null,
    conversation_history: null,
    created_at: '2026-06-01T00:00:00Z',
  }
}

/** Builds the composed `OptimizationGateRead` payload from the state. */
function gatePayload(state: OptimizationState) {
  const conversational = state.mode === 'conversational'
  const modelConfigured = state.mode === 'configured'
  const canGeneratePlan = modelConfigured && !conversational
  const canOptimize = canGeneratePlan && state.completedRuns > 0

  let reasonCode: string | null = null
  let reason: string | null = null
  if (conversational) {
    reasonCode = 'conversational_agent'
    reason = 'Conversational agents do not have plans and cannot be optimized.'
  } else if (state.mode === 'model_not_configured') {
    reasonCode = 'authoring_model_not_configured'
    reason = MODEL_NOT_CONFIGURED_COPY
  } else if (state.mode === 'model_not_enabled') {
    reasonCode = 'authoring_model_not_enabled'
    reason = MODEL_NOT_ENABLED_COPY
  } else if (state.completedRuns === 0) {
    reasonCode = 'no_successful_execution'
    reason = NO_EXECUTION_COPY
  }

  return {
    can_optimize: canOptimize,
    can_generate_plan: canGeneratePlan,
    successful_executions: state.completedRuns,
    // `workflow_model_id` echoes a stale value even when it is not usable, so
    // the UI can say "re-select" — it must not be read as "configured".
    workflow_model_configured: modelConfigured,
    workflow_model_id:
      state.mode === 'model_not_enabled'
        ? 'retired-model'
        : modelConfigured
          ? 'gpt-4o'
          : null,
    is_conversational: conversational,
    reason_code: reasonCode,
    reason,
  }
}

/**
 * Registers the optimization surfaces on top of the panel world.
 * MUST be called AFTER `mockPanelWorld` (routes resolve last-registered-first).
 */
async function mockOptimizationApi(page: Page, state: OptimizationState) {
  // ── Composed gate (conversational → authoring model → executions) ────────
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimization-gate$/, (route) => {
    state.gateReads += 1
    return json(route, 200, gatePayload(state))
  })

  // ── Dedicated optimization trigger ───────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/sessions\/optimize$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    state.optimizeRequests.push(route.request().postDataJSON())
    if (state.rejectOptimize) {
      return json(route, 412, { detail: state.rejectOptimize })
    }
    return json(route, 202, makeSession(`sess-opt-${state.optimizeRequests.length}`, 'queued'))
  })

  // ── Normal run launch (execution-only) ───────────────────────────────────
  await page.route(/\/api\/v1\/agents\/sessions(\?.*)?$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    state.runRequests.push(route.request().postDataJSON())
    // The mocked run completes immediately — this is what satisfies the gate.
    state.completedRuns += 1
    return json(route, 202, makeSession(`sess-run-${state.runRequests.length}`, 'completed'))
  })

  // ── Execution details dialog of the launched session ─────────────────────
  await page.route(/\/api\/v1\/agents\/sessions\/[^/]+\/logs$/, (route) => json(route, 200, []))
  await page.route(/\/api\/v1\/agents\/sessions\/[^/]+$/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return json(route, 200, makeSession('sess-run-1', 'completed'))
  })
}

/** Navigates to the panel and selects the seeded (typed) agent. */
async function gotoPanelWithAgent(page: Page, name = AGENT_NAME) {
  await page.goto('/agents/panel')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
  }
  await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()
  await page.getByRole('button', { name }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
}

function optimizeAction(page: Page) {
  return page.getByTestId('optimize-agent-action')
}

function runAction(page: Page) {
  return page.getByRole('button', { name: RUN_LABEL })
}

/** Pins a dialog by its heading so stale locators never resolve to another one. */
function dialogWithHeading(page: Page, name: string) {
  return page.getByRole('dialog').filter({ has: page.getByRole('heading', { name }) })
}

/**
 * Closes the execution-details dialog that opens after a launch. Its header
 * close control is an icon-only button, so the topmost modal is dismissed with
 * Escape (only the focused top modal handles it).
 */
async function dismissExecutionDetails(page: Page) {
  const detailsTitle = page.getByText('Execution Details')
  // The launched session's execution details open asynchronously on top.
  await expect(detailsTitle.first()).toBeVisible({ timeout: 15_000 })
  // It is the topmost modal — Escape closes only it.
  await page.keyboard.press('Escape')
  await expect(detailsTitle.first()).toBeHidden()
}

async function markNoReload(page: Page) {
  await page.evaluate(() => {
    ;(window as unknown as Record<string, unknown>).__e2e_no_reload = true
  })
}

async function assertNoReload(page: Page) {
  const marker = await page.evaluate(
    () => (window as unknown as Record<string, unknown>).__e2e_no_reload,
  )
  expect(marker).toBe(true)
}

/** Hovers a disabled action's wrapper span so its tooltip becomes reachable. */
async function hoverOptimizeTooltip(page: Page) {
  await page
    .locator('span')
    .filter({ has: optimizeAction(page) })
    .first()
    .hover({ force: true })
}

test.describe('Optimize gate — blocks then enables the separate Optimize action', () => {
  let state: OptimizationState

  test.beforeEach(async ({ page }) => {
    state = {
      completedRuns: 0,
      mode: 'configured',
      gateReads: 0,
      runRequests: [],
      optimizeRequests: [],
      rejectOptimize: null,
    }
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockPanelWorld(page, { agents: seedAgents() })
    await mockOptimizationApi(page, state)
  })

  test('no successful execution: Optimize is disabled with the localized reason, Run stays available', async ({
    page,
  }) => {
    await gotoPanelWithAgent(page)

    // Gate read for the selected agent type.
    await expect.poll(() => state.gateReads).toBeGreaterThan(0)

    // Optimize exists as its own action, but is disabled before any successful
    // execution. Run is a different action and stays enabled.
    await expect(optimizeAction(page)).toBeVisible()
    await expect(optimizeAction(page)).toBeDisabled()
    await expect(runAction(page).first()).toBeEnabled()

    // The explanation is the localized `no_successful_execution` copy (not a
    // generic string), reachable even though the button is disabled.
    await hoverOptimizeTooltip(page)
    await expect(page.getByRole('tooltip')).toContainText(NO_EXECUTION_COPY)

    // Clicking a gated action never opens the Optimize dialog.
    await optimizeAction(page).click({ force: true })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(state.optimizeRequests).toEqual([])
  })

  test('no authoring model: Optimize is disabled with the model reason and nothing can start', async ({
    page,
  }) => {
    state.mode = 'model_not_configured'
    await gotoPanelWithAgent(page)

    await expect(optimizeAction(page)).toBeVisible()
    await expect(optimizeAction(page)).toBeDisabled()
    // Run is unaffected — the gate is about authoring capability, not running.
    await expect(runAction(page).first()).toBeEnabled()

    await hoverOptimizeTooltip(page)
    await expect(page.getByRole('tooltip')).toContainText(MODEL_NOT_CONFIGURED_COPY)

    await optimizeAction(page).click({ force: true })
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(state.optimizeRequests).toEqual([])

    // The gate payload is explicit about the model state (the UI does not treat
    // a stale id as configured).
    expect(gatePayload(state).workflow_model_configured).toBe(false)
    expect(gatePayload(state).can_generate_plan).toBe(false)
  })

  test('a disabled/removed authoring model blocks Optimize with the re-select reason', async ({
    page,
  }) => {
    state.mode = 'model_not_enabled'
    state.completedRuns = 1
    await gotoPanelWithAgent(page)

    await expect(optimizeAction(page)).toBeDisabled()
    await hoverOptimizeTooltip(page)
    await expect(page.getByRole('tooltip')).toContainText(MODEL_NOT_ENABLED_COPY)

    // A completed run cannot compensate for a stale authoring model.
    const payload = gatePayload(state)
    expect(payload.workflow_model_configured).toBe(false)
    expect(payload.workflow_model_id).toBe('retired-model')
    expect(payload.can_optimize).toBe(false)
    expect(payload.reason_code).toBe('authoring_model_not_enabled')
  })

  test('conversational agent: no Optimize action at all (plans/optimization do not exist)', async ({
    page,
  }) => {
    state.mode = 'conversational'
    state.completedRuns = 1
    await gotoPanelWithAgent(page, CONV_AGENT_NAME)

    // The action self-hides for a conversational agent — even with a completed
    // execution and everything else in place.
    await expect(optimizeAction(page)).toHaveCount(0)
    // The conversational launch action is a chat, not a run: neither plan nor
    // optimization affordance appears.
    await expect(page.getByRole('button', { name: 'Start Chat' }).first()).toBeEnabled()

    // The backend agrees (compound gate precedence puts the agent type first).
    const payload = gatePayload(state)
    expect(payload.is_conversational).toBe(true)
    expect(payload.can_generate_plan).toBe(false)
    expect(payload.can_optimize).toBe(false)
    expect(payload.reason_code).toBe('conversational_agent')
  })

  test('a completed run satisfies the gate and Optimize becomes enabled without a reload', async ({
    page,
  }) => {
    await gotoPanelWithAgent(page)
    await markNoReload(page)
    await expect(optimizeAction(page)).toBeDisabled()

    // Run the agent (execution-only launch).
    await runAction(page).first().click()
    const launch = page.getByRole('dialog')
    await expect(launch.getByRole('heading', { name: `Launch Session — ${AGENT_NAME}` })).toBeVisible()
    // Run is execution-only: no "run with optimization" opt-in affordance and
    // no optimization sub-dialog. The dialog states which path the run takes.
    await expect(launch.getByText(/run with optimization/i)).toHaveCount(0)
    await expect(launch.getByText(/skip optimization/i)).toHaveCount(0)
    await expect(launch.getByTestId('run-execution-only-hint')).toBeVisible()
    await launch.getByRole('button', { name: 'Launch', exact: true }).click()

    // The run completed — the gate re-reads (the launch invalidates the
    // agent-type scope, which includes the gate query), and Optimize becomes
    // available with no manual page reload.
    await expect(optimizeAction(page)).toBeEnabled({ timeout: 45_000 })
    await assertNoReload(page)

    // Run really was execution-only: no `optimize` field in the payload.
    expect(state.runRequests).toHaveLength(1)
    expect(state.runRequests[0]).toMatchObject({ agent_type_id: AGENT_ID })
    expect(state.runRequests[0]).not.toHaveProperty('optimize')

    // The still-open execution details dialog is closed; Optimize then starts
    // its dedicated run directly — there is no pre-run confirmation dialog
    // (the explanation lives in the Optimized Plan tab help + the chat).
    await dismissExecutionDetails(page)
    await optimizeAction(page).click()

    // A distinct optimization execution was launched for this agent type.
    await expect.poll(() => state.optimizeRequests.length).toBe(1)
    expect(state.optimizeRequests[0]).toEqual({ agent_type_id: AGENT_ID })
    // No "Optimize Agent — …" confirmation dialog was ever opened.
    await expect(dialogWithHeading(page, `Optimize Agent — ${AGENT_NAME}`)).toHaveCount(0)
    await expect(page.getByTestId('optimize-start-error')).toHaveCount(0)
    // The launched optimization session's execution details open on top.
    await dismissExecutionDetails(page)
  })

  test('server re-checks the gate: 412 with reason_code shows the reason in a snackbar', async ({
    page,
  }) => {
    // Gate open in the UI…
    state.completedRuns = 1
    await gotoPanelWithAgent(page)
    await expect(optimizeAction(page)).toBeEnabled()

    // …but the server rejects the trigger (e.g. the authoring model was removed
    // between the gate read and the click). The UI snapshot is never trusted.
    state.rejectOptimize = {
      error: 'optimize_gate_unmet',
      reason_code: 'authoring_model_not_configured',
      reason: 'No authoring model is configured for this workspace.',
    }

    await optimizeAction(page).click()

    // The failure is surfaced as a lightweight warning snackbar, localized from
    // the structured reason_code (not a generic message).
    const unmet = page.getByTestId('optimize-start-error')
    await expect(unmet).toBeVisible()
    await expect(unmet).toContainText(MODEL_NOT_CONFIGURED_COPY)
    // Nothing was launched and no confirmation dialog exists in this flow.
    expect(state.optimizeRequests).toHaveLength(1)
    await expect(dialogWithHeading(page, `Optimize Agent — ${AGENT_NAME}`)).toHaveCount(0)
  })

  test('server re-checks the gate: legacy reason-only 412 surfaces the backend reason', async ({
    page,
  }) => {
    state.completedRuns = 1
    await gotoPanelWithAgent(page)
    await expect(optimizeAction(page)).toBeEnabled()

    // Older payload shape: only `reason` (no `reason_code`).
    const legacyReason =
      'This agent type has no successful execution yet. Run the agent successfully once, then optimize.'
    state.rejectOptimize = { error: 'optimize_gate_unmet', reason: legacyReason }

    await optimizeAction(page).click()

    const unmet = page.getByTestId('optimize-start-error')
    await expect(unmet).toBeVisible()
    await expect(unmet).toContainText(legacyReason)
    expect(state.optimizeRequests).toHaveLength(1)
    await expect(dialogWithHeading(page, `Optimize Agent — ${AGENT_NAME}`)).toHaveCount(0)
  })
})
