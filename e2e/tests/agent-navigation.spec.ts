import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// The Agent Types table hides the Role column below `lg` (1200px) and the
// Identity column below `xl` (1536px). Desktop Chrome's default 1280px
// viewport therefore never renders the Identity column, so this spec runs at a
// wide viewport to exercise both resolved-name columns.
test.use({ viewport: { width: 1600, height: 1000 } })

// ── Mock data ──────────────────────────────────────────────────────────────────

const MOCK_ROLE = {
  id: 'role-1',
  name: 'Research Role',
  description: 'Role for research tasks',
  sop_ids: [],
  skill_ids: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_IDENTITY = {
  id: 'identity-1',
  name: 'Research Bot',
  identity_type: 'realm_user',
  realm_name: 'ai_agents',
  realm_username: 'research-bot',
  status: 'active',
  token_expires_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_AGENT_TYPE = {
  id: 'at-nav-1',
  name: 'Research Agent',
  description: 'Does deep research on topics',
  identity_id: 'identity-1',
  role_id: 'role-1',
  model_id: 'gpt-4o',
  system_instruction: 'You are a research assistant. Be thorough.',
  input_type: 'typed',
  input_schema: null,
  output_type: 'markdown',
  output_schema: null,
  sop_bindings: [],
  skill_bindings: [],
  guardrail_max_iterations: 10,
  guardrail_max_delegation_depth: 3,
  guardrail_max_delegated_steps: 20,
  guardrail_execution_timeout_seconds: 300,
  guardrail_token_budget: null,
  guardrail_token_enforcement_mode: 'observe',
  guardrail_token_fallback_mode: 'observe_and_log',
  guardrail_conversational_token_visibility_mode: 'enabled',
  guardrail_conversational_continuation_policy: 'allow',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  plan: null,
}

const MOCK_AGENT_TYPE_WITH_PLAN = {
  ...MOCK_AGENT_TYPE,
  plan: {
    id: 'plan-1',
    agent_type_id: 'at-nav-1',
    plan_steps: [
      { order: 1, type: 'tool_call', name: 'Gather Sources', description: 'Collect references' },
    ],
    topology_nodes: [{ id: 'role:r1', type: 'role', label: 'Research Role' }],
    topology_edges: [],
    generation_status: 'success',
    generation_error: null,
    agent_config_hash: 'abc123',
    generated_at: '2026-01-01T00:00:00Z',
  },
}

// Composed plan/optimize gate (GET /agents/types/{id}/optimization-gate).
// Typed agent with an authoring model configured but no successful execution
// yet — the surface renders normally and the gate does not poll aggressively.
const MOCK_OPTIMIZATION_GATE = {
  can_optimize: false,
  successful_executions: 0,
  reason: 'At least one successful execution is required.',
  can_generate_plan: true,
  workflow_model_configured: true,
  workflow_model_id: 'gpt-4o',
  is_conversational: false,
  reason_code: 'no_successful_execution',
  optimization_conversation_available: true,
  optimization_conversation_reason_code: 'no_successful_execution',
  optimizer_model_configured: true,
  optimizer_model_id: 'gpt-4o',
  optimizer_model_source: 'inherited',
  optimizer_model_reason_code: null,
}

const MOCK_SESSION = {
  id: 'session-abcdef12',
  agent_type_id: 'at-nav-1',
  triggered_by_user_id: 'user-1',
  input_data: null,
  status: 'completed',
  started_at: '2026-01-01T10:00:00Z',
  completed_at: '2026-01-01T10:05:00Z',
  output_data: null,
  error_message: null,
  conversation_history: null,
  created_at: '2026-01-01T10:00:00Z',
}

// ── Shared setup ───────────────────────────────────────────────────────────────

/**
 * Registers every API mock this spec needs.
 *
 * Patterns end with `**` because the app appends pagination/filter query
 * params (`?limit=25&offset=0`), which a pattern without the trailing wildcard
 * would never match — the request would then hit the (stopped) backend and the
 * page would render a network error instead of data.
 *
 * Playwright resolves routes last-registered-first, so generic collection
 * routes are registered BEFORE the more specific item/sub-resource routes.
 */
async function setupAgentNavPage(page: import('@playwright/test').Page) {
  await standardSetup(page)

  // ── Agent types ────────────────────────────────────────────────────────────
  // Collection (also matches the id-less `useAgentTypes()` call).
  await page.route('**/api/v1/agents/types**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_AGENT_TYPE]),
    }),
  )
  // Single agent type by ID — registered after (higher priority).
  await page.route('**/api/v1/agents/types/at-nav-1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_AGENT_TYPE),
    }),
  )
  // Plan/optimize precondition gate — read by the details dialog and the
  // Optimize action.
  await page.route('**/api/v1/agents/types/*/optimization-gate', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_OPTIMIZATION_GATE),
    }),
  )

  // ── Execution sessions ─────────────────────────────────────────────────────
  // Sessions collection (executions page, dialog Execution Logs tab, embedded
  // executions dialog) — registered first so the item routes below win.
  await page.route('**/api/v1/agents/sessions**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_SESSION]),
    }),
  )
  // Individual session detail — for AgentJobPage in execution details dialog.
  await page.route('**/api/v1/agents/sessions/session-abcdef12', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SESSION),
    }),
  )
  // Session logs — for AgentJobPage log viewer.
  await page.route('**/api/v1/agents/sessions/session-abcdef12/logs', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  // Session execution logs — for AgentJobPage execution log section.
  await page.route('**/api/v1/agents/sessions/session-abcdef12/execution-logs', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // ── Roles ──────────────────────────────────────────────────────────────────
  // Roles collection — returns populated data for table column name resolution.
  await page.route('**/api/v1/agents/roles**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_ROLE]) }),
  )
  // Individual role by ID — for AgentRoleViewDialog.
  await page.route('**/api/v1/agents/roles/role-1', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_ROLE) }),
  )
  // Role sub-resources — for AgentRoleDialog (edit form).
  await page.route('**/api/v1/agents/roles/role-1/identities', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/agents/roles/role-1/mcp-sessions', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/agents/roles/role-1/mcp-tools**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  // Delegation preview used by AgentRoleDialog — must be a string[] of agent
  // type names, otherwise the dialog renders objects as React children.
  await page.route('**/api/v1/agents/roles/role-1/allowed-agent-types**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // ── Identities ─────────────────────────────────────────────────────────────
  // Identities collection — returns populated data for table column resolution.
  await page.route('**/api/v1/agents/identities**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_IDENTITY]),
    }),
  )
  // Individual identity by ID — for AgentIdentityViewDialog.
  await page.route('**/api/v1/agents/identities/identity-1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_IDENTITY),
    }),
  )

  // SOPs and skills — needed when AgentRoleDialog (edit form) opens.
  await page.route('**/api/v1/sops**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/skills**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // MCP hub lists — read by AgentRoleDialog's tool preview.
  await page.route('**/api/v1/mcp/servers**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/mcp/tools**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // Conversations (Conversation History tab).
  await page.route('**/api/v1/conversations**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // Intervention metrics polled by the app shell.
  await page.route('**/api/v1/intervene/metrics**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ pending_count: 0 }),
    }),
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('Agents nav group', () => {
  test('shows Agents nav group in sidebar', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // The group header with "Agents" text should be visible
    await expect(page.getByRole('button', { name: /^Agents$/i })).toBeVisible({ timeout: 10000 })
  })

  test('nav group is expanded by default and shows child items', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // The group containing the active route auto-expands, so its child items
    // are visible even though groups start collapsed.
    // "Agent Management" is the current label of the `nav.agentTypes` entry.
    // (`exact` avoids also matching "Agent Management Panel".)
    await expect(page.getByRole('button', { name: 'Agent Management', exact: true })).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('button', { name: 'Agent Management Panel' })).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('button', { name: 'Agent Roles' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Agent Identities' })).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('button', { name: 'Agent Trails' })).toBeVisible({ timeout: 10000 })
  })

  test('collapses and expands nav group on header click', async ({ page }) => {
    await setupAgentNavPage(page)
    // Navigate to a route outside the Agents group: the group containing the
    // active route is force-expanded, so collapse/expand can only be observed
    // from a different module.
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // Groups start collapsed when none of their children is active.
    await expect(page.getByRole('button', { name: 'Agent Roles' })).not.toBeVisible({
      timeout: 5000,
    })

    // Click the group header to expand
    await page.getByRole('button', { name: /^Agents$/i }).click()
    await expect(page.getByRole('button', { name: 'Agent Roles' })).toBeVisible({ timeout: 5000 })

    // Click again to collapse
    await page.getByRole('button', { name: /^Agents$/i }).click()
    await expect(page.getByRole('button', { name: 'Agent Roles' })).not.toBeVisible({
      timeout: 5000,
    })
  })

  test('clicking Agent Trails navigates to /agent-trails', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // Agent Executions and Conversation History were consolidated into the
    // single "Agent Trails" entry (tabs inside the page).
    await page.getByRole('button', { name: 'Agent Trails' }).click()
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agent-trails')
    await expect(
      page.getByRole('heading', { name: 'Agent Trails', exact: true }),
    ).toBeVisible({ timeout: 10000 })
    // The executions trail is the first tab inside the page.
    await expect(page.getByRole('tab', { name: 'Agent Executions' })).toBeVisible({
      timeout: 10000,
    })
  })

  test('clicking Agent Roles navigates to /agents/roles', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Agent Roles' }).click()
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agents/roles')
  })

  test('clicking Agent Identities navigates to /agents/identities', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Agent Identities' }).click()
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agents/identities')
  })
})

test.describe('Agent Executions page', () => {
  test('navigating to /agents/instances redirects to /agents/executions', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents/instances')
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agents/executions')
  })

  test('Agent Executions page shows the page title', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents/executions')
    await page.waitForLoadState('networkidle')

    // Scope to main content area to avoid nav sidebar matches
    await expect(
      page.locator('main').getByRole('heading', { name: 'Agent Executions' }),
    ).toBeVisible({ timeout: 10000 })
  })

  test('agent type filter dropdown is visible on executions page', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents/executions')
    await page.waitForLoadState('networkidle')

    // Filter dropdown label — use first() in case it appears more than once
    await expect(page.getByText('Filter by Agent Type').first()).toBeVisible({ timeout: 10000 })
  })

  test('selecting agent type filter refetches sessions', async ({ page }) => {
    await setupAgentNavPage(page)

    // Track requests to sessions endpoint
    const sessionRequests: string[] = []
    await page.route('**/api/v1/agents/sessions**', (route) => {
      sessionRequests.push(route.request().url())
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([MOCK_SESSION]),
      })
    })

    await page.goto('/agents/executions')
    await page.waitForLoadState('networkidle')

    // Open the agent type filter — it is the first MUI Select on the page.
    const filterCombobox = page.locator('[aria-haspopup="listbox"]').first()
    await filterCombobox.click()

    // Select "Research Agent" from dropdown
    await expect(page.getByRole('option', { name: 'Research Agent' })).toBeVisible({
      timeout: 5000,
    })
    await page.getByRole('option', { name: 'Research Agent' }).click()

    await page.waitForLoadState('networkidle')

    // A request with agent_type_id should have been made
    expect(sessionRequests.some((url) => url.includes('agent_type_id=at-nav-1'))).toBe(true)
  })
})

test.describe('Agent Type Details Dialog', () => {
  test('clicking agent type row opens details dialog', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // The agent type table row should show the agent name
    await expect(page.getByRole('cell', { name: 'Research Agent' })).toBeVisible({ timeout: 10000 })

    // Click the row
    await page.getByRole('cell', { name: 'Research Agent' }).click()

    // Dialog should open
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })
  })

  test('dialog shows agent type name and its tabs', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()

    // Wait for dialog
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Dialog title shows "Research Agent" — use first() since name also appears in Details tab
    await expect(page.getByRole('dialog').getByText('Research Agent').first()).toBeVisible({
      timeout: 10000,
    })

    // Tabs: the former "Plan Preview" tab is now "Implementation Plan".
    await expect(page.getByRole('tab', { name: 'Details' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('tab', { name: 'Agent Topology' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('tab', { name: 'Implementation Plan' })).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('tab', { name: 'Execution Logs' })).toBeVisible({ timeout: 10000 })
  })

  test('dialog Details tab shows agent metadata', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Model ID should be displayed
    await expect(page.getByRole('dialog').getByText('gpt-4o')).toBeVisible({ timeout: 10000 })
    // System instruction (Details tab label is "System Prompt")
    await expect(
      page.getByRole('dialog').getByText(/You are a research assistant/),
    ).toBeVisible({ timeout: 10000 })
  })

  // NOTE (product gap, not a spec drift fix): the Details tab no longer renders
  // the "Execution Guardrails" block — guardrails are now edited in the Agent
  // Management Panel / Agent Type form. The test still verifies the values are
  // reachable from the details dialog, via its Edit action.
  test('details dialog Edit action exposes execution guardrails', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    const detailsDialog = page.getByRole('dialog').first()
    await expect(detailsDialog).toBeVisible({ timeout: 10000 })

    // Edit on the details dialog opens the agent type form.
    await detailsDialog.getByRole('button', { name: 'Edit' }).click()

    const editDialog = page.getByRole('dialog', { name: 'Edit Agent Type' }).first()
    await expect(editDialog).toBeVisible({ timeout: 10000 })

    // Guardrails live in a collapsed accordion.
    await editDialog.getByText('Execution Guardrails').click()

    await expect(editDialog.getByRole('spinbutton', { name: 'Max Iterations' })).toHaveValue(
      '10',
    )
    // MUI Selects in this app carry no accessible name (their InputLabel has no
    // id), so the field is located through its FormControl wrapper.
    const fallbackField = editDialog
      .locator('.MuiFormControl-root')
      .filter({ hasText: 'Token Fallback Mode' })
      .first()
    await expect(fallbackField.getByRole('combobox')).toHaveText('Observe and log')
  })

  test('switching to Implementation Plan tab shows no-plan placeholder when plan is null', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await page.getByRole('tab', { name: 'Implementation Plan' }).click()

    // Empty-state placeholder
    await expect(
      page.getByRole('dialog').getByText(/No implementation plan yet/i),
    ).toBeVisible({ timeout: 5000 })
  })

  test('Implementation Plan tab shows plan steps when plan is populated', async ({ page }) => {
    await setupAgentNavPage(page)

    // Override the single agent type route with one that has a plan
    await page.route('**/api/v1/agents/types/at-nav-1', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_AGENT_TYPE_WITH_PLAN),
      }),
    )

    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await page.getByRole('tab', { name: 'Implementation Plan' }).click()

    // Plan step name should be visible
    await expect(page.getByText('Gather Sources')).toBeVisible({ timeout: 10000 })
  })

  test('Execution Logs tab shows sessions filtered by agent type', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await page.getByRole('tab', { name: 'Execution Logs' }).click()

    // Session ID 'session-abcdef12'.slice(0,8) = 'session-' (8 chars), displayed with ellipsis
    await expect(page.getByRole('dialog').getByText(/session-/)).toBeVisible({ timeout: 10000 })
  })

  test('"View All Executions" button opens executions dialog', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Switch to Execution Logs tab
    await page.getByRole('tab', { name: 'Execution Logs' }).click()

    // Click "View All Executions" button
    await page.getByRole('button', { name: /View All Executions/i }).click()

    // Should open a second dialog with the executions dashboard
    await expect(page.getByRole('dialog', { name: /Agent Executions/ })).toBeVisible({ timeout: 10000 })
  })

  test('clicking identity name in Details tab opens identity view dialog', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Identity name resolves to 'Research Bot' from the identities list
    await expect(page.getByRole('button', { name: 'Research Bot' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Research Bot' }).click()

    // A second dialog should appear — the identity view dialog
    await expect(page.getByRole('dialog', { name: 'Agent Identity' })).toBeVisible({
      timeout: 10000,
    })
  })

  test('identity view dialog has Edit button that navigates to identities page', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await expect(page.getByRole('button', { name: 'Research Bot' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Research Bot' }).click()

    await expect(page.getByRole('dialog', { name: 'Agent Identity' })).toBeVisible({
      timeout: 10000,
    })
    const editBtn = page
      .getByRole('dialog', { name: 'Agent Identity' })
      .getByRole('button', { name: 'Edit' })
    await expect(editBtn).toBeVisible({ timeout: 5000 })

    await editBtn.click()
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agents/identities')
  })

  test('clicking role name in Details tab opens role view dialog', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Role name resolves to 'Research Role' from the roles list
    await expect(page.getByRole('button', { name: 'Research Role' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Research Role' }).click()

    await expect(page.getByRole('dialog', { name: 'Agent Role' })).toBeVisible({ timeout: 10000 })
  })

  // NOTE (product gap): the details dialog now reuses AgentRoleDialog in
  // read-only `view` mode, which exposes no Edit action — roles are edited from
  // the Agent Roles list page. The test verifies both halves of that behaviour.
  test('role view dialog is read-only; role edit form opens from the Agent Roles page', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await expect(page.getByRole('button', { name: 'Research Role' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Research Role' }).click()

    const roleDialog = page.getByRole('dialog', { name: 'Agent Role' })
    await expect(roleDialog).toBeVisible({ timeout: 10000 })

    // Read-only view: no Edit action inside the dialog, Close only.
    await expect(roleDialog.getByRole('button', { name: 'Edit' })).toHaveCount(0)
    await roleDialog.getByRole('button', { name: 'Close' }).click()

    // Role editing lives on the Agent Roles list page.
    await page.goto('/agents/roles')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Edit' }).first().click()

    // Role edit form dialog should open
    await expect(page.getByRole('dialog', { name: 'Edit Agent Role' })).toBeVisible({
      timeout: 5000,
    })
  })

  test('closing dialog via close button works', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    // Close button in DialogTitle
    await page.getByRole('button', { name: 'Close' }).click()

    await expect(page.getByRole('dialog')).not.toBeVisible({ timeout: 5000 })
  })
})

// ── Nav menu order ─────────────────────────────────────────────────────────────

test.describe('Nav menu order', () => {
  test('Agent Roles and Agent Identities appear above Agent Management in the nav', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    const rolesButton = page.getByRole('button', { name: 'Agent Roles' })
    const identitiesButton = page.getByRole('button', { name: 'Agent Identities' })
    const typesButton = page.getByRole('button', { name: 'Agent Management', exact: true })
    const trailsButton = page.getByRole('button', { name: 'Agent Trails' })

    await expect(rolesButton).toBeVisible({ timeout: 10000 })

    const rolesY = (await rolesButton.boundingBox())?.y ?? 0
    const identitiesY = (await identitiesButton.boundingBox())?.y ?? 0
    const typesY = (await typesButton.boundingBox())?.y ?? 0
    const trailsY = (await trailsButton.boundingBox())?.y ?? 0

    // Roles → Identities → Agent Management → Agent Trails (top to bottom)
    expect(rolesY).toBeLessThan(identitiesY)
    expect(identitiesY).toBeLessThan(typesY)
    expect(typesY).toBeLessThan(trailsY)
  })
})

// ── Agent Types table columns ──────────────────────────────────────────────────

test.describe('Agent Types table columns', () => {
  test('Agent Types table has Role and Identity column headers', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('columnheader', { name: 'Role' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('columnheader', { name: 'Identity' })).toBeVisible({
      timeout: 10000,
    })
  })

  test('Role column shows resolved role name for agent type', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // MOCK_AGENT_TYPE has role_id 'role-1'; roles list returns MOCK_ROLE with name 'Research Role'
    await expect(page.getByRole('cell', { name: 'Research Role' })).toBeVisible({ timeout: 10000 })
  })

  test('Identity column shows resolved identity name for agent type', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // MOCK_AGENT_TYPE has identity_id 'identity-1'; identities list returns MOCK_IDENTITY with name 'Research Bot'
    await expect(page.getByRole('cell', { name: 'Research Bot' })).toBeVisible({ timeout: 10000 })
  })
})
