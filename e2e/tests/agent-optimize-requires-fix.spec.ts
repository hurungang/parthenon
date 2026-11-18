import { expect, test, type Page, type Route } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import { mockPanelWorld, seedAgents } from './_agent_panel_world'

/**
 * E2E: the self-healing journey of a separate optimization run.
 *
 * Fully mocked (mock-first convention, `page.route()`): no live backend.
 *
 * Journey (docs/changes/separate-optimization-from-execution/test-plan.md):
 *   optimize (dedicated run) → `ready` optimized plan → a later execution
 *   falls back because of that plan (server-side: plan becomes `requires_fix`
 *   + auto-recorded execution-derived feedback) → the operator sees the
 *   requires-fix alert with the auto-recorded feedback when they next open the
 *   agent → Re-optimize from the alert (the new run carries the prior plan +
 *   recorded feedback) → the Optimized Plan tab refreshes automatically to the
 *   new plan without a manual page reload.
 *
 * No-optimize-for-a-ready-plan and the manual vs auto-recorded feedback badges
 * are asserted along the way.
 */

test.describe.configure({ timeout: 120_000 })

const AGENT_ID = 'at-a'
const AGENT_NAME = 'panel-e2e-alpha'

const AUTO_FEEDBACK_SUMMARY =
  'Execution sess-run-7 fell back: tool "ops____query" result missing expected key "id".'

const READY_PLAN = {
  id: 'oplan-1',
  agent_type_id: AGENT_ID,
  agent_plan_id: 'plan-at-a',
  status: 'ready',
  fully_scripted: false,
  error: null,
  steps: [
    {
      order: 1,
      type: 'tool_call',
      name: 'Query pipeline',
      description: 'Fetch the pipeline snapshot',
      python_source: null,
      scriptable: true,
    },
  ],
  steps_count: 1,
  scripts_authored: 1,
  feedback_comments: [] as Record<string, unknown>[],
  generated_at: '2026-06-01T00:00:00Z',
}

const REQUIRES_FIX_PLAN = {
  ...READY_PLAN,
  status: 'requires_fix',
  feedback_comments: [
    {
      created_at: '2026-06-02T00:00:00Z',
      raw_feedback: AUTO_FEEDBACK_SUMMARY,
      summary: AUTO_FEEDBACK_SUMMARY,
      source: 'execution_derived',
      source_execution_id: 'sess-run-7',
      source_fallback_event_id: 'fb-7',
    },
    {
      created_at: '2026-06-02T01:00:00Z',
      raw_feedback: 'Keep amounts in EUR.',
      summary: 'Keep amounts in EUR.',
      source: 'manual',
      source_execution_id: null,
      source_fallback_event_id: null,
    },
  ],
}

const READY_PLAN_AFTER_REOPTIMIZE = {
  ...READY_PLAN,
  id: 'oplan-2',
  steps: [
    {
      order: 1,
      type: 'tool_call',
      name: 'Query pipeline (fixed)',
      description: 'Fetch the pipeline snapshot, tolerating a missing id key',
      python_source: null,
      scriptable: true,
    },
  ],
  // Re-optimization carries the accumulated feedback (auto + manual).
  feedback_comments: REQUIRES_FIX_PLAN.feedback_comments,
  generated_at: '2026-06-03T00:00:00Z',
}

interface JourneyState {
  /** Current server-side optimized plan (null ⇒ 404, no plan yet). */
  plan: Record<string, unknown> | null
  /** How many times the optimized-plan endpoint was read. */
  planReads: number
  /** Bodies of POST /agents/sessions/optimize. */
  optimizeRequests: Record<string, unknown>[]
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

function jsonText(route: Route, status: number, body: string) {
  return route.fulfill({ status, contentType: 'application/json', body })
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

/**
 * Registers the optimization surfaces on top of the panel world.
 * MUST be called AFTER `mockPanelWorld` (routes resolve last-registered-first).
 */
async function mockOptimizationApi(page: Page, state: JourneyState) {
  // The agent already completed a run — Optimize is available.
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimization-gate$/, (route) =>
    json(route, 200, { can_optimize: true, successful_executions: 1, reason: null }),
  )

  // ── Optimized plan (current server-side state) ───────────────────────────
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimized-plan(\?.*)?$/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    state.planReads += 1
    if (!state.plan) {
      return jsonText(route, 404, JSON.stringify({ detail: 'No optimized plan for this agent type' }))
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

  // ── Dedicated optimization trigger ───────────────────────────────────────
  await page.route(/\/api\/v1\/agents\/sessions\/optimize$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    state.optimizeRequests.push(route.request().postDataJSON())
    const attempt = state.optimizeRequests.length
    // The first optimization authors a ready plan; the re-optimization (from
    // the requires-fix alert) authors a fresh ready plan informed by the
    // previous plan + recorded feedback.
    state.plan = attempt === 1 ? { ...READY_PLAN } : { ...READY_PLAN_AFTER_REOPTIMIZE }
    return json(route, 202, makeSession(`sess-opt-${attempt}`, 'queued'))
  })

  // ── Execution details dialog of the launched optimization session ────────
  await page.route(/\/api\/v1\/agents\/sessions\/[^/]+\/logs$/, (route) => json(route, 200, []))
  await page.route(/\/api\/v1\/agents\/sessions\/[^/]+$/, (route) => {
    if (route.request().method() !== 'GET') return route.fallback()
    return json(route, 200, makeSession('sess-opt-1', 'completed'))
  })
}

async function gotoAgentsList(page: Page) {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
  }
  await expect(page.getByText(AGENT_NAME, { exact: true }).first()).toBeVisible()
}

/** Opens the agent-type detail dialog (no navigation — a UI click). */
async function openAgentDialog(page: Page) {
  await page.getByText(AGENT_NAME, { exact: true }).first().click()
  // Pin the dialog by its tab strip: the execution-details dialog opened after
  // an optimize trigger has no such tab, so this never resolves to both.
  const dialog = page
    .getByRole('dialog')
    .filter({ has: page.getByRole('tab', { name: 'Optimized Plan' }) })
  await expect(dialog.getByRole('tab', { name: 'Optimized Plan' })).toBeVisible()
  return dialog
}

/** Pins a modal by its heading (never resolves to another open dialog). */
function dialogWithHeading(page: Page, name: string) {
  return page.getByRole('dialog').filter({ has: page.getByRole('heading', { name }) })
}

async function openOptimizedPlanTab(dialog: ReturnType<Page['getByRole']>) {
  await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
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

/** Closes the execution-details dialog that opens after an optimize trigger. */
async function dismissExecutionDetails(page: Page) {
  const detailsTitle = page.getByText('Execution Details')
  // The launched session's execution details open asynchronously on top.
  await expect(detailsTitle.first()).toBeVisible({ timeout: 15_000 })
  // It is the topmost modal — Escape closes only it.
  await page.keyboard.press('Escape')
  await expect(detailsTitle.first()).toBeHidden()
}

test.describe('Optimized plan — requires-fix alert and re-optimization journey', () => {
  let state: JourneyState

  test.beforeEach(async ({ page }) => {
    state = { plan: null, planReads: 0, optimizeRequests: [] }
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockPanelWorld(page, { agents: seedAgents() })
    await mockOptimizationApi(page, state)
  })

  test('optimize → ready plan → fallback marks requires_fix → re-optimize from the alert refreshes the tab', async ({
    page,
  }) => {
    await gotoAgentsList(page)
    await markNoReload(page)
    let dialog = await openAgentDialog(page)
    await openOptimizedPlanTab(dialog)
    // No optimized plan exists yet — and the empty state is explicit about the
    // fact that a normal run never produces one.
    await expect(dialog.getByTestId('optimized-plan-absent')).toBeVisible()
    await expect(dialog.getByText(/never produced by a normal run/)).toBeVisible()

    // ── 1. Optimize: a dedicated run, separate from Run ────────────────────
    const optimizeAction = dialog.getByTestId('optimize-agent-action')
    await expect(optimizeAction).toBeEnabled()
    await optimizeAction.click()

    const optimizeDialog = dialogWithHeading(page, `Optimize Agent — ${AGENT_NAME}`)
    await expect(optimizeDialog).toBeVisible()
    await expect(optimizeDialog.getByText(/Optimization is a dedicated run/)).toBeVisible()
    await expect(optimizeDialog.getByText(/never turns a normal run into an optimization mission/)).toBeVisible()
    await optimizeDialog.getByTestId('optimize-confirm').click()

    expect(state.optimizeRequests).toHaveLength(1)
    expect(state.optimizeRequests[0]).toEqual({ agent_type_id: AGENT_ID })

    // The launched optimization session's execution details open on top.
    await dismissExecutionDetails(page)

    // ── 2. The authored plan is `ready` — no alert, no re-optimize offered ─
    await openOptimizedPlanTab(dialog)
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('ready')
    await expect(dialog.getByText('Query pipeline')).toBeVisible()
    await expect(dialog.getByTestId('requires-fix-alert')).toHaveCount(0)
    await expect(dialog.getByTestId('reoptimize-from-alert')).toHaveCount(0)
    await expect(dialog.getByTestId('retire-optimized-plan')).toBeVisible()

    // ── 3. A later execution falls back because of the plan ────────────────
    // Server-side reaction (record_fallback → requires_fix + execution-derived
    // feedback). The operator comes back to the agent: the dialogs are closed
    // (which invalidates the agent-type scope) and the agent is reopened, so
    // the plan is re-read — no page reload.
    const planReadsBefore = state.planReads
    state.plan = { ...REQUIRES_FIX_PLAN }
    await dialog.getByRole('button', { name: 'Close' }).first().click()
    await expect(page.getByRole('dialog')).toHaveCount(0)

    dialog = await openAgentDialog(page)
    await openOptimizedPlanTab(dialog)
    // The tab re-read the plan after the failed execution was recorded.
    await expect.poll(() => state.planReads).toBeGreaterThan(planReadsBefore)

    // ── 4. The requires-fix alert + auto-recorded feedback render ──────────
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('requires_fix')
    const alert = dialog.getByTestId('requires-fix-alert')
    await expect(alert).toBeVisible()
    await expect(alert.getByText('This optimized plan requires a fix')).toBeVisible()
    await expect(
      alert.getByText(/A later run fell back to the model-driven path because this optimized plan failed/),
    ).toBeVisible()
    await expect(
      alert.getByText('Auto-recorded feedback from the failed execution'),
    ).toBeVisible()
    // The failure reason recorded from the failed execution is shown.
    await expect(dialog.getByTestId('requires-fix-feedback-0')).toHaveText(AUTO_FEEDBACK_SUMMARY)
    // Feedback entries are badged by their source.
    await expect(dialog.getByTestId('feedback-source-0')).toHaveText('auto-recorded')
    await expect(dialog.getByTestId('feedback-source-1')).toHaveText('manual')

    // ── 5. Re-optimize from the alert carries prior plan + feedback ────────
    await expect(alert.getByTestId('reoptimize-from-alert')).toBeVisible()
    await alert.getByTestId('reoptimize-from-alert').click()

    const reoptimizeDialog = dialogWithHeading(page, `Re-optimize Agent — ${AGENT_NAME}`)
    await expect(reoptimizeDialog).toBeVisible()
    await expect(
      reoptimizeDialog.getByText(
        /this run carries the previous plan plus the feedback recorded from the failed execution/,
      ),
    ).toBeVisible()

    await reoptimizeDialog.getByTestId('optimize-confirm').click()

    // ── 6. The tab refreshes automatically to the new plan (no reload) ─────
    expect(state.optimizeRequests).toHaveLength(2)
    expect(state.optimizeRequests[1]).toEqual({ agent_type_id: AGENT_ID })
    await expect(reoptimizeDialog).toBeHidden()
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('ready', {
      timeout: 15_000,
    })
    await expect(dialog.getByText('Query pipeline (fixed)')).toBeVisible()
    await expect(dialog.getByTestId('requires-fix-alert')).toHaveCount(0)
    await expect(dialog.getByTestId('reoptimize-from-alert')).toHaveCount(0)
    // The regenerated plan carries the accumulated feedback (the auto-recorded
    // entry from the failed execution plus the manual one) into its context.
    await expect(dialog.getByTestId('feedback-source-0')).toHaveText('auto-recorded')
    await expect(dialog.getByTestId('feedback-source-1')).toHaveText('manual')

    // No manual page reload happened anywhere in the journey.
    await assertNoReload(page)
  })
})
