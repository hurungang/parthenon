/**
 * Issue 5 — E2E test for a Simple Agent that uses ONLY the built-in
 * `save_data` system tool (no external MCP connections required).
 *
 * The legacy `save_result` system tool was REPLACED by `save_data`
 * (final results now go through typed `AgentOutput` records), so this spec
 * re-points the original assertions at the current tool:
 *
 * This scenario is important because:
 *  - It is the lowest-friction agent type a user can create
 *  - System tools are handled differently from external MCP tools (no session/auth)
 *  - Service-decomposition Phase 10 fixed tool name inconsistencies and duplicate
 *    tool IDs in the skill editor.
 *
 * Behaviour verified here:
 *  - The tool picker lists exactly one `system____save_data` entry (no duplicates)
 *  - A skill binding only that tool renders it in the bound-tools preview
 *  - Triggering the agent produces a session whose execution completes
 *
 * Note: `save_data` is exposed canonically as `system____save_data` (the wire
 * format `server____tool`); the harness renders it verbatim in the tool picker.
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from '../_helpers'

// ── Constants ─────────────────────────────────────────────────────────────────

const SYSTEM_SERVER_ID = '00000000-0000-0000-0000-000000000001'
const SYSTEM_TOOL_SAVE_DATA_ID = '00000000-0000-0000-0000-000000000002'
const SAVE_DATA_TOOL_NAME = 'system____save_data'

// ── Mock payloads ─────────────────────────────────────────────────────────────

const MOCK_SYSTEM_SERVER = {
  id: SYSTEM_SERVER_ID,
  name: 'System',
  slug: 'system',
  description: 'Built-in system tools available to all agents',
  base_url: '',
  status: 'active',
  oauth_config: null,
  last_synced_at: null,
  session_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

// The API returns only the virtual copy (no DB-seeded duplicate). The DB row is
// named `system____save_data` (4 underscores, internal wire format).
const MOCK_TOOLS_RESPONSE = [
  {
    id: SYSTEM_TOOL_SAVE_DATA_ID,
    server_id: SYSTEM_SERVER_ID,
    server_slug: 'system',
    server_name: 'system',
    name: SAVE_DATA_TOOL_NAME,
    original_name: 'save_data',
    description: 'Save named intermediate data during execution for later retrieval.',
    input_schema: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
]

const MOCK_SKILL_SAVE_DATA = {
  id: 'skill-save-data-e2e-001',
  name: 'simple-data-skill',
  description: 'Skill using only save_data',
  is_active: true,
  is_system: false,
  tool_ids: [SYSTEM_TOOL_SAVE_DATA_ID],
  tool_bindings: [
    {
      tool_id: SYSTEM_TOOL_SAVE_DATA_ID,
      name: SAVE_DATA_TOOL_NAME,
      original_name: 'save_data',
      server_slug: 'system',
      server_name: 'system',
    },
  ],
  instructions: 'Always persist intermediate data using save_data.',
  instructions_with_tools:
    'Always persist intermediate data using save_data.\n\n## Tools\n\n### `system____save_data`\nSave named intermediate data during execution for later retrieval.',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_AGENT_ROLE = {
  id: 'role-e2e-001',
  name: 'Simple Agent Role',
  description: 'Role using only the save_data skill',
  sop_ids: [],
  skill_ids: ['skill-save-data-e2e-001'],
  mcp_session_ids: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_AGENT_TYPE = {
  id: 'agent-type-e2e-001',
  name: 'Simple Data Agent',
  description: 'Minimal agent that only saves data',
  identity_id: null,
  role_id: 'role-e2e-001',
  model_id: null,
  system_instruction: null,
  input_type: 'none',
  input_schema: null,
  output_type: 'auto',
  output_schema: null,
  output_data_type_id: null,
  output_data_type_name: null,
  is_active: true,
  is_system: false,
  plan: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const MOCK_AGENT_JOB = {
  id: 'job-e2e-001',
  agent_type_id: 'agent-type-e2e-001',
  agent_type_name: 'Simple Data Agent',
  triggered_by_user_id: null,
  input_data: null,
  status: 'completed',
  started_at: '2026-01-01T00:00:00Z',
  completed_at: '2026-01-01T00:00:05Z',
  // `save_data` stores intermediate data; the final result is a typed output.
  output_data: { result: 'Task completed successfully via save_data' },
  error_message: null,
  conversation_history: null,
  created_at: '2026-01-01T00:00:00Z',
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('Issue 5 — Simple Agent E2E: save_data System Tool Only (FIX-20260518-140000)', () => {
  /**
   * Full flow: create skill with save_data → create role → create agent type →
   * trigger agent → verify completion.
   *
   * Historically this asserted `save_result`; the system tool was replaced by
   * `save_data`, so the picker now lists `system____save_data`.
   */
  test('creates a skill with only the save_data system tool — no duplicate tools in picker', async ({ page }) => {
    await standardSetup(page)

    // Mock all required API endpoints (paginated — hence the trailing `**`)
    await page.route('**/api/v1/mcp/servers**', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    })

    await page.route('**/api/v1/mcp/tools**', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE) })
    })

    await page.route('**/api/v1/skills**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([]) })
      } else if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_SKILL_SAVE_DATA) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify([]) })
      }
    })

    await page.route('**/api/v1/agents/roles', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    })

    // Navigate to skills page and open the skill editor
    await page.goto('/skills')
    await page.waitForLoadState('load')

    const addButton = page.getByRole('button', { name: 'Create Skill' }).first()
    await expect(addButton).toBeVisible({ timeout: 5000 })
    await addButton.click()

    // The editor opens on the Basic Info card; the picker lives behind "Select Tools"
    const editor = page.getByRole('dialog').filter({ hasText: 'Create Skill' })
    await expect(editor).toBeVisible({ timeout: 5000 })
    await editor.getByRole('button', { name: 'Select Tools' }).click()

    // Tool picker lists the canonical wire name in a <code> element
    const picker = page.getByRole('dialog').filter({ hasText: 'Select Tools' })
    await expect(picker).toBeVisible({ timeout: 5000 })

    const saveDataEntries = picker.locator('code').filter({ hasText: SAVE_DATA_TOOL_NAME })
    await expect(saveDataEntries.first()).toBeVisible({ timeout: 5000 })

    // Exactly 1 entry — the API returns no DB-seeded duplicate
    expect(await saveDataEntries.count()).toBe(1)
  })

  test('triggering a simple agent with save_data produces a completed job', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/mcp/servers**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    )
    await page.route('**/api/v1/mcp/tools**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE) })
    )
    await page.route('**/api/v1/skills**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SKILL_SAVE_DATA]) })
    )
    await page.route('**/api/v1/sops**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_ROLE]) })
    )
    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/types**', (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/optimized-plan')) {
        return route.fulfill({ status: 404, body: JSON.stringify({ detail: 'No optimized plan' }) })
      }
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_TYPE]) })
      }
      if (route.request().method() === 'POST') {
        return route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_TYPE) })
      }
      return route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) })
    })
    // Sessions: POST launches, every sub-resource returns its own real shape
    await page.route('**/api/v1/agents/sessions**', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_JOB) })
      }
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/logs') || path.endsWith('/execution-logs') || path.endsWith('/history')) {
        return route.fulfill({ status: 200, body: JSON.stringify([]) })
      }
      return route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_JOB) })
    })
    await page.route('**/api/v1/intervene/requests**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )

    // Navigate to agent types page
    await page.goto('/agents')
    await page.waitForLoadState('load')

    // Find the simple agent in the list (table row)
    const agentCard = page.getByText('Simple Data Agent')
    await expect(agentCard).toBeVisible({ timeout: 5000 })

    // Trigger the agent — icon button with aria-label "Run Agent"
    const triggerButton = page.getByRole('button', { name: /run agent/i }).first()
    await expect(triggerButton).toBeVisible({ timeout: 5000 })
    await triggerButton.click()

    // AgentJobLaunchDialog opens: "Launch Session — Simple Data Agent"
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Click the "Launch Session" button — scope to dialog to avoid matching other page buttons
    const launchBtn = dialog.locator('button').filter({ hasText: /launch/i }).first()
    await expect(launchBtn).toBeVisible({ timeout: 3000 })
    await launchBtn.click()

    // After launching, the workspace opens the Execution Details dialog for the
    // new session with a terminal `completed` status.
    await expect(page.getByText('Execution Details')).toBeVisible({ timeout: 8000 })
    await expect(page.getByRole('tab', { name: /result/i }).first()).toBeVisible({ timeout: 8000 })
    await expect(page.getByText(/Task completed successfully via save_data/)).toBeVisible({ timeout: 8000 })
  })

  test('save_data system tool appears in agent skill preview after selection', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/mcp/servers**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    )
    await page.route('**/api/v1/mcp/tools**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE) })
    )
    // Skill detail fetch (GET /skills/{id}) — must be registered after the list route
    await page.route('**/api/v1/skills**', (route) => {
      const path = new URL(route.request().url()).pathname
      if (path.endsWith('/roles')) {
        return route.fulfill({ status: 200, body: JSON.stringify(['role-e2e-001']) })
      }
      if (path.replace(/\/$/, '').endsWith('/skills/skill-save-data-e2e-001')) {
        return route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILL_SAVE_DATA) })
      }
      if (route.request().method() === 'GET') {
        return route.fulfill({ status: 200, body: JSON.stringify([MOCK_SKILL_SAVE_DATA]) })
      }
      return route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILL_SAVE_DATA) })
    })
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_ROLE]) })
    )

    // Navigate to skills page — the existing skill is pre-loaded
    await page.goto('/skills')
    await page.waitForLoadState('load')

    // The skill should appear in the list
    await expect(page.getByText(MOCK_SKILL_SAVE_DATA.name)).toBeVisible({ timeout: 5000 })

    // Open the read-only viewer in the skill's row (first action = View)
    const skillRow = page.locator('tr').filter({ hasText: MOCK_SKILL_SAVE_DATA.name })
    const viewBtn = skillRow.getByRole('button').first()
    await expect(viewBtn).toBeVisible({ timeout: 3000 })
    await viewBtn.click()

    // The Bound Tools preview lists the tool's bare name in <code> plus its
    // canonical wire name — the picker/API expose `system____save_data`.
    const editor = page.getByRole('dialog').filter({ hasText: 'View Skill' })
    await expect(editor).toBeVisible({ timeout: 5000 })
    await expect(editor.locator('code').filter({ hasText: 'save_data' }).first()).toBeVisible({ timeout: 5000 })
    await expect(editor.getByText(SAVE_DATA_TOOL_NAME, { exact: true })).toBeVisible({ timeout: 5000 })
  })
})
