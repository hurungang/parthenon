import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Agent Runtime Monitor — E2E.
 *
 * The runtime-control "agent topology" view was rebranded to "Agent Runtime
 * Monitor" and replaced with the interactive `AgentRuntimeMapCanvas`.  The
 * model guardrail panel was removed from this page entirely.
 *
 * Mock-first: `page.route()` mocks isolate the UI from the backend.  One
 * real-backend smoke variant is retained at the bottom.
 */

// The Vite dev/preview server compiles the route on first hit; under load this
// can exceed Playwright's 30s default. Give the map page generous headroom.
test.describe.configure({ timeout: 90_000 })

const MOCK_AGENT_TYPE = {
  id: 'at-root',
  name: 'Root Runtime Agent',
  input_type: 'typed',
  output_type: 'auto',
  is_active: true,
  guardrail_max_iterations: 25,
  guardrail_max_delegation_depth: 3,
  guardrail_token_budget: 100000,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

const MOCK_TOPOLOGY_SINGLE_NODE = {
  nodes: [
    {
      session_id: 'sess-root-terminate-001',
      agent_type_id: 'at-root',
      agent_type_name: 'Root Runtime Agent',
      status: 'running',
      depth_from_root: 0,
      parent_session_id: null,
      started_at: '2026-06-01T00:00:02Z',
      created_at: '2026-06-01T00:00:00Z',
      termination_category: null,
      kind: 'agent',
      needs_intervention: false,
    },
  ],
  edges: [],
  root_session_ids: ['sess-root-terminate-001'],
}

test.describe('Agent Runtime Monitor', () => {
  test.beforeEach(async ({ page }) => {
    // Lowest-priority catch-all FIRST (Playwright resolves handlers
    // last-registered-first) so standardSetup + test mocks always win.
    await mockApiCatchAllProxyAware(page)
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
  })

  test('presents the view as "Agent Runtime Monitor" and renders the map canvas', async ({
    page,
  }) => {
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOPOLOGY_SINGLE_NODE) }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    // Renamed page title (h4) — the heading appears as "Agent Runtime Monitor".
    await expect(
      page.getByRole('heading', { name: 'Agent Runtime Monitor' }).first(),
    ).toBeVisible()

    // The interactive map canvas is the primary view.
    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()
  })

  test('does not render the model guardrail panel', async ({ page }) => {
    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOPOLOGY_SINGLE_NODE) }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    // The guardrail panel (and its summary) are no longer on this page.
    await expect(page.getByTestId('agent-runtime-map-canvas')).toBeVisible()
    await expect(page.getByTestId('vendor-model-guardrail-panel')).toHaveCount(0)
    await expect(page.getByTestId('guardrail-dashboard-summary')).toHaveCount(0)
  })

  test('selects a node and opens the termination dialog from the detail bubble', async ({
    page,
  }) => {
    let terminatePayload: Record<string, unknown> | null = null

    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_TOPOLOGY_SINGLE_NODE) }),
    )
    await page.route('**/api/v1/agents/types/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPE) }),
    )
    await page.route('**/api/v1/agents/runtime/terminate', async (route) => {
      terminatePayload = (await route.request().postDataJSON()) as Record<string, unknown>
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'term-req-001',
          requested_by_user_id: '00000000-0000-0000-0000-000000000001',
          target_agent_job_id: 'sess-root-terminate-001',
          termination_scope: 'cascade_subtree',
          permission_evaluation_outcome: 'allowed',
          permission_evaluation_reason: 'test terminate',
          request_status: 'completed',
          requested_at: '2026-06-01T00:00:00Z',
          completed_at: '2026-06-01T00:00:01Z',
        }),
      })
    })
    await page.route('**/api/v1/agents/runtime/terminate/**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    // Select the node tile (role="button" on the map).
    await page.getByRole('button', { name: /Root Runtime Agent/ }).click()

    // Detail bubble appears beside the node with a terminate action.
    await expect(page.getByTestId('agent-detail-bubble')).toBeVisible()
    await page.getByTestId('terminate-node-button').click()

    // Termination dialog opens (reused NodeTerminationDialog).
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(
      page.getByRole('heading', { name: 'Terminate Runtime Node' }),
    ).toBeVisible()

    await page.getByLabel(/operator reason/i).fill('operator requested subtree stop')
    await page.getByRole('button', { name: /confirm termination/i }).click()

    await expect.poll(() => terminatePayload?.termination_scope).toBe('cascade_subtree')
    await expect
      .poll(() => terminatePayload?.target_session_id)
      .toBe('sess-root-terminate-001')
  })
})

test.describe('Agent Runtime Monitor - Real Backend Integration', () => {
  test('real backend topology and terminate outcomes are retrievable without request mocks', async ({
    page,
  }) => {
    const realToken = process.env.E2E_REAL_BACKEND_TOKEN
    if (!realToken) {
      test.skip()
      return
    }

    let healthStatus = 0
    try {
      const health = await page.request.get('http://localhost:8000/api/v1/health')
      healthStatus = health.status()
    } catch {
      healthStatus = 0
    }

    if (healthStatus === 0) {
      test.skip()
      return
    }

    const headers = { Authorization: `Bearer ${realToken}` }

    const topologyResp = await page.request.get(
      'http://localhost:8000/api/v1/agents/runtime/topology?include_terminal=true&max_nodes=200',
      { headers },
    )

    if (topologyResp.status() !== 200) {
      expect([401, 403]).toContain(topologyResp.status())
      test.skip()
      return
    }

    const topologyBody = await topologyResp.json()
    expect(Array.isArray(topologyBody.nodes)).toBe(true)

    if (!topologyBody.nodes.length) {
      test.skip()
      return
    }

    const targetSessionId = topologyBody.nodes[0].session_id
    const terminateResp = await page.request.post(
      'http://localhost:8000/api/v1/agents/runtime/terminate',
      {
        headers,
        data: {
          target_session_id: targetSessionId,
          termination_scope: 'node_only',
          operator_reason: 'playwright-real-backend-termination-check',
        },
      },
    )

    expect([200, 403, 404]).toContain(terminateResp.status())

    if (terminateResp.status() === 200) {
      const terminateBody = await terminateResp.json()
      const requestId = terminateBody.id
      expect(requestId).toBeTruthy()

      const outcomesResp = await page.request.get(
        `http://localhost:8000/api/v1/agents/runtime/terminate/${requestId}`,
        { headers },
      )
      expect(outcomesResp.status()).toBe(200)
      const outcomesBody = await outcomesResp.json()
      expect(Array.isArray(outcomesBody)).toBe(true)
    }

    const policyResp = await page.request.get(
      `http://localhost:8000/api/v1/agents/runtime/policy-events?session_id=${targetSessionId}&limit=50`,
      { headers },
    )
    expect([200, 403]).toContain(policyResp.status())
  })
})
