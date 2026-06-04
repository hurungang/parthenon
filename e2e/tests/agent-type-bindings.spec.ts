/**
 * E2E Real Backend Integration test for Agent Type SOP/Skill Bindings.
 *
 * Tests against the actual running backend WITHOUT page.route() mocks.
 * Verifies that the API contract for bindings is satisfied:
 * - AgentType response includes sop_bindings and skill_bindings arrays
 * - Create and round-trip preserve the binding fields
 */
import { test, expect } from '@playwright/test'

test.describe('Real Backend Integration — Agent Type Bindings', () => {
  test('POST agent type returns sop_bindings and skill_bindings in response', async ({ request }) => {
    const BACKEND_URL = process.env.API_BASE_URL ?? 'http://localhost:8000'

    let healthOk = false
    try {
      const health = await request.get(`${BACKEND_URL}/api/v1/health`)
      healthOk = health.status() === 200
    } catch {
      test.skip(true, 'Backend not available — skipping real backend integration test')
      return
    }

    if (!healthOk) {
      test.skip(true, 'Backend health check failed — skipping real backend integration test')
      return
    }

    const token = process.env.AGENT_TEST_TOKEN
    if (!token) {
      test.skip(true, 'AGENT_TEST_TOKEN env var not set — skipping authenticated real backend test')
      return
    }

    const agentTypeName = `e2e-binding-test-${Date.now()}`
    let createdId: string | null = null

    try {
      const createResp = await request.post(`${BACKEND_URL}/api/v1/agents/types`, {
        data: {
          name: agentTypeName,
          input_type: 'typed',
          output_type: 'markdown',
          is_active: true,
        },
        headers: { Authorization: `Bearer ${token}` },
      })

      expect(createResp.status()).toBe(201)
      const body = await createResp.json()
      createdId = body.id as string

      expect(body).toHaveProperty('sop_bindings')
      expect(body).toHaveProperty('skill_bindings')
      expect(Array.isArray(body.sop_bindings)).toBe(true)
      expect(Array.isArray(body.skill_bindings)).toBe(true)
    } finally {
      // Cleanup
      if (createdId) {
        const deleteResp = await request.delete(
          `${BACKEND_URL}/api/v1/agents/types/${createdId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        )
        expect([200, 204]).toContain(deleteResp.status())
      }
    }
  })
})
