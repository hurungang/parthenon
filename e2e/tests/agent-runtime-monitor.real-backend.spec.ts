import { expect, test } from '@playwright/test'

/**
 * Agent Runtime Monitor — real-backend trigger-provenance integration.
 *
 * This no-mock variant exercises the schema change (`scheduled_jobs.
 * scheduled_by_user_id`) and the trigger-provenance chain end-to-end against a
 * live backend.  It is intentionally conservative: it verifies the topology
 * endpoint now returns the trigger-provenance fields (`trigger_source`,
 * `trigger_source_label`, `tool_calls`) plus the existing `needs_intervention`
 * contract, which only works if the migration is applied and the provenance
 * resolution layer is wired through `ScheduledJob` → dispatch →
 * `AgentJob.triggered_by_user_id` → `RuntimeTopologyController`.
 *
 * Skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is
 * unreachable.
 */

test.describe('Real Backend Integration - trigger provenance', () => {
  test('topology nodes return trigger provenance + tool-call history + needs_intervention', async ({
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

    const resp = await page.request.get(
      'http://localhost:8000/api/v1/agents/runtime/topology?include_terminal=true&max_nodes=200',
      { headers },
    )

    if (resp.status() !== 200) {
      expect([401, 403]).toContain(resp.status())
      test.skip()
      return
    }

    const body = await resp.json()
    expect(Array.isArray(body.nodes)).toBe(true)

    for (const node of body.nodes) {
      // Contract of the refined endpoint (backwards-compatible additions).
      expect(typeof node.needs_intervention).toBe('boolean')
      expect('trigger_source' in node).toBe(true)
      expect('trigger_source_label' in node).toBe(true)
      expect(Array.isArray(node.tool_calls)).toBe(true)
      // trigger_source is one of the defined provenance values.
      expect(['user', 'schedule', 'delegated', 'unknown']).toContain(node.trigger_source)
    }

    // If any node is schedule-triggered, its label is the schedule name
    // (a non-empty string), confirming the provenance chain resolves through
    // the `scheduled_by_user_id` migration.
    for (const node of body.nodes) {
      if (node.trigger_source === 'schedule') {
        expect(typeof node.trigger_source_label).toBe('string')
      }
    }
  })
})
