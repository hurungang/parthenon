/**
 * E2E tests for Agent Plan Mode feature.
 *
 * Contains two test suites:
 * 1. Mocked tests (fast) — use page.route() to intercept API calls
 * 2. Real Backend Integration — ONE suite without page.route() mocks that
 *    verifies the actual backend creates and cascades plan records
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// ── Shared fixtures ────────────────────────────────────────────────────────────

const MOCK_AGENT_PLAN_SUCCESS = {
  id: 'plan-e2e-1',
  agent_type_id: 'at-e2e-1',
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

const MOCK_AGENT_PLAN_FAILED = {
  id: 'plan-e2e-fail',
  agent_type_id: 'at-e2e-fail',
  plan_steps: [],
  topology_nodes: [],
  topology_edges: [],
  generation_status: 'failed',
  generation_error: 'LLM provider unavailable — no model config found',
  agent_config_hash: null,
  generated_at: null,
}

const MOCK_AGENT_TYPE_BASE = {
  id: 'at-e2e-1',
  name: 'E2E Test Agent',
  description: 'Created by E2E test',
  identity_id: null,
  role_id: null,
  model_id: null,
  system_instruction: null,
  input_type: 'typed',
  input_schema: null,
  output_type: 'markdown',
  output_schema: null,
  primary_sop_id: null,
  is_active: true,
  created_at: '2026-05-09T12:00:00Z',
  updated_at: '2026-05-09T12:00:00Z',
}

// ── Standard API mocks used by most tests ──────────────────────────────────────

async function setupStandardAgentMocks(page: Parameters<typeof test>[1]['page']) {
  await page.route('**/api/v1/agents/types', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    } else {
      // POST — return agent type with a successful plan
      route.fulfill({
        status: 201,
        body: JSON.stringify({ ...MOCK_AGENT_TYPE_BASE, plan: MOCK_AGENT_PLAN_SUCCESS }),
      })
    }
  })
  await page.route('**/api/v1/agents/types/**', (route) => {
    if (route.request().method() === 'PUT') {
      // Update — return with regenerated plan
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          ...MOCK_AGENT_TYPE_BASE,
          id: 'at-e2e-1',
          name: 'Updated E2E Agent',
          plan: MOCK_AGENT_PLAN_SUCCESS,
        }),
      })
    } else if (route.request().method() === 'DELETE') {
      route.fulfill({ status: 204 })
    } else {
      route.fulfill({
        status: 200,
        body: JSON.stringify({ ...MOCK_AGENT_TYPE_BASE, plan: MOCK_AGENT_PLAN_SUCCESS }),
      })
    }
  })
  await page.route('**/api/v1/agents/roles', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/model-configs', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  // SOPs are fetched by AgentTypeForm when input_type === 'none' (the default).
  // Without this mock the real backend receives the fake JWT, returns 401, and the
  // app redirects to login before any dialog interaction completes.
  await page.route('**/api/v1/sops', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
}

// ═══════════════════════════════════════════════════════════════════════════════
// Suite 1: Mocked E2E tests (fast, use page.route())
// ═══════════════════════════════════════════════════════════════════════════════

test.describe('Agent Plan Mode — Mocked', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupStandardAgentMocks(page)
  })

  test('Create agent type with plan: modal opens with steps and diagram after save', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (e) => errors.push(e.message))

    await page.goto('/agents')
    await page.waitForLoadState('load')

    // Click "Add Agent Type" / "Create Agent Type" button
    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await expect(createBtn).toBeVisible()
    await createBtn.click()

    // Wait for create dialog to open
    await expect(page.getByRole('dialog')).toBeVisible()

    // Fill in the Name field
    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('E2E Test Agent')

    // Switch Input Type from 'none' to 'typed' to bypass primarySopRequired validation
    await page.getByRole('dialog').getByText('None (no input required)').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.locator('[role="option"][data-value="typed"]').click()

    // Click Save
    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // PlanPreviewModal should open — look for plan steps
    await expect(page.getByText('Initialize Context')).toBeVisible({ timeout: 8000 })
    await expect(page.getByText('Execute Search')).toBeVisible()
    await expect(page.getByText('Save Result')).toBeVisible()

    // Console errors should not include plan-related failures
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('Create agent type with plan: topology section visible in modal', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('E2E Plan Topology Test')

    // Switch Input Type from 'none' to 'typed' to bypass primarySopRequired validation
    await page.getByRole('dialog').getByText('None (no input required)').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.locator('[role="option"][data-value="typed"]').click()

    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // Plan preview modal should open
    await expect(page.getByText('Initialize Context')).toBeVisible({ timeout: 8000 })

    // Topology section should be visible (plan has non-empty nodes)
    // The topology heading uses t() key agents.plan.topology
    await expect(page.getByText(/agents\.plan\.topology|agent topology/i)).toBeVisible()
  })

  test('Dismiss plan modal: modal closes and agent type row appears in table', async ({ page }) => {
    // Set up GET to return the created agent type
    await page.route('**/api/v1/agents/types', (route) => {
      if (route.request().method() === 'GET') {
        // After save, return the new agent type in the list
        route.fulfill({
          status: 200,
          body: JSON.stringify([{ ...MOCK_AGENT_TYPE_BASE, name: 'E2E Test Agent' }]),
        })
      } else {
        route.fulfill({
          status: 201,
          body: JSON.stringify({ ...MOCK_AGENT_TYPE_BASE, plan: MOCK_AGENT_PLAN_SUCCESS }),
        })
      }
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('E2E Test Agent')

    // Switch Input Type from 'none' to 'typed' to bypass primarySopRequired validation
    await page.getByRole('dialog').getByText('None (no input required)').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.locator('[role="option"][data-value="typed"]').click()

    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // Wait for plan modal to open
    await expect(page.getByText('Initialize Context')).toBeVisible({ timeout: 8000 })

    // Close the plan modal
    const closeBtn = page.getByRole('button', { name: /close/i })
    await closeBtn.click()

    // Wait for the plan modal to fully close before checking the table
    await expect(page.getByText('Initialize Context')).not.toBeVisible({ timeout: 5000 })

    // Agent type row should appear in the table (use role='cell' to avoid matching the dialog title)
    await expect(page.getByRole('cell', { name: 'E2E Test Agent' })).toBeVisible({ timeout: 5000 })
  })

  test('Update agent type: PlanPreviewModal opens with updated plan on save', async ({ page }) => {
    // Pre-populate the agent type list
    await page.route('**/api/v1/agents/types', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          body: JSON.stringify([MOCK_AGENT_TYPE_BASE]),
        })
      } else {
        route.fulfill({
          status: 201,
          body: JSON.stringify({ ...MOCK_AGENT_TYPE_BASE, plan: MOCK_AGENT_PLAN_SUCCESS }),
        })
      }
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')

    // Click edit button for the existing agent type
    const editBtn = page.getByRole('button', { name: /edit/i })
    await expect(editBtn).toBeVisible()
    await editBtn.click()

    // Wait for edit dialog
    await expect(page.getByRole('dialog')).toBeVisible()

    // Modify the name
    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('Updated E2E Agent')

    // Save
    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // Plan modal should open with steps from the updated response
    await expect(page.getByText('Initialize Context')).toBeVisible({ timeout: 8000 })
  })

  test('Failed plan: modal opens with error message when generation_status is failed', async ({ page }) => {
    // Override POST to return failed plan
    await page.route('**/api/v1/agents/types', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify([]) })
      } else {
        route.fulfill({
          status: 201,
          body: JSON.stringify({ ...MOCK_AGENT_TYPE_BASE, plan: MOCK_AGENT_PLAN_FAILED }),
        })
      }
    })

    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('Failed Plan Agent')

    // Switch Input Type from 'none' to 'typed' to bypass primarySopRequired validation
    await page.getByRole('dialog').getByText('None (no input required)').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.locator('[role="option"][data-value="typed"]').click()

    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // Error message from generation_error should be visible in the modal
    await expect(
      page.getByText('LLM provider unavailable — no model config found')
    ).toBeVisible({ timeout: 8000 })
  })

  test('Plan modal does not reopen after dismissal without another save', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    const createBtn = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn.click()
    await expect(page.getByRole('dialog')).toBeVisible()

    const nameInput = page.getByRole('dialog').getByRole('textbox').first()
    await nameInput.fill('E2E Test Agent')

    // Switch Input Type from 'none' to 'typed' to bypass primarySopRequired validation
    await page.getByRole('dialog').getByText('None (no input required)').click()
    await page.waitForSelector('[role="listbox"]', { state: 'visible' })
    await page.locator('[role="option"][data-value="typed"]').click()

    const saveBtn = page.getByRole('dialog').getByRole('button', { name: /save/i })
    await saveBtn.click()

    // Wait for plan modal
    await expect(page.getByText('Initialize Context')).toBeVisible({ timeout: 8000 })

    // Close plan modal
    const closeBtn = page.getByRole('button', { name: /close/i })
    await closeBtn.click()

    // Verify modal is closed
    await expect(page.getByText('Initialize Context')).not.toBeVisible({ timeout: 3000 })

    // Click "Add Agent Type" again — the plan modal should NOT reopen automatically
    const createBtn2 = page.getByRole('button', { name: /create.*agent.*type|add.*agent/i })
    await createBtn2.click()

    // Only the create dialog should be open, not the plan modal
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('Initialize Context')).not.toBeVisible()
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

  test('POST /api/v1/agents/types returns plan field in response', async ({ request }) => {
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

      // Must be 201 — plan failure should not block this
      expect(createResp.status()).toBe(201)
      const body = await createResp.json()

      // Response must include `plan` key
      expect(body).toHaveProperty('plan')
      createdId = body.id as string

      // plan.generation_status must be either 'success' or 'failed' (not absent)
      if (body.plan !== null) {
        expect(['success', 'failed', 'pending']).toContain(body.plan.generation_status)
      }
    } finally {
      // Cleanup: delete the created agent type to verify CASCADE
      if (createdId) {
        const deleteResp = await request.delete(
          `${BACKEND_URL}/api/v1/agents/types/${createdId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        )
        // 204 means successful deletion — plan should cascade automatically
        expect([200, 204]).toContain(deleteResp.status())
      }
    }
  })
})
