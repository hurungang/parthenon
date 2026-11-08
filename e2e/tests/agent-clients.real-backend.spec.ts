import { test, expect } from '@playwright/test'

/**
 * Real-backend integration test for third-party agent clients.
 *
 * Required by the change-lifecycle DB-change policy: at least one E2E variant
 * must hit the REAL backend (no mocks) to catch migration issues that mocked
 * tests miss. Skipped unless REAL_API_TOKEN (+ REAL_AGENT_TYPE_ID) are provided
 * and a live backend is reachable.
 */
const API = process.env.REAL_API_BASE_URL || 'http://localhost:8000/api/v1'
const TOKEN = process.env.REAL_API_TOKEN
const AGENT_TYPE_ID = process.env.REAL_AGENT_TYPE_ID

test.describe('Real Backend Integration - third-party-agent-integration', () => {
  test.skip(!TOKEN, 'Requires REAL_API_TOKEN and a running backend')
  test.skip(!AGENT_TYPE_ID, 'Requires REAL_AGENT_TYPE_ID')

  test('client CRUD round-trips against the real database', async ({ request }) => {
    const name = `e2e-client-${Date.now()}`

    // Create a secret client for an existing agent type.
    const create = await request.post(`${API}/clients`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
      data: { name, agent_type_id: AGENT_TYPE_ID, key_type: 'secret' },
    })
    expect(create.ok(), `create failed: ${create.status()} ${await create.text()}`).toBeTruthy()
    const created = await create.json()
    expect(created.client_key).toMatch(/^phn_cl_sk_/)
    expect(created.id).toBeTruthy()

    // It appears in the list.
    const list = await request.get(`${API}/clients?agent_type_id=${AGENT_TYPE_ID}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })
    expect(list.ok()).toBeTruthy()
    const items = await list.json()
    expect(items.some((c: { id: string }) => c.id === created.id)).toBeTruthy()

    // Revoke it (cleanup) and confirm it is gone from the active set.
    const revoke = await request.delete(`${API}/clients/${created.id}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })
    expect(revoke.ok()).toBeTruthy()
  })
})
