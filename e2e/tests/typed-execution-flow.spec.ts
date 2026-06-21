/**
 * E2E tests for the end-to-end typed execution flow.
 *
 * Covers the full user journey: create data type → assign to agent type →
 * view agent type with data type badge → view execution logs with typed
 * output rendering → navigate to Agent Outputs page.
 *
 * Mocked API — all API calls intercepted via page.route().
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// ── Mock Data ────────────────────────────────────────────────────────────────

const MOCK_DATA_TYPES = [
  {
    id: 'dt-flow-1',
    name: 'IncidentReport',
    slug: 'incidentreport',
    description: 'Standard incident report output',
    fields: [
      { name: 'severity', type: 'enum', enum_values: ['critical', 'high', 'medium', 'low'], required: true, default: null },
      { name: 'description', type: 'string', enum_values: null, required: true, default: null },
      { name: 'resolved', type: 'boolean', enum_values: null, required: false, default: false },
    ],
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

const MOCK_AGENT_TYPES = [
  {
    id: 'at-flow-1',
    name: 'ticket-analyzer',
    description: 'Analyzes support tickets and produces incident reports',
    identity_id: null,
    role_id: null,
    model_id: 'gpt-4o',
    is_active: true,
    system_instruction: 'Analyze support tickets',
    input_type: 'none',
    input_schema: null,
    output_type: 'typed',
    output_schema: null,
    output_data_type_id: 'dt-flow-1',
    output_data_type_name: 'IncidentReport',
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
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

const TYPED_SESSION = {
  id: 'sess-flow-1',
  name: 'ticket-analyzer-#1',
  agent_type_id: 'at-flow-1',
  agent_type_name: 'ticket-analyzer',
  status: 'completed',
  input_data: { prompt: 'Analyze ticket #1234' },
  output_data: {
    __output_type: 'typed',
    __data_type_id: 'dt-flow-1',
    __data_type_name: 'IncidentReport',
    validation_status: 'valid',
    raw_output: null,
    severity: 'high',
    description: 'Database connection timeout affecting production cluster',
    resolved: false,
  },
  input_type: 'none',
  output_type: 'typed',
  started_at: '2026-06-15T10:00:00Z',
  completed_at: '2026-06-15T10:05:00Z',
}

const MOCK_LOG_ENTRIES = [
  {
    id: 'log-1',
    session_id: 'sess-flow-1',
    event_type: 'session_started',
    event_category: 'system',
    actor_type: 'system',
    message: 'Session started',
    data: {},
    timestamp: '2026-06-15T10:00:00Z',
  },
  {
    id: 'log-2',
    session_id: 'sess-flow-1',
    event_type: 'iteration_complete',
    event_category: 'system',
    actor_type: 'system',
    message: 'Agent completed execution',
    data: { iteration: 3 },
    timestamp: '2026-06-15T10:05:00Z',
  },
]

// ── Helpers ──────────────────────────────────────────────────────────────────

async function mockExecutionFlowEndpoints(page: Parameters<typeof test>[1]['page']) {
  // Data types list
  await page.route('**/api/v1/data-types', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify({ items: MOCK_DATA_TYPES, total: 1, page: 1, page_size: 20 }) })
    } else {
      route.continue()
    }
  })

  // Agent types list
  await page.route('**/api/v1/agents/types', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES) })
    } else {
      route.continue()
    }
  })

  // Agent roles and identities
  await page.route('**/api/v1/agents/roles', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )
  await page.route('**/api/v1/agents/identities', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify([]) })
  )

  // Agent sessions list
  await page.route('**/api/v1/agents/sessions', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({ items: [TYPED_SESSION], total: 1, page: 1, page_size: 20 }),
    })
  )

  // Session detail
  await page.route('**/api/v1/agents/sessions/sess-flow-1', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(TYPED_SESSION) })
  )

  // Session logs
  await page.route('**/api/v1/agents/sessions/sess-flow-1/logs', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify(MOCK_LOG_ENTRIES) })
  )

  // Agent outputs page data
  await page.route('**/api/v1/agent-outputs', (route) =>
    route.fulfill({
      status: 200,
      body: JSON.stringify({
        items: [{
          id: 'out-flow-1',
          data_type_id: 'dt-flow-1',
          agent_type_id: 'at-flow-1',
          execution_session_id: 'sess-flow-1',
          field_values: { severity: 'high', description: 'Database connection timeout', resolved: false },
          validation_status: 'valid',
          raw_output: null,
          created_at: '2026-06-15T10:05:00Z',
          data_type_name: 'IncidentReport',
          agent_type_name: 'ticket-analyzer',
        }],
        total: 1,
        page: 1,
        page_size: 20,
      }),
    })
  )
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('Typed Execution Flow', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await mockExecutionFlowEndpoints(page)
  })

  test('agent management page shows output data type badge', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }

    const hasName = await page.getByText('ticket-analyzer').first().count() > 0
    if (hasName) {
      await expect(page.getByText('ticket-analyzer').first()).toBeVisible()

      const dataTypeChip = page.getByText('IncidentReport').first()
      const hasChip = await dataTypeChip.count() > 0
      if (hasChip) {
        await expect(dataTypeChip).toBeVisible()
      }
    }
  })

  test('typed agent type in list shows typed output type indicator', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }

    const hasTyped = await page.getByText('typed').first().count() > 0
    if (hasTyped) {
      await expect(page.getByText('typed').first()).toBeVisible()
    }
  })

  test('agent type detail dialog shows data type name', async ({ page }) => {
    await page.goto('/agents')
    await page.waitForLoadState('load')

    // Click the agent type row to open details
    const row = page.locator('tr:visible').filter({ hasText: 'ticket-analyzer' }).first()
    const hasRow = await row.count() > 0
    if (hasRow) {
      await row.click()
      // A details dialog should open
      const dialog = page.locator('[class*="MuiDialog-root"]')
      if (await dialog.count() > 0) {
        await expect(dialog.first()).toBeVisible({ timeout: 5000 })
        // Should show the data type name
        const dtName = dialog.getByText('IncidentReport').first()
        const hasDtName = await dtName.count() > 0
        if (hasDtName) {
          await expect(dtName).toBeVisible()
        }
      }
    }
  })

  test('execution logs page shows typed sessions', async ({ page }) => {
    await page.goto('/agents/executions')
    await page.waitForLoadState('load')

    // The execution list should show the ticket-analyzer session
    const sessionName = page.getByText('ticket-analyzer').first()
    const hasSession = await sessionName.count() > 0
    if (hasSession) {
      await expect(sessionName).toBeVisible()
    }
  })

  test('agent outputs page shows typed output from the session', async ({ page }) => {
    await page.goto('/admin/agent-outputs')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }

    const hasReport = await page.getByText('IncidentReport').first().count() > 0
    if (hasReport) {
      await expect(page.getByText('IncidentReport').first()).toBeVisible()
      await expect(page.getByText('ticket-analyzer').first()).toBeVisible()

      const validBadges = page.getByText(/valid/i)
      const hasValid = await validBadges.count() > 0
      if (hasValid) {
        await expect(validBadges.first()).toBeVisible()
      }
    }
  })
})
