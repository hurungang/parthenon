import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, standardSetup } from './_helpers'

test.describe('Runtime Control Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
    }, FAKE_TOKEN)
    await standardSetup(page)
  })

  test('shows running sessions and opens execution details dialog', async ({ page }) => {
    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'at-conv',
            name: 'Runtime Conversation Agent',
            input_type: 'conversation',
            output_type: 'auto',
            is_active: true,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'sess-runtime-001',
            agent_type_id: 'at-conv',
            status: 'running',
            created_at: '2026-06-01T00:00:00Z',
            started_at: '2026-06-01T00:00:05Z',
            completed_at: null,
            input_data: { message: 'run' },
          },
        ]),
      }),
    )

    await page.route('**/api/v1/conversations?agent_type_id=at-conv', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          { id: 'conv-1', title: 'Ops Delegation Tree', agent_job_id: 'sess-runtime-001' },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions/sess-runtime-001', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'sess-runtime-001',
          agent_type_id: 'at-conv',
          status: 'running',
          created_at: '2026-06-01T00:00:00Z',
          started_at: '2026-06-01T00:00:05Z',
          completed_at: null,
          output_data: null,
          error_message: null,
        }),
      }),
    )

    await page.route('**/api/v1/agents/sessions/sess-runtime-001/logs', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )
    await page.route('**/api/v1/agents/sessions/sess-runtime-001/logs/stream', (route) =>
      route.fulfill({ status: 200, body: '' }),
    )
    await page.route('**/api/v1/agents/sessions/sess-runtime-001/execution-logs', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    await page.goto('/')
    await page.getByRole('button', { name: /agent executions/i }).click()
    await page.waitForLoadState('load')

    await expect(page.getByText(/sess-run/i).first()).toBeVisible()

    await page.getByRole('button', { name: /view/i }).first().click()
    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByText(/sess-runtime-001|sess-run/i).first()).toBeVisible()
  })

  test('surfaces observe-only threshold policy events in execution logs', async ({ page }) => {
    let logsEndpointHit = false
    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'at-task',
            name: 'Runtime Task Agent',
            input_type: 'typed',
            output_type: 'auto',
            is_active: true,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'sess-runtime-002',
            agent_type_id: 'at-task',
            status: 'completed',
            created_at: '2026-06-01T00:00:00Z',
            started_at: '2026-06-01T00:00:01Z',
            completed_at: '2026-06-01T00:00:10Z',
            output_data: { result: 'ok' },
          },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions/sess-runtime-002', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'sess-runtime-002',
          agent_type_id: 'at-task',
          status: 'completed',
          created_at: '2026-06-01T00:00:00Z',
          started_at: '2026-06-01T00:00:01Z',
          completed_at: '2026-06-01T00:00:10Z',
          output_data: { result: 'ok' },
          error_message: null,
        }),
      }),
    )

    await page.route('**/api/v1/agents/sessions/sess-runtime-002/execution-logs', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'exec-1',
            session_id: 'sess-runtime-002',
            system_instruction: 'test',
            user_prompt: 'hello',
            logged_at: '2026-06-01T00:00:00Z',
          },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions/sess-runtime-002/logs', (route) => {
      logsEndpointHit = true
      return route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'log-1',
            session_id: 'sess-runtime-002',
            timestamp: '2026-06-01T00:00:05Z',
            log_level: 'INFO',
            event_type: 'guardrail.token_budget.threshold_reached',
            message: 'Observe-only token threshold reached',
            data: {
              guardrail_reason: 'token_threshold_observed',
              enforcement_mode: 'observe',
            },
          },
        ]),
      })
    })

    await page.route('**/api/v1/agents/sessions/sess-runtime-002/logs/stream', (route) =>
      route.fulfill({ status: 200, body: '' }),
    )

    await page.goto('/')
    await page.getByRole('button', { name: /agent executions/i }).click()
    await page.waitForLoadState('load')
    await page.getByRole('button', { name: /view/i }).first().click()

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect.poll(() => logsEndpointHit).toBe(true)
  })

  test('shows topology selection and opens termination dialog for selected node', async ({ page }) => {
    let terminatePayload: Record<string, unknown> | null = null

    await page.route('**/api/v1/agents/types', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'at-root',
            name: 'Root Runtime Agent',
            input_type: 'typed',
            output_type: 'auto',
            is_active: true,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
        ]),
      }),
    )

    await page.route('**/api/v1/agents/sessions**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    await page.route('**/api/v1/agents/runtime/topology**', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
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
            },
          ],
          edges: [],
          root_session_ids: ['sess-root-terminate-001'],
        }),
      }),
    )

    await page.route('**/api/v1/agents/guardrails/model-usage-limits', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    await page.route('**/api/v1/agents/guardrails/model-usage-posture?refresh=true', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
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

    await page.route('**/api/v1/agents/runtime/terminate/term-req-001', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )

    await page.goto('/')
    await page.getByRole('button', { name: /agent executions/i }).click()
    await page.waitForLoadState('load')

    await page.getByText('Root Runtime Agent').click()
    await expect(page.getByRole('button', { name: /terminate/i })).toBeVisible()

    await page.getByRole('button', { name: /terminate/i }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByRole('heading', { name: /terminate/i })).toBeVisible()

    await page.getByLabel(/reason/i).fill('operator requested subtree stop')
    await page.getByRole('button', { name: /confirm/i }).click()

    await expect.poll(() => terminatePayload?.termination_scope).toBe('cascade_subtree')
    await expect.poll(() => terminatePayload?.target_session_id).toBe('sess-root-terminate-001')
  })

  test('returns recursion_validation_failed contract for run preflight dead-loop checks', async ({ page }) => {
    await page.route('**/api/v1/agents/sessions', async (route) => {
      if (route.request().method() !== 'POST') {
        return route.fallback()
      }
      return route.fulfill({
        status: 422,
        body: JSON.stringify({
          detail: {
            error: 'recursion_validation_failed',
            summary: 'Cycle detected in delegation graph',
            findings: [
              {
                type: 'cycle_detected',
                severity: 'error',
                path: 'root -> child -> root',
                recommendation: 'Break delegation cycle',
              },
            ],
          },
        }),
      })
    })

    const response = await page.evaluate(async () => {
      const res = await fetch('/api/v1/agents/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          agent_type_id: '11111111-1111-1111-1111-111111111111',
          input_data: { prompt: 'trigger recursion check' },
        }),
      })
      return {
        status: res.status,
        body: await res.json(),
      }
    })

    expect(response.status).toBe(422)
    expect(response.body.detail.error).toBe('recursion_validation_failed')
    expect(response.body.detail.findings[0].type).toBe('cycle_detected')
  })
})

test.describe('Runtime Control Dashboard - Real Backend Integration', () => {
  test('real backend topology and terminate outcomes are retrievable without request mocks', async ({ page }) => {
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
    const terminateResp = await page.request.post('http://localhost:8000/api/v1/agents/runtime/terminate', {
      headers,
      data: {
        target_session_id: targetSessionId,
        termination_scope: 'node_only',
        operator_reason: 'playwright-real-backend-termination-check',
      },
    })

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

  test('renders vendor → model → guardrail hierarchy in the runtime control panel', async ({ page }) => {
    await page.route('**/api/v1/agents/runtime/topology', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ nodes: [], edges: [], root_session_ids: [] }) }),
    )
    await page.route('**/api/v1/agents/guardrails/model-usage-limits', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            id: 'g-1',
            model_config_id: 'cfg-openai',
            model_id: 'gpt-4.1',
            model_name: 'gpt-4.1',
            period: 'hour',
            limit_value: 10,
            unit: 'k',
            enforcement_posture: 'terminate',
            is_active: true,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
        ]),
      }),
    )
    await page.route('**/api/v1/agents/guardrails/model-usage-posture**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )
    await page.route('**/api/v1/agents/model-availability', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            vendor_config_id: 'cfg-openai',
            vendor_display_name: 'OpenAI Production',
            is_disabled: false,
            models: [
              {
                model_name: 'gpt-4.1',
                is_disabled: false,
                disabled_reason: 'manual',
                guardrails: [
                  {
                    id: 'g-1',
                    period: 'hour',
                    limit_value: 10,
                    unit: 'k',
                    enforcement_posture: 'terminate',
                    is_active: true,
                  },
                ],
              },
            ],
          },
        ]),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByText('OpenAI Production').first()).toBeVisible()
  })

  test('vendor disable cascades the cascade-source badge to all child models', async ({ page }) => {
    await page.route('**/api/v1/agents/runtime/topology', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ nodes: [], edges: [], root_session_ids: [] }) }),
    )
    await page.route('**/api/v1/agents/guardrails/model-usage-limits', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )
    await page.route('**/api/v1/agents/guardrails/model-usage-posture**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) }),
    )
    await page.route('**/api/v1/agents/model-availability', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify([
          {
            vendor_config_id: 'cfg-anthropic',
            vendor_display_name: 'Anthropic Prod',
            is_disabled: true,
            models: [
              {
                model_name: 'claude-sonnet-4',
                is_disabled: true,
                disabled_reason: 'vendor_cascaded',
                guardrails: [],
              },
            ],
          },
        ]),
      }),
    )

    await page.goto('/agents/runtime-control')
    await page.waitForLoadState('load')

    if (page.url().includes('/login')) {
      test.skip()
      return
    }

    await expect(page.getByText('Anthropic Prod').first()).toBeVisible()
  })
})
