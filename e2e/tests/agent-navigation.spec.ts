import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

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
  primary_sop_id: null,
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

async function setupAgentNavPage(page: import('@playwright/test').Page) {
  await standardSetup(page)

  // Single agent type detail — registered first (lower priority, LIFO)
  await page.route('**/api/v1/agents/types', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_AGENT_TYPE]),
    }),
  )

  // Single agent type by ID — registered after (higher priority)
  await page.route('**/api/v1/agents/types/at-nav-1', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_AGENT_TYPE),
    }),
  )

  // Individual session detail — for AgentJobPage in execution details dialog
  await page.route('**/api/v1/agents/sessions/session-abcdef12', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SESSION),
    }),
  )

  // Session logs — for AgentJobPage log viewer
  await page.route('**/api/v1/agents/sessions/session-abcdef12/logs', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    }),
  )

  // Session execution logs — for AgentJobPage execution log section
  await page.route('**/api/v1/agents/sessions/session-abcdef12/execution-logs', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([]),
    }),
  )

  // Sessions list (with or without query params) — must come after specific session routes
  await page.route('**/api/v1/agents/sessions**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([MOCK_SESSION]),
    }),
  )

  // Roles list — returns populated data for table column name resolution
  await page.route('**/api/v1/agents/roles', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_ROLE]) }),
  )
  // Individual role by ID — for AgentRoleViewDialog
  await page.route('**/api/v1/agents/roles/role-1', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_ROLE) }),
  )
  // Role sub-resources — for AgentRoleDialog (edit form)
  await page.route('**/api/v1/agents/roles/role-1/identities', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/agents/roles/role-1/mcp-sessions', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/agents/roles/role-1/mcp-tools', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // Identities list — returns populated data for table column name resolution
  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_IDENTITY]) }),
  )
  // Individual identity by ID — for AgentIdentityViewDialog
  await page.route('**/api/v1/agents/identities/identity-1', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_IDENTITY) }),
  )

  // SOPs and skills — needed when AgentRoleDialog (edit form) opens
  await page.route('**/api/v1/sops', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
  await page.route('**/api/v1/skills', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  // Conversations (Agent Logs page)
  await page.route('**/api/v1/conversations**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('AI Agent nav group', () => {
  test('shows AI Agent nav group in sidebar', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // The group header with "AI Agent" text should be visible
    await expect(page.getByRole('button', { name: /AI Agent/i })).toBeVisible({ timeout: 10000 })
  })

  test('nav group is expanded by default and shows child items', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // Child items should be visible when group is expanded (default)
    await expect(page.getByRole('button', { name: 'Agent Types' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Agent Executions' })).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('button', { name: 'Agent Logs' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Agent Roles' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Agent Identities' })).toBeVisible({
      timeout: 10000,
    })
  })

  test('collapses and expands nav group on header click', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    // Verify "Agent Types" is visible (expanded)
    await expect(page.getByRole('button', { name: 'Agent Types' })).toBeVisible({ timeout: 10000 })

    // Click the group header to collapse
    await page.getByRole('button', { name: /AI Agent/i }).click()

    // Child items should be hidden after collapse
    await expect(page.getByRole('button', { name: 'Agent Types' })).not.toBeVisible({
      timeout: 5000,
    })

    // Click again to expand
    await page.getByRole('button', { name: /AI Agent/i }).click()

    // Child items visible again
    await expect(page.getByRole('button', { name: 'Agent Types' })).toBeVisible({ timeout: 5000 })
  })

  test('clicking Agent Executions navigates to /agents/executions', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Agent Executions' }).click()
    await page.waitForLoadState('networkidle')

    expect(page.url()).toContain('/agents/executions')
    // The page heading is an h4, distinct from the nav button
    await expect(page.getByRole('heading', { name: 'Agent Executions' })).toBeVisible({
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

    // Open the filter dropdown — click the first MUI Select combobox (agent type is first filter)
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

  test('dialog shows agent type name and Details tab', async ({ page }) => {
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

    // Three tabs should be visible
    await expect(page.getByRole('tab', { name: 'Details' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('tab', { name: 'Plan Preview' })).toBeVisible({ timeout: 10000 })
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
    // System instruction
    await expect(
      page.getByRole('dialog').getByText(/You are a research assistant/),
    ).toBeVisible({ timeout: 10000 })
  })

  test('switching to Plan Preview tab shows no-plan placeholder when plan is null', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await page.getByRole('tab', { name: 'Plan Preview' }).click()

    // Should show placeholder text
    await expect(page.getByRole('dialog').getByText(/No plan generated/i)).toBeVisible({
      timeout: 5000,
    })
  })

  test('Plan Preview tab shows plan steps when plan is populated', async ({ page }) => {
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

    await page.getByRole('tab', { name: 'Plan Preview' }).click()

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

    // Should open a second dialog with executions list
    await expect(page.getByRole('dialog', { name: /Agent Executions/ })).toBeVisible({ timeout: 10000 })
  })

  // TODO: Add test for execution details dialog once dialog rendering issue is resolved
  // test('clicking View on an execution opens execution details dialog', async ({ page }) => {
  //   await setupAgentNavPage(page)
  //   await page.goto('/agents')
  //   await page.waitForLoadState('networkidle')
  //   await page.getByRole('cell', { name: 'Research Agent' }).click()
  //   await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })
  //   await page.getByRole('tab', { name: 'Execution Logs' }).click()
  //   await page.getByRole('button', { name: 'View' }).first().click()
  //   await expect(page.getByText('Execution Details')).toBeVisible({ timeout: 10000 })
  // })

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

  test('role view dialog has Edit button that opens role edit form', async ({ page }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await page.getByRole('cell', { name: 'Research Agent' }).click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10000 })

    await expect(page.getByRole('button', { name: 'Research Role' })).toBeVisible({ timeout: 10000 })
    await page.getByRole('button', { name: 'Research Role' }).click()

    await expect(page.getByRole('dialog', { name: 'Agent Role' })).toBeVisible({ timeout: 10000 })
    const editBtn = page
      .getByRole('dialog', { name: 'Agent Role' })
      .getByRole('button', { name: 'Edit' })
    await expect(editBtn).toBeVisible({ timeout: 5000 })

    await editBtn.click()

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
  test('Agent Roles and Agent Identities appear above Agent Types in the nav', async ({
    page,
  }) => {
    await setupAgentNavPage(page)
    await page.goto('/agents')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('button', { name: 'Agent Roles' })).toBeVisible({ timeout: 10000 })

    const rolesY =
      (await page.getByRole('button', { name: 'Agent Roles' }).boundingBox())?.y ?? 0
    const identitiesY =
      (await page.getByRole('button', { name: 'Agent Identities' }).boundingBox())?.y ?? 0
    const typesY =
      (await page.getByRole('button', { name: 'Agent Types' }).boundingBox())?.y ?? 0
    const executionsY =
      (await page.getByRole('button', { name: 'Agent Executions' }).boundingBox())?.y ?? 0
    const logsY =
      (await page.getByRole('button', { name: 'Agent Logs' }).boundingBox())?.y ?? 0

    // Roles → Identities → Types → Executions → Logs (top to bottom)
    expect(rolesY).toBeLessThan(identitiesY)
    expect(identitiesY).toBeLessThan(typesY)
    expect(typesY).toBeLessThan(executionsY)
    expect(executionsY).toBeLessThan(logsY)
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
