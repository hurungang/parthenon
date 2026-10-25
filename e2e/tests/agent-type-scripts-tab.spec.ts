/**
 * E2E: Software 3.0 agent-owned scripts — Scripts tab of the Agent Type
 * detail dialog (fully mocked via page.route(); no live backend).
 *
 * The standalone /admin/scripts registry module was REMOVED: scripts are
 * agent-owned functions and all governance visibility lives in the Agent
 * Type detail dialog's Scripts tab. Journeys covered:
 *   1. Scripts tab lists the agent type's scripts with description,
 *      lifecycle and health state (A1, G1)
 *   2. Version lineage incl. `repaired_from` + verification evidence +
 *      fallback reason are viewable per script (A2, V2, F2)
 *   3. Repairs list shows repair attempts recorded after fallback (E10, F3)
 *   4. Operator promotes a version from the tab (asserted request payload)
 *   5. Operator retires a version from the tab
 *   6. Plan review shows script links on script-backed steps and opening
 *      one lands in the Scripts tab (E4a)
 *   7. Permission-gated actions surface via the dialog error pattern, no crash
 *   8. Absence of any standalone /admin/scripts route or nav entry (A3/N8)
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

const FALLBACK_DETAIL = "Tool 'ops____query' result missing expected keys: ['id']"

const VERIFICATION_RUN = {
  id: 'vr-1',
  script_version_id: 'ver-1',
  reference_execution_id: 'ref-sess-1',
  comparison_outcome: 'match',
  verdict: 'promoted',
  verdict_reason: null,
  input_context: { ticket: 'T-1' },
  expected_output: { result: { x: 1 } },
  actual_output: { result: { x: 1 } },
  created_at: '2026-01-01T00:00:00Z',
}

const FALLBACK_EVENT = {
  id: 'fb-1',
  execution_record_id: 'exec-1',
  script_version_id: 'ver-1',
  trigger_reason: 'tool_schema_mismatch',
  resulting_action: 'repaired_candidate_produced',
  failure_detail: FALLBACK_DETAIL,
  script_health_impact: 1,
  repaired_version_id: 'ver-2',
  created_at: '2026-01-02T00:00:00Z',
}

const REPAIR_ATTEMPTS = {
  items: [
    {
      id: 'ra-1',
      fallback_event_id: 'fb-1',
      script_version_id: 'ver-1',
      repaired_version_id: 'ver-2',
      defect_diagnosis: 'tool schema drifted: missing id key',
      diff_applied: 'repair attempt 1 (tool_schema_mismatch)',
      retry_outcome: 'pending',
      created_at: '2026-01-03T00:00:00Z',
    },
    {
      id: 'ra-2',
      fallback_event_id: 'fb-2',
      script_version_id: 'ver-2',
      repaired_version_id: 'ver-3',
      defect_diagnosis: 'output validation failed',
      diff_applied: null,
      retry_outcome: 'succeeded',
      created_at: '2026-01-04T00:00:00Z',
    },
  ],
  total: 2,
}

function makeVersion(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ver-1',
    script_definition_id: 'def-1',
    version_label: 'v1',
    lifecycle_status: 'verified',
    declarative_step_graph: {
      name: 'notify-on-call',
      steps: [{ kind: 'tool_call', name: 's1', tool_name: 'ops____query' }],
    },
    parent_version_id: null,
    repaired_from_id: null,
    created_by: 'agent-runtime-compiler',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

/** v2 is a repair candidate derived from v1 (E10 lineage). */
const REPAIRED_VERSION = makeVersion({
  id: 'ver-2',
  version_label: 'v2',
  lifecycle_status: 'draft',
  parent_version_id: 'ver-1',
  repaired_from_id: 'ver-1',
  created_by: 'repair-loop',
  created_at: '2026-01-03T00:00:00Z',
})

const SCRIPT_DEFINITION = {
  id: 'def-1',
  name: 'notify-on-call',
  description: 'Compiled bridge for the on-call notification workflow',
  lifecycle_status: 'compiled',
  health_status: 'degraded',
  agent_type_id: AGENT_TYPE.id,
  source_plan_id: null,
  source_session_id: null,
  current_version_id: 'ver-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  versions: [makeVersion(), REPAIRED_VERSION],
}

/** Plan whose first step is backed by the compiled script (E4a). */
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

const respond = (body: unknown, status = 200) => (route: Route) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

async function mockAgentTypeApi(page: Page, agentType: unknown = AGENT_TYPE) {
  // Register broad patterns first — Playwright resolves handlers
  // last-registered-first, so the specific detail mock keeps priority.
  await page.route(/\/api\/v1\/agents\/types\?.*/, respond([AGENT_TYPE]))
  await page.route('**/api/v1/agents/types/**', respond([]))
  await page.route('**/api/v1/agents/types/' + AGENT_TYPE.id, respond(agentType))
  // Reference lists the agents page maps over — must be arrays, not the
  // catch-all's `{}` (which crashes rendering with `.map is not a function`).
  await page.route('**/api/v1/agents/roles', respond([]))
  await page.route('**/api/v1/agents/identities', respond([]))
  await page.route('**/api/v1/agents/model-configs', respond([]))
  await page.route('**/api/v1/sops', respond([]))
  await page.route('**/api/v1/skills', respond([]))
}

async function mockScriptsApi(
  page: Page,
  options: { versions?: unknown[]; denyRead?: boolean } = {},
) {
  const versions = options.versions ?? [makeVersion(), REPAIRED_VERSION]
  if (options.denyRead) {
    await page.route('**/api/v1/scripts**', respond(
      { detail: { required_permission: { resource_type: 'agent::scripts', action: 'read' } } },
      403,
    ))
    return
  }
  await page.route(/\/api\/v1\/scripts\/?\?.*/, (route) => {
    const url = new URL(route.request().url())
    // The tab always scopes by owning agent type.
    expect(url.searchParams.get('agent_type_id')).toBe(AGENT_TYPE.id)
    return respond({ items: [SCRIPT_DEFINITION], total: 1 })(route)
  })
  await page.route('**/api/v1/scripts/def-1/versions', respond(versions))
  await page.route('**/api/v1/scripts/def-1/verifications', respond({ items: [VERIFICATION_RUN], total: 1 }))
  await page.route('**/api/v1/scripts/def-1/fallbacks', respond({ items: [FALLBACK_EVENT], total: 1 }))
  await page.route('**/api/v1/scripts/def-1/repairs', respond(REPAIR_ATTEMPTS))
  await page.route('**/api/v1/scripts/def-1/health', respond({}))
}

/** Opens the agent type list, opens the detail dialog, switches to Scripts tab. */
async function openScriptsTab(page: Page) {
  await page.goto('/agents')
  await page.waitForLoadState('load')
  if (page.url().includes('/login')) test.skip()
  await page.getByText(AGENT_TYPE.name, { exact: true }).first().click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('tab', { name: 'Scripts' }).click()
  return dialog
}

test.describe('Agent Type Scripts tab — agent-owned script governance', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
    await mockAgentTypeApi(page)
  })

  test('Scripts tab lists the agent type script with description, lifecycle and health', async ({
    page,
  }) => {
    await mockScriptsApi(page)
    const dialog = await openScriptsTab(page)

    await expect(dialog.getByText('notify-on-call')).toBeVisible()
    // Human-readable description (A1)
    await expect(dialog.getByText('Compiled bridge for the on-call notification workflow')).toBeVisible()
    // Lifecycle + health chips (G1)
    await expect(dialog.getByText('Compiled', { exact: true }).first()).toBeVisible()
    await expect(dialog.getByText('Degraded', { exact: true }).first()).toBeVisible()
  })

  test('version lineage with repaired_from and verification evidence are visible', async ({
    page,
  }) => {
    await mockScriptsApi(page)
    const dialog = await openScriptsTab(page)

    // Both versions render; v2 carries derived + repair-of lineage badges (A2)
    await expect(dialog.getByText('v1', { exact: true })).toBeVisible()
    await expect(dialog.getByText('v2', { exact: true })).toBeVisible()
    await expect(dialog.getByText('derived')).toBeVisible()
    await expect(dialog.getByText('repair of')).toBeVisible()

    // Verification evidence (V2)
    await dialog.getByRole('tab', { name: 'Verifications' }).click()
    await expect(dialog.getByText('Promoted')).toBeVisible()

    // Fallback reason recorded with the trigger type (F2)
    await dialog.getByRole('tab', { name: 'Fallbacks' }).click()
    await expect(dialog.getByText('Tool schema mismatch')).toBeVisible()
    await expect(dialog.getByText(FALLBACK_DETAIL)).toBeVisible()
    await expect(dialog.getByText('Repair candidate produced')).toBeVisible()
  })

  test('Repairs list shows repair attempts recorded after fallback (E10)', async ({ page }) => {
    await mockScriptsApi(page)
    const dialog = await openScriptsTab(page)

    await dialog.getByRole('tab', { name: 'Repairs' }).click()
    // Each attempt: diagnosis + retry outcome + diff (F3)
    await expect(dialog.getByText('tool schema drifted: missing id key')).toBeVisible()
    await expect(dialog.getByText('Pending retry')).toBeVisible()
    await expect(dialog.getByText('repair attempt 1 (tool_schema_mismatch)')).toBeVisible()
    await expect(dialog.getByText('output validation failed')).toBeVisible()
    await expect(dialog.getByText('Retry succeeded')).toBeVisible()
  })

  test('operator promotes a version from the Scripts tab (asserted payload)', async ({ page }) => {
    await mockScriptsApi(page, {
      versions: [makeVersion({ lifecycle_status: 'verified', id: 'ver-1' })],
    })

    let promotePayload: Record<string, unknown> | null = null
    await page.route('**/api/v1/scripts/def-1/versions/ver-1/promote', async (route) => {
      promotePayload = route.request().postDataJSON()
      return respond(makeVersion({ lifecycle_status: 'compiled' }))(route)
    })

    const dialog = await openScriptsTab(page)
    await dialog.getByRole('button', { name: 'Promote' }).first().click()
    await expect.poll(() => promotePayload).not.toBeNull()
    expect(promotePayload).toMatchObject({ target_status: 'verified' })
  })

  test('operator retires a version from the Scripts tab', async ({ page }) => {
    await mockScriptsApi(page)
    let retireCalled = false
    await page.route('**/api/v1/scripts/def-1/versions/ver-1/retire', async (route) => {
      retireCalled = true
      return respond(makeVersion({ lifecycle_status: 'retired' }))(route)
    })

    const dialog = await openScriptsTab(page)
    await dialog.getByRole('button', { name: 'Retire' }).first().click()
    await expect.poll(() => retireCalled).toBe(true)
  })

  test('plan review shows a script link on the script-backed step and opens the Scripts tab (E4a)', async ({
    page,
  }) => {
    await mockScriptsApi(page)
    await mockAgentTypeApi(page, agentTypeWithPlan())

    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.getByText(AGENT_TYPE.name, { exact: true }).first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Plan tab (Agent Preview) renders the plan with the script link on the
    // script-backed step only.
    await dialog.getByRole('tab', { name: 'Agent Preview' }).click()
    await expect(dialog.getByText('Query on-call tool')).toBeVisible()
    const scriptLinks = dialog.getByRole('button', { name: 'Script', exact: true })
    await expect(scriptLinks).toHaveCount(1)

    // Opening the link lands in the Scripts tab (C3/E4a).
    await scriptLinks.click()
    await expect(
      dialog.getByRole('tab', { name: 'Scripts' }),
    ).toHaveAttribute('aria-selected', 'true')
    await expect(dialog.getByText('notify-on-call')).toBeVisible()
  })

  test('permission-gated promote surfaces via the dialog error pattern without crashing', async ({
    page,
  }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await mockScriptsApi(page)
    await page.route('**/api/v1/scripts/def-1/versions/ver-1/promote', respond(
      { detail: { required_permission: { resource_type: 'agent::scripts', action: 'manage' } } },
      403,
    ))

    const dialog = await openScriptsTab(page)
    await dialog.getByRole('button', { name: 'Promote' }).first().click()

    // dialogError standard: PermissionDeniedAlert renders instead of a crash
    await expect(dialog.getByText(/Permission Denied/i)).toBeVisible()
    await expect(dialog.getByText(/agent::scripts/)).toBeVisible()
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toEqual([])
  })

  test('no standalone /admin/scripts route or nav entry exists (A3/N8)', async ({ page }) => {
    await mockScriptsApi(page)

    // The old registry URL no longer renders a registry page.
    await page.goto('/admin/scripts')
    await page.waitForLoadState('load')
    await expect(page.getByText('notify-on-call')).toHaveCount(0)

    // No navigation entry anywhere links into a scripts registry.
    const navLinks = await page.locator('a[href*="admin/scripts"]').count()
    expect(navLinks).toBe(0)

    // The governed view remains reachable through the agent type dialog.
    await mockAgentTypeApi(page, agentTypeWithPlan())
    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.getByText(AGENT_TYPE.name, { exact: true }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('dialog').getByRole('tab', { name: 'Scripts' })).toBeVisible()
  })
})
