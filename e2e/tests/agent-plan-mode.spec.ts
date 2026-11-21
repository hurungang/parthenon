import { expect, test, type Page, type Route } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'
import {
  mockPanelWorld,
  seedAgents,
  selectMuiOption,
  type PanelWorldState,
} from './_agent_panel_world'

/**
 * E2E: implementation-plan authoring is EXPLICIT-ONLY.
 *
 * Fully mocked (mock-first convention, `page.route()`): no live backend.
 *
 * Journeys (docs/changes/separate-optimization-from-execution/test-plan.md —
 * "Explicit-only plan generation" + "Generate-plan gate" + "Explicit
 * Generate-plan UX"):
 *   1. Creating / saving an agent type produces no plan and fires no
 *      plan-generation request; the Implementation Plan tab of the details
 *      dialog shows the explicit empty state instead.
 *   2. Generation happens only on the explicit **Generate plan** action, and
 *      the authored plan renders in place without a page reload.
 *   3. With no usable workspace authoring model, the Implementation Plan tab
 *      shows the blocked state with the localized reason and a System Config
 *      shortcut, and the Generate plan action is disabled — nothing is
 *      dispatched.
 *   4. Conversational agents expose no plan-generation affordances at all; the
 *      tab explains why.
 *   5. A blocked explicit generation (`412 plan_generation_unavailable`) shows
 *      its reason while the last good plan stays visible.
 *
 * The "Real Backend Integration" suite below is unchanged in intent and skips
 * cleanly unless a live backend + token are available; it asserts the live
 * create response carries no plan (explicit-only on the server).
 */

test.describe.configure({ timeout: 120_000 })

const AGENT_ID = 'at-a'
const AGENT_NAME = 'panel-e2e-alpha'
const CONV_ID = 'at-c'
const CONV_NAME = 'panel-e2e-conv'

const PLAN_SUCCESS = {
  id: 'plan-e2e-1',
  agent_type_id: AGENT_ID,
  plan_steps: [
    { order: 1, type: 'sop_invocation', name: 'Initialize Context', description: 'Gather required context' },
    { order: 2, type: 'skill_invocation', name: 'Execute Search', description: 'Run the search skill' },
    { order: 3, type: 'tool_call', name: 'Save Result', description: 'Persist the result' },
  ],
  topology_nodes: [
    { id: 'role:r1', type: 'role', label: 'Research Role', meta: null },
    { id: 'skill:s1', type: 'skill', label: 'Search Skill', meta: null },
  ],
  topology_edges: [{ source: 'role:r1', target: 'skill:s1', label: 'uses skill' }],
  generation_status: 'success',
  generation_error: null,
  agent_config_hash: 'abc123def',
  generated_at: '2026-05-09T12:00:00Z',
}

// Copy resolved from `frontend/src/i18n/locales/en.json` (the only locale).
const EMPTY_TITLE = 'No implementation plan yet'
const EMPTY_HINT =
  'This agent has no plan. Generating one is an explicit action — creating or saving an agent never produces a plan.'
const BLOCKED_TITLE = 'Plan generation unavailable'
const MODEL_NOT_CONFIGURED_COPY =
  'No authoring model is configured for this workspace. Select one in System Config before generating plans or optimizing.'
const MODEL_NOT_ENABLED_COPY =
  'The saved authoring model is no longer available in this workspace. Re-select an enabled model in System Config.'
const CONVERSATIONAL_COPY = 'Implementation plans are not available for conversational agents.'
const GENERATION_FAILED_TITLE = 'The last plan generation attempt failed'
const GENERATION_FAILED_KEPT = 'The last successful plan is still shown below.'

interface PlanState {
  /** Gate payload the Plan Preview reads (see useOptimizationGate). */
  canGeneratePlan: boolean
  reasonCode: string | null
  conversational?: boolean
  /** Bodies of POST /agents/types/{id}/regenerate-plan. */
  regenerateRequests: unknown[]
}

function json(route: Route, status: number, body: unknown) {
  return route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/**
 * Registers the plan surfaces on top of the panel world.
 * MUST be called AFTER `mockPanelWorld` (routes resolve last-registered-first).
 */
async function mockPlanApi(
  page: Page,
  world: PanelWorldState,
  state: PlanState,
  opts: { generationFailure?: Record<string, unknown> } = {},
) {
  // ── Composed plan/optimize gate (can_generate_plan gates the action) ─────
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/optimization-gate$/, (route) => {
    const conversational = state.conversational === true
    const canGenerate = state.canGeneratePlan && !conversational
    return json(route, 200, {
      // A successful execution is not required for base-plan generation.
      can_optimize: false,
      can_generate_plan: canGenerate,
      successful_executions: 0,
      workflow_model_configured: state.canGeneratePlan,
      workflow_model_id: state.canGeneratePlan ? 'gpt-4o' : null,
      is_conversational: conversational,
      reason_code: state.reasonCode,
      reason: state.reasonCode === 'authoring_model_not_configured' ? MODEL_NOT_CONFIGURED_COPY : null,
    })
  })

  // ── Explicit generation (the ONLY authoring path) ────────────────────────
  await page.route(/\/api\/v1\/agents\/types\/[^/]+\/regenerate-plan$/, (route) => {
    if (route.request().method() !== 'POST') return route.fallback()
    const id = route.request().url().split('/agents/types/')[1]?.split('/')[0]
    state.regenerateRequests.push({ agentTypeId: id })
    if (opts.generationFailure) {
      return json(route, 412, { detail: opts.generationFailure })
    }
    const agent = world.agents.find((a) => a.id === id)
    if (agent) {
      // The server persists the authored plan; the UI then refetches it.
      ;(agent as Record<string, unknown>).plan = PLAN_SUCCESS
      return json(route, 200, agent)
    }
    return json(route, 404, { detail: 'not found' })
  })
}

const GATE_OK: PlanState = { canGeneratePlan: true, reasonCode: null, regenerateRequests: [] }

/**
 * Locates the agent-type details dialog. Its accessible name is the agent type
 * name (the DialogTitle renders it), so it is identified by its tab set.
 */
function agentDetailsDialog(page: Page) {
  return page
    .getByRole('dialog')
    .filter({ has: page.getByRole('tab', { name: 'Implementation Plan' }) })
}

async function openAgentDialog(page: Page, name: string) {
  await page.getByText(name, { exact: true }).first().click()
  const dialog = agentDetailsDialog(page)
  await expect(dialog.getByRole('tab', { name: 'Implementation Plan' })).toBeVisible()
  return dialog
}

/**
 * Opens the plan surface: the plan lives on its own "Implementation Plan" tab
 * (there is no separate plan-preview modal or "Agent Preview" tab).
 */
async function openPlanTab(dialog: ReturnType<Page['getByRole']>) {
  await dialog.getByRole('tab', { name: 'Implementation Plan' }).click()
}

async function gotoAgentsList(page: Page) {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  return true
}

async function gotoPanel(page: Page) {
  await page.goto('/agents/panel')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) {
    test.skip()
    return false
  }
  await expect(page.getByRole('heading', { name: 'Agent Management Panel' })).toBeVisible()
  return true
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

/** Asserts the panel/agent API never received a plan-generation request. */
function assertNoGenerationRequests(world: PanelWorldState, state: PlanState) {
  expect(state.regenerateRequests).toEqual([])
  expect(world.requests.filter((r) => r.includes('regenerate-plan'))).toEqual([])
}

// ═══════════════════════════════════════════════════════════════════════════════
// Suite 1: Mocked E2E tests (fast, use page.route())
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Agent Plan Mode — explicit-only generation (mocked)', () => {
  let world: PanelWorldState
  let state: PlanState

  test.beforeEach(async ({ page }) => {
    state = { ...GATE_OK, regenerateRequests: [] }
    // Lowest-priority catch-all FIRST (handlers resolve last-registered-first).
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    world = await mockPanelWorld(page, { agents: seedAgents() })
    await mockPlanApi(page, world, state)
  })

  test('saving an agent type generates nothing — Plan Preview stays in the explicit empty state', async ({
    page,
  }) => {
    if (!(await gotoPanel(page))) return

    await markNoReload(page)

    // Select the seeded agent and edit it in place (the panel's property bar
    // owns editing; the pending-changes tray owns saving).
    await page.getByRole('button', { name: AGENT_NAME }).click()
    await expect(page.getByRole('heading', { name: AGENT_NAME, exact: true })).toBeVisible()
    const descInput = page.getByLabel('Description')
    await expect(descInput).toHaveValue('E2E panel agent')
    await descInput.fill(`saved by e2e ${Date.now()}`)
    await page.getByRole('button', { name: 'Save Changes' }).click()

    // The save persisted exactly once…
    await expect(page.getByText('saved', { exact: true })).toBeVisible()
    await expect.poll(() => world.agentPutBodies.length).toBe(1)
    // …and no plan generation was scheduled by create/update.
    assertNoGenerationRequests(world, state)

    // Plan Preview shows the explicit empty state — no plan was authored.
    await page.getByLabel('View').click()
    const dialog = agentDetailsDialog(page)
    await openPlanTab(dialog)
    const empty = dialog.getByTestId('plan-empty-state')
    await expect(empty).toBeVisible()
    await expect(empty.getByText(EMPTY_TITLE)).toBeVisible()
    await expect(empty.getByText(EMPTY_HINT)).toBeVisible()
    await expect(dialog.getByTestId('plan-generate')).toBeEnabled()
    // No plan content leaked in from the save.
    await expect(dialog.getByText('Initialize Context')).toHaveCount(0)

    await assertNoReload(page)
  })

  test('creating an agent type generates nothing — the new agent has no plan', async ({ page }) => {
    if (!(await gotoPanel(page))) return

    const name = `e2e-plan-create-${Date.now()}`
    await page.getByRole('button', { name: 'Create Agent' }).click()
    const createDialog = page.getByRole('dialog')
    await expect(createDialog.getByRole('heading', { name: 'Create Agent Type' })).toBeVisible()
    await createDialog.getByLabel('Name').fill(name)
    await selectMuiOption(page, createDialog, 'Agent Role', 'panel-e2e-role')
    await createDialog.getByRole('button', { name: 'Add Binding' }).click()
    await createDialog
      .locator('.MuiToggleButtonGroup-root')
      .locator('..')
      .getByRole('combobox')
      .click()
    await page.getByRole('option', { name: 'panel-e2e-sop' }).click()
    await createDialog.getByRole('button', { name: 'Add', exact: true }).click()
    await createDialog.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(createDialog).toBeHidden()

    // Created exactly once, and no plan authoring was requested by create.
    expect(world.agentPostBodies).toHaveLength(1)
    assertNoGenerationRequests(world, state)
    const created = world.agents.find((a) => a.name === name)
    expect(created).toBeTruthy()
    expect(created?.plan).toBeNull()

    // The created agent's Plan Preview opens on the empty state.
    await page.getByLabel('View').click()
    const dialog = agentDetailsDialog(page)
    await openPlanTab(dialog)
    await expect(dialog.getByTestId('plan-empty-state')).toBeVisible()
    await expect(dialog.getByTestId('plan-generate')).toBeVisible()
  })

  test('explicit Generate plan authors the plan and it renders without a page reload', async ({
    page,
  }) => {
    if (!(await gotoAgentsList(page))) return

    const dialog = await openAgentDialog(page, AGENT_NAME)
    await markNoReload(page)
    await openPlanTab(dialog)

    const generate = dialog.getByTestId('plan-generate')
    await expect(generate).toBeVisible()
    await expect(generate).toHaveText('Generate plan')
    // Explicit-only: nothing has been generated just by opening the surface.
    await expect(dialog.getByTestId('plan-empty-state')).toBeVisible()
    expect(state.regenerateRequests).toEqual([])

    await generate.click()

    // Exactly one explicit authoring request.
    await expect.poll(() => state.regenerateRequests.length).toBe(1)
    expect(state.regenerateRequests[0]).toEqual({ agentTypeId: AGENT_ID })

    // The refreshed agent type renders the authored plan in place (dependent
    // queries invalidated — no manual page reload).
    await expect(dialog.getByText('Initialize Context')).toBeVisible({ timeout: 15_000 })
    await expect(dialog.getByText('Execute Search')).toBeVisible()
    await expect(dialog.getByText('Save Result')).toBeVisible()
    await expect(dialog.getByTestId('plan-empty-state')).toHaveCount(0)
    // With a plan present the explicit action becomes "Regenerate plan".
    await expect(dialog.getByTestId('plan-regenerate')).toHaveText('Regenerate plan')

    await assertNoReload(page)
  })

  test('no authoring model: Plan Preview is blocked with the reason + System Config shortcut, nothing is dispatched', async ({
    page,
  }) => {
    state.canGeneratePlan = false
    state.reasonCode = 'authoring_model_not_configured'
    await mockPlanApi(page, world, state)
    if (!(await gotoAgentsList(page))) return

    const dialog = await openAgentDialog(page, AGENT_NAME)
    await openPlanTab(dialog)

    const blocked = dialog.getByTestId('plan-generation-blocked')
    await expect(blocked).toBeVisible()
    await expect(blocked.getByText(BLOCKED_TITLE)).toBeVisible()
    // The reason is the localized authoring-model message, not a generic one.
    await expect(blocked.getByText(MODEL_NOT_CONFIGURED_COPY)).toBeVisible()

    // The explicit action is disabled and never dispatches a request.
    const generate = dialog.getByTestId('plan-generate')
    await expect(generate).toBeDisabled()
    await generate.click({ force: true })
    await expect(dialog.getByTestId('plan-empty-state')).toBeVisible()
    expect(state.regenerateRequests).toEqual([])
    assertNoGenerationRequests(world, state)

    // The shortcut points the operator at the fix.
    await dialog.getByTestId('plan-system-config-shortcut').click()
    await expect(page).toHaveURL(/\/system-config$/)
    await expect(page.getByTestId('authoring-model-section')).toBeVisible()
  })

  test('conversational agent: no plan-generation affordances, only the explanation', async ({
    page,
  }) => {
    state.conversational = true
    state.reasonCode = 'conversational_agent'
    await mockPlanApi(page, world, state)
    if (!(await gotoAgentsList(page))) return

    // The row exposes no Optimize action for a conversational agent (the typed
    // rows do have one, so this is scoped to the conversational row).
    await expect(page.getByText(CONV_NAME, { exact: true }).first()).toBeVisible()
    const convRow = page.getByRole('row').filter({ hasText: CONV_NAME })
    await expect(convRow.getByTestId('optimize-agent-action')).toHaveCount(0)

    const dialog = await openAgentDialog(page, CONV_NAME)
    await openPlanTab(dialog)

    await expect(dialog.getByTestId('plan-conversational-unavailable')).toHaveText(
      CONVERSATIONAL_COPY,
    )
    // No generate / regenerate / empty-state affordance at all.
    await expect(dialog.getByTestId('plan-generate')).toHaveCount(0)
    await expect(dialog.getByTestId('plan-regenerate')).toHaveCount(0)
    await expect(dialog.getByTestId('plan-empty-state')).toHaveCount(0)
    await expect(dialog.getByTestId('plan-generation-blocked')).toHaveCount(0)
    expect(state.regenerateRequests).toEqual([])
  })

  test('a blocked explicit generation shows its reason and keeps the last successful plan', async ({
    page,
  }) => {
    // An agent that already has a good plan; the authoring model went missing
    // between the gate read and the request (server re-checks → 412).
    ;(world.agents[0] as Record<string, unknown>).plan = PLAN_SUCCESS
    await mockPlanApi(page, world, state, {
      generationFailure: {
        error: 'plan_generation_unavailable',
        reason_code: 'authoring_model_not_enabled',
        reason: 'The saved authoring model is no longer available in this workspace.',
      },
    })
    if (!(await gotoAgentsList(page))) return

    const dialog = await openAgentDialog(page, AGENT_NAME)
    await openPlanTab(dialog)
    await expect(dialog.getByText('Initialize Context')).toBeVisible()

    await dialog.getByTestId('plan-regenerate').click()
    await expect.poll(() => state.regenerateRequests.length).toBe(1)

    const failed = dialog.getByTestId('plan-generation-failed')
    await expect(failed).toBeVisible()
    await expect(failed.getByText(GENERATION_FAILED_TITLE)).toBeVisible()
    await expect(failed.getByText(MODEL_NOT_ENABLED_COPY)).toBeVisible()
    await expect(failed.getByText(GENERATION_FAILED_KEPT)).toBeVisible()
    // The authoring-model failure offers the System Config path.
    await expect(dialog.getByTestId('plan-generation-failed-system-config')).toBeVisible()
    // The previous plan is never discarded by a failed attempt.
    await expect(dialog.getByText('Initialize Context')).toBeVisible()
    await expect(dialog.getByText('Execute Search')).toBeVisible()
  })
})

// ═══════════════════════════════════════════════════════════════════════════════
// Suite 2: Real Backend Integration — Agent Plan Mode
// Tests against the actual running backend WITHOUT page.route() mocks.
// Catches migration issues that mocked tests miss.
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Real Backend Integration — Agent Plan Mode', () => {
  // These tests require the backend and frontend to be running.
  // They are tagged as slow and may be skipped if the backend is not available.

  test('POST /api/v1/agents/types never authors a plan (explicit-only on the server)', async ({
    request,
  }) => {
    const BACKEND_URL = process.env.API_BASE_URL ?? 'http://localhost:8000'

    // Check if backend is reachable first
    let healthOk = false
    try {
      const health = await request.get(`${BACKEND_URL}/api/v1/health`)
      healthOk = health.status() === 200
    } catch {
      // Backend not running — skip gracefully
      test.skip(true, 'Backend not available — skipping real backend integration test')
      return
    }

    if (!healthOk) {
      test.skip(true, 'Backend health check failed — skipping real backend integration test')
      return
    }

    // Get an auth token (requires a running Keycloak / identity provider)
    // For CI environments, use the AGENT_TEST_TOKEN environment variable
    const token = process.env.AGENT_TEST_TOKEN
    if (!token) {
      test.skip(true, 'AGENT_TEST_TOKEN env var not set — skipping authenticated real backend test')
      return
    }

    const agentTypeName = `e2e-plan-test-${Date.now()}`
    let createdId: string | null = null

    try {
      // Create an agent type via the real API
      const createResp = await request.post(`${BACKEND_URL}/api/v1/agents/types`, {
        data: {
          name: agentTypeName,
          input_type: 'typed',
          output_type: 'markdown',
          is_active: true,
        },
        headers: { Authorization: `Bearer ${token}` },
      })

      // Must be 201 — plan generation is explicit, so it cannot block creation
      expect(createResp.status()).toBe(201)
      const body = await createResp.json()

      // Response must include `plan` key, and a brand-new agent has no plan:
      // save/create must never author one (explicit-only contract).
      expect(body).toHaveProperty('plan')
      expect(body.plan).toBeNull()
      createdId = body.id as string
    } finally {
      // Cleanup: delete the created agent type to verify CASCADE
      if (createdId) {
        const deleteResp = await request.delete(
          `${BACKEND_URL}/api/v1/agents/types/${createdId}`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
        // 204 means successful deletion — plan should cascade automatically
        expect([200, 204]).toContain(deleteResp.status())
      }
    }
  })
})
