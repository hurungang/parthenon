/**
 * E2E: Software 3.0 agent-owned scripts — the CURRENT governance surface.
 *
 * The standalone `/admin/scripts` registry and the Agent Type dialog's "Scripts"
 * tab were both REMOVED. Scripts are agent-owned artefacts reached from the
 * agent type's PLAN surfaces:
 *
 *   Implementation Plan tab → a script-backed step exposes a "Script" link that
 *   switches to the Optimized Plan tab (E4a), where each Python/scriptable step
 *   opens the read-only `ScriptViewDialog` (source + description) and the plan
 *   lifecycle (status, retire, requires-fix) is governed.
 *
 * Journeys covered (mapping to the retired Scripts-tab journeys, kept so the
 * demo-case coverage is traceable):
 *   1. No Scripts tab exists; plan surfaces are the only script views
 *      (replaces the old "Scripts tab lists scripts" journey, A1/G1)
 *   2. Implementation Plan: script link on the script-backed step only, and it
 *      lands on the Optimized Plan tab (E4a)
 *   3. Script viewer shows the model-authored source + description (A1)
 *   4. Version lineage / verification evidence / fallback + repair lists are
 *      gone from the dialog and no `/scripts` registry API is called — the
 *      retired promote action no longer exists (A2, V2, F2, F3, E10)
 *   5. Optimized plan lifecycle: a ready plan retires into `retired`
 *      (replaces the per-version retire journey)
 *   6. Permission-gated retire surfaces via the dialog error pattern
 *      (replaces the permission-gated promote journey)
 *   7. requires-fix alerting on the Optimized Plan tab (auto-feedback dump
 *      retired by product decision)
 *   8. No standalone /admin/scripts route or nav entry (A3/N8)
 */
import { test, expect, type Page, type Route } from '@playwright/test'
import { standardSetup, mockApiCatchAllProxyAware, FAKE_TOKEN } from './_helpers'

const AGENT_TYPE = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Ops Agent',
  description: 'Runs the on-call operations workflow',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: null,
  input_type: 'typed',
  input_schema: null,
  output_type: 'markdown',
  output_schema: null,
  output_data_type_id: null,
  output_data_type_name: null,
  sop_bindings: [],
  skill_bindings: [],
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null as unknown,
}

/** Model-authored sandboxed Python for the on-call workflow. */
const PYTHON_SOURCE = [
  'def run(tools, context):',
  '    result = tools.call("ops____query", {"scope": "on_call"})',
  '    return {"schedule": result["items"]}',
].join('\n')

const OPTIMIZATION_GATE = {
  can_optimize: true,
  successful_executions: 3,
  reason: null,
  can_generate_plan: true,
  is_conversational: false,
  optimization_conversation_available: true,
  optimizer_model_id: 'gpt-4.1-mini',
  optimizer_model_source: 'authoring',
}

/** Optimized plan with one scripted step and one model step. */
const OPTIMIZED_PLAN = {
  id: 'oplan-1',
  agent_type_id: AGENT_TYPE.id,
  agent_plan_id: 'plan-1',
  status: 'ready',
  fully_scripted: false,
  error: null,
  steps: [
    {
      order: 1,
      type: 'tool_call',
      name: 'Query on-call tool',
      description: 'Fetch the on-call schedule',
      python_source: PYTHON_SOURCE,
      scriptable: true,
    },
    {
      order: 2,
      type: 'semantic_bridge',
      name: 'Summarise schedule',
      description: 'Summarise who is on call',
      python_source: null,
      scriptable: false,
    },
  ],
  steps_count: 2,
  scripts_authored: 1,
  feedback_comments: [],
  generated_at: '2026-01-04T00:00:00Z',
}

/** Base plan whose first step is backed by a compiled script (E4a). */
function agentTypeWithPlan() {
  return {
    ...AGENT_TYPE,
    plan: {
      id: 'plan-1',
      agent_type_id: AGENT_TYPE.id,
      plan_steps: [
        {
          order: 1,
          type: 'tool_call',
          name: 'Query on-call tool',
          description: 'Fetch the on-call schedule',
          script_definition_id: 'def-1',
          script_version_id: 'ver-1',
        },
        {
          order: 2,
          type: 'semantic_bridge',
          name: 'Summarise schedule',
          description: 'Summarise who is on call',
        },
      ],
      topology_nodes: [],
      topology_edges: [],
      generation_status: 'success',
      generation_error: null,
      agent_config_hash: 'abc123',
      generated_at: '2026-01-01T00:00:00Z',
    },
  }
}

/** Optimized plan flagged by a later fallback (record_fallback → requires_fix). */
const REQUIRES_FIX_PLAN = {
  ...OPTIMIZED_PLAN,
  status: 'requires_fix',
  feedback_comments: [
    {
      created_at: '2026-01-05T00:00:00Z',
      raw_feedback: 'Fallback: tool schema mismatch (missing id key).',
      summary: 'Fallback: tool schema mismatch (missing id key).',
      source: 'execution_derived',
      source_execution_id: 'exec-9',
      source_fallback_event_id: 'fb-9',
    },
    {
      created_at: '2026-01-06T00:00:00Z',
      raw_feedback: 'Keep the summary short.',
      summary: 'Keep the summary short.',
      source: 'manual',
      source_execution_id: null,
      source_fallback_event_id: null,
    },
  ],
}

const respond = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

/**
 * Reference lists + the agent type itself. Registered base-first: the generic
 * collection glob is registered BEFORE the item / sub-resource mocks because
 * Playwright resolves handlers last-registered-first.
 */
async function mockAgentTypeApi(page: Page, agentType: unknown = AGENT_TYPE) {
  await page.route('**/api/v1/agents/types**', respond([AGENT_TYPE]))
  await page.route('**/api/v1/agents/types/*/optimization-gate', respond(OPTIMIZATION_GATE))
  await page.route(`**/api/v1/agents/types/${AGENT_TYPE.id}`, respond(agentType))
  // Reference lists the agents page maps over — must be arrays.
  await page.route('**/api/v1/agents/roles', respond([]))
  await page.route('**/api/v1/agents/identities', respond([]))
  await page.route('**/api/v1/agents/model-configs', respond([]))
  await page.route('**/api/v1/sops', respond([]))
  await page.route('**/api/v1/skills', respond([]))
}

/** GET /agents/types/{id}/optimized-plan (the tab's plan payload). */
async function mockOptimizedPlan(page: Page, plan: unknown) {
  await page.route('**/api/v1/agents/types/*/optimized-plan', respond(plan))
}

/** No optimized plan on record — the tab renders its informational empty state. */
async function mockOptimizedPlanAbsent(page: Page) {
  await page.route('**/api/v1/agents/types/*/optimized-plan', respond({ detail: 'Not found' }, 404))
}

/** Opens the agents list, opens the detail dialog. */
async function openAgentDialog(page: Page) {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  const row = page.getByText(AGENT_TYPE.name, { exact: true }).first()
  await expect(row).toBeVisible()
  await row.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  return dialog
}

test.describe('Agent Type script governance — plan surfaces (mocked)', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockAgentTypeApi(page)
  })

  test('no Scripts tab — script visibility lives on the Implementation Plan and Optimized Plan tabs', async ({
    page,
  }) => {
    await mockOptimizedPlanAbsent(page)
    const dialog = await openAgentDialog(page)

    // The dedicated Scripts tab was removed (superseded by the plan surfaces).
    await expect(dialog.getByRole('tab', { name: 'Scripts' })).toHaveCount(0)

    // The remaining tabs are the ones that carry script governance.
    await expect(dialog.getByRole('tab')).toHaveCount(6)
    await expect(dialog.getByRole('tab', { name: 'Implementation Plan' })).toBeVisible()
    await expect(dialog.getByRole('tab', { name: 'Optimized Plan' })).toBeVisible()

    // With no optimized plan on record the tab explains the state instead of
    // listing a script registry.
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
    await expect(dialog.getByTestId('optimized-plan-absent')).toBeVisible()
  })

  test('Implementation Plan links a script-backed step to the Optimized Plan tab (E4a)', async ({
    page,
  }) => {
    await mockAgentTypeApi(page, agentTypeWithPlan())
    await mockOptimizedPlan(page, OPTIMIZED_PLAN)

    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Implementation Plan' }).click()

    await expect(dialog.getByText('Query on-call tool')).toBeVisible()
    // Only the step carrying a script_version_id gets the script link.
    const scriptLinks = dialog
      .getByTestId('base-plan-tree')
      .getByRole('button', { name: 'Script', exact: true })
    await expect(scriptLinks).toHaveCount(1)

    // Opening the link lands on the Optimized Plan tab (the script governance
    // surface that replaced the removed Scripts tab).
    await scriptLinks.click()
    await expect(dialog.getByRole('tab', { name: 'Optimized Plan' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('ready')
  })

  test('script viewer shows the model-authored source and step description', async ({ page }) => {
    await mockAgentTypeApi(page, agentTypeWithPlan())
    await mockOptimizedPlan(page, OPTIMIZED_PLAN)

    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()

    // Only Python/scriptable steps expose the viewer action.
    await expect(dialog.getByTestId('optimized-plan-tree').getByTestId('view-script-1')).toBeVisible()
    await expect(dialog.getByTestId('optimized-plan-tree').getByTestId('view-script-2')).toHaveCount(0)

    await dialog.getByTestId('view-script-1').click()

    // Read-only viewer (its own dialog, layered above the details dialog).
    const viewer = page.getByRole('dialog').filter({ has: page.getByTestId('script-view-source') })
    await expect(viewer).toBeVisible()
    await expect(page.getByText('Script version Query on-call tool')).toBeVisible()
    await expect(viewer.getByTestId('script-view-source')).toContainText(
      'tools.call("ops____query"',
    )
    await expect(viewer.getByText('Fetch the on-call schedule')).toBeVisible()

    // The viewer supports a version chip, but the plan-step host supplies no
    // version_label and no lineage metadata — version history is no longer
    // surfaced here (it retired with the Scripts tab).
    await expect(viewer.getByText(/Serving Version/)).toHaveCount(0)
    await expect(viewer.getByText('repair of')).toHaveCount(0)

    await viewer.getByRole('button', { name: 'Close' }).click()
    await expect(page.getByTestId('script-view-source')).toHaveCount(0)
  })

  test('version lineage, verification, fallback and repair lists are retired — no registry API is called', async ({
    page,
  }) => {
    const scriptApiCalls: string[] = []
    page.on('request', (request) => {
      if (/\/api\/v1\/scripts(\/|\?|$)/.test(request.url())) scriptApiCalls.push(request.url())
    })

    await mockOptimizedPlan(page, OPTIMIZED_PLAN)
    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('ready')
    await dialog.getByTestId('view-script-1').click()
    await expect(page.getByTestId('script-view-source')).toBeVisible()

    // Per-version lineage / verification / fallback / repair tabs and the
    // promote action lived on the removed Scripts tab. Assert they are gone
    // rather than silently dropping the coverage.
    for (const retiredTab of ['Versions', 'Verifications', 'Fallbacks', 'Repairs']) {
      await expect(page.getByRole('tab', { name: retiredTab })).toHaveCount(0)
    }
    await expect(page.getByRole('button', { name: 'Promote' })).toHaveCount(0)
    await expect(page.getByText('derived', { exact: true })).toHaveCount(0)
    await expect(page.getByText('Promoted')).toHaveCount(0)
    await expect(page.getByText('Tool schema mismatch')).toHaveCount(0)
    await expect(page.getByText('Pending retry')).toHaveCount(0)

    // The governance surface is plan-backed: no script-registry requests.
    expect(scriptApiCalls).toEqual([])
  })

  test('optimized plan lifecycle: a ready plan retires into the retired state', async ({
    page,
  }) => {
    let retired = false
    const retireRequests: { method: string; url: string }[] = []

    await page.route('**/api/v1/agents/types/*/optimized-plan/retire', (route) => {
      retireRequests.push({ method: route.request().method(), url: route.request().url() })
      retired = true
      return respond({ retired: true, plans_removed: 1 })(route)
    })
    await page.route('**/api/v1/agents/types/*/optimized-plan', (route) =>
      respond(retired ? { ...OPTIMIZED_PLAN, status: 'retired' } : OPTIMIZED_PLAN)(route),
    )

    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('ready')

    const retireBtn = dialog.getByTestId('retire-optimized-plan')
    await expect(retireBtn).toBeEnabled()
    await retireBtn.click()

    await expect.poll(() => retireRequests.length).toBe(1)
    expect(retireRequests[0].method).toBe('POST')
    expect(retireRequests[0].url).toContain(`/agents/types/${AGENT_TYPE.id}/optimized-plan/retire`)

    // The plan is kept for reference but marked retired — execution stops
    // preferring it and the operator is told there is nothing left to retire.
    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('retired')
    await expect(dialog.getByTestId('retire-success')).toBeVisible()
    await expect(dialog.getByTestId('nothing-to-retire')).toBeVisible()
    await expect(dialog.getByTestId('retire-optimized-plan')).toBeDisabled()
  })

  test('permission-gated retire surfaces via the dialog error pattern without crashing', async ({
    page,
  }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route('**/api/v1/agents/types/*/optimized-plan/retire', respond(
      {
        detail: {
          detail: 'Permission denied',
          required_permission: { resource_type: 'agent::types', action: 'update' },
        },
      },
      403,
    ))
    await mockOptimizedPlan(page, OPTIMIZED_PLAN)

    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()
    await dialog.getByTestId('retire-optimized-plan').click()

    // dialogError standard: PermissionDeniedAlert renders instead of a crash.
    await expect(dialog.getByText(/Permission Denied/i)).toBeVisible()
    await expect(dialog.getByText(/agent::types/)).toBeVisible()
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toEqual([])
  })

  test('requires-fix alert surfaces in the Optimized Plan tab (auto-feedback dump retired)', async ({
    page,
  }) => {
    await page.route('**/api/v1/agents/types/*/optimized-plan', respond(REQUIRES_FIX_PLAN))

    const dialog = await openAgentDialog(page)
    await dialog.getByRole('tab', { name: 'Optimized Plan' }).click()

    await expect(dialog.getByTestId('optimized-plan-status')).toHaveText('requires_fix')
    const alert = dialog.getByTestId('requires-fix-alert')
    await expect(alert).toBeVisible()
    await expect(alert.getByText('This optimized plan requires a fix')).toBeVisible()
    // The operator can re-optimize straight from the alert (the conversation is
    // where recorded feedback is now discussed).
    await expect(alert.getByTestId('reoptimize-from-alert')).toBeVisible()

    // The execution-derived feedback dump was removed by product decision —
    // the conversational optimizer owns that narrative now.
    await expect(dialog.getByTestId('requires-fix-feedback-0')).toHaveCount(0)
    await expect(dialog.getByTestId('feedback-source-0')).toHaveCount(0)
    await expect(
      dialog.getByText('Fallback: tool schema mismatch (missing id key).'),
    ).toHaveCount(0)
  })

  test('no standalone /admin/scripts route or nav entry exists (A3/N8)', async ({ page }) => {
    await mockOptimizedPlanAbsent(page)

    // The old registry URL renders the 404 page, never a scripts registry.
    await page.goto('/admin/scripts')
    await page.waitForLoadState('load')
    await expect(page.getByText('notify-on-call')).toHaveCount(0)
    await expect(page.getByText('404', { exact: true })).toBeVisible()

    // No navigation entry anywhere links into a scripts registry.
    const navLinks = await page.locator('a[href*="admin/scripts"]').count()
    expect(navLinks).toBe(0)

    // The governed view remains reachable through the agent type dialog's plan
    // surfaces.
    await mockAgentTypeApi(page, agentTypeWithPlan())
    const dialog = await openAgentDialog(page)
    await expect(dialog.getByRole('tab', { name: 'Implementation Plan' })).toBeVisible()
    await expect(dialog.getByRole('tab', { name: 'Optimized Plan' })).toBeVisible()
  })
})
