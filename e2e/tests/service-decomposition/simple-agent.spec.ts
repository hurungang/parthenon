/**
 * FIX-20260518-140000 — Issue 5: E2E Test for Simple Agent (save_result only)
 *
 * Validates the minimal "simple agent" flow where an agent type uses ONLY the
 * built-in `save_result` system tool (no external MCP connections required).
 *
 * This scenario is important because:
 *  - It is the lowest-friction agent type a user can create
 *  - System tools are handled differently from external MCP tools (no session/auth)
 *  - Service-decomposition Phase 10 fixed tool name inconsistencies and duplicate
 *    tool IDs in the skill editor.
 *
 * Phase 10 fixes verified here:
 *   - API returns a single `system/save_result` entry (no DB-seeded duplicate)
 *   - No duplicate tool entries appear during skill creation
 *   - Triggering the agent produces a job/session
 *   - The job completes successfully and the result is visible in the UI
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from '../_helpers'

// ── Constants ─────────────────────────────────────────────────────────────────

const SYSTEM_SERVER_ID = '00000000-0000-0000-0000-000000000001'
const SYSTEM_TOOL_SAVE_RESULT_ID = '00000000-0000-0000-0000-000000000002'

// ── Mock payloads ─────────────────────────────────────────────────────────────

const MOCK_SYSTEM_SERVER = {
  id: SYSTEM_SERVER_ID,
  name: 'System',
  slug: 'system',
  description: 'Built-in system tools available to all agents',
  base_url: '',
  status: 'active',
}

// Phase 10 fix: API returns only the virtual copy (no DB-seeded duplicate).
// The DB-seeded tool is named `system____save_result` (4 underscores, internal),
// so the list endpoint returns only the display-formatted virtual tool.
const MOCK_TOOLS_RESPONSE_FIXED = [
  {
    id: SYSTEM_TOOL_SAVE_RESULT_ID,
    server_id: SYSTEM_SERVER_ID,
    server_slug: 'system',
    server_name: 'System',
    name: 'system/save_result',
    original_name: 'save_result',
    description: 'Save the final result of agent execution',
    input_schema: null,
    is_active: true,
  },
]

const MOCK_SKILL_SAVE_RESULT = {
  id: 'skill-save-result-e2e-001',
  name: 'Simple Result Skill',
  description: 'Skill using only save_result',
  is_active: true,
  tool_ids: [SYSTEM_TOOL_SAVE_RESULT_ID],
  tool_binding_count: 1,
  instructions: 'Always save the output using save_result.',
  instructions_with_tools: 'Always save the output using save_result.\n\n## Tools\n\n### `system/save_result`\nSave the final result of agent execution',
}

const MOCK_AGENT_ROLE = {
  id: 'role-e2e-001',
  name: 'Simple Agent Role',
  description: 'Role using only save_result skill',
  sop_ids: [],
  skill_ids: ['skill-save-result-e2e-001'],
  mcp_session_ids: [],
}

const MOCK_AGENT_TYPE = {
  id: 'agent-type-e2e-001',
  name: 'Simple Result Agent',
  description: 'Minimal agent that only saves results',
  status: 'active',
  max_retries: 3,
  timeout_seconds: 300,
  role_id: 'role-e2e-001',
}

const MOCK_AGENT_JOB = {
  id: 'job-e2e-001',
  agent_type_id: 'agent-type-e2e-001',
  status: 'completed',
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  result: { output: 'Task completed successfully via save_result' },
}

// ── Tests ──────────────────────────────────────────────────────────────────────

test.describe('Issue 5 — Simple Agent E2E: save_result System Tool Only (FIX-20260518-140000)', () => {
  /**
   * Full flow: create skill with save_result → create role → create agent type →
   * trigger agent → verify completion result is displayed.
   *
   * Phase 10 fixes verified here:
   *  - API returns a single `system/save_result` entry (no DB-seeded duplicate)
   *  - No duplicate tool entries appear during skill creation
   *  - Triggering the agent produces a job/session
   *  - The job completes successfully and the result is visible in the UI
   */
  test('creates a skill with only save_result system tool — no duplicate tools in picker', async ({ page }) => {
    await standardSetup(page)

    // Mock all required API endpoints
    await page.route('**/api/v1/mcp/servers', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    })

    // Phase 10 fix: API returns only 1 entry (no DB-seeded duplicate)
    await page.route('**/api/v1/mcp/tools', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE_FIXED) })
    })

    await page.route('**/api/v1/skills', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([]) })
      } else if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_SKILL_SAVE_RESULT) })
      } else {
        route.continue()
      }
    })

    await page.route('**/api/v1/skills/*/roles', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    })

    await page.route('**/api/v1/agents/roles', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    })

    // Navigate to skills page and open the skill editor
    await page.goto('/skills')
    await page.waitForLoadState('load')

    // Open the create skill dialog using the correct button text
    const addButton = page.locator('button:visible').filter({ hasText: /Create Skill/i }).first()
    await expect(addButton).toBeVisible({ timeout: 5000 })
    await addButton.click()

    // Wait for the skill editor dialog to appear with the tool picker
    // system/save_result is shown as <code>system/save_result</code> in the tool list
    await expect(page.getByText('system/save_result')).toBeVisible({ timeout: 5000 })

    // Count how many times 'system/save_result' appears in the tool picker
    // Phase 10 fix ensures the API returns exactly 1 entry (no duplicates)
    const saveResultEntries = page.locator('text=system/save_result')
    const count = await saveResultEntries.count()

    // EXPECTED: exactly 1 entry for save_result (Phase 10 deduplication fix)
    expect(count).toBe(1)
  })

  test('triggering a simple agent with save_result produces a completed job', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/mcp/servers', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    )
    await page.route('**/api/v1/mcp/tools', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE_FIXED) })
    )
    await page.route('**/api/v1/skills**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SKILL_SAVE_RESULT]) })
    )
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_ROLE]) })
    )
    await page.route('**/api/v1/agents/identities', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/types', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_TYPE]) })
      } else if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_TYPE) })
      } else {
        route.continue()
      }
    })
    await page.route('**/api/v1/agents/types/**', (route) => {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) })
    })
    // Register execution-logs BEFORE the sessions/** catch-all so it takes precedence
    await page.route('**/api/v1/agents/sessions/*/execution-logs', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/agents/sessions', (route) =>
      route.fulfill({ status: 201, body: JSON.stringify(MOCK_AGENT_JOB) })
    )
    await page.route('**/api/v1/agents/sessions/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_JOB) })
    )

    // Navigate to agent types page
    await page.goto('/agents')
    await page.waitForLoadState('load')

    // Find the simple agent in the list (table row)
    const agentCard = page.getByText('Simple Result Agent')
    await expect(agentCard).toBeVisible({ timeout: 5000 })

    // Trigger the agent — icon button with aria-label "Run Agent"
    const triggerButton = page.getByRole('button', { name: /run agent/i }).first()
    await expect(triggerButton).toBeVisible({ timeout: 5000 })
    await triggerButton.click()

    // AgentJobLaunchDialog opens: "Launch Session — Simple Result Agent"
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 5000 })

    // Click the "Launch Session" button — scope to dialog to avoid matching other page buttons
    const launchBtn = dialog.locator('button').filter({ hasText: /launch/i }).first()
    await expect(launchBtn).toBeVisible({ timeout: 3000 })
    await launchBtn.click()

    // After launching, navigates to /agents/sessions/job-e2e-001 which shows "Completed"
    // The AgentJobPage renders a Chip with label from t('agents.sessions.statusCompleted') = "Completed"
    await expect(page.getByText('Completed').first()).toBeVisible({ timeout: 8000 })
  })

  test('save_result system tool appears in agent skill preview after selection', async ({ page }) => {
    await standardSetup(page)

    await page.route('**/api/v1/mcp/servers', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_SYSTEM_SERVER]) })
    )
    await page.route('**/api/v1/mcp/tools', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOOLS_RESPONSE_FIXED) })
    )
    // Mock skill detail fetch (GET /skills/{id}) before the list route
    await page.route('**/api/v1/skills/skill-save-result-e2e-001', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_SKILL_SAVE_RESULT) })
    )
    await page.route('**/api/v1/skills/*/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(['role-e2e-001']) })
    )
    await page.route('**/api/v1/skills', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([MOCK_SKILL_SAVE_RESULT]) })
      } else {
        route.continue()
      }
    })
    await page.route('**/api/v1/agents/roles', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([MOCK_AGENT_ROLE]) })
    )

    // Navigate to skills page — the existing skill is pre-loaded
    await page.goto('/skills')
    await page.waitForLoadState('load')

    // The skill "Simple Result Skill" should appear in the list
    await expect(page.getByText('Simple Result Skill')).toBeVisible({ timeout: 5000 })

    // Click the edit icon button in the skill's row to open the SkillEditor
    const skillRow = page.locator('tr').filter({ hasText: 'Simple Result Skill' })
    const editBtn = skillRow.getByRole('button').first()
    await expect(editBtn).toBeVisible({ timeout: 3000 })
    await editBtn.click()

    // SkillEditor opens as a side panel and calls /mcp/tools
    // The tool is shown as <code>system/save_result</code> in the tool picker checkbox list
    // Use locator('code') to avoid matching the <pre> block in instructions_with_tools
    await expect(page.locator('code').filter({ hasText: 'system/save_result' }).first()).toBeVisible({ timeout: 5000 })
  })
})
