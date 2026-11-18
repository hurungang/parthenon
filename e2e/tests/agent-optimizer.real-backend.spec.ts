import { expect, test, type APIRequestContext, type APIResponse } from '@playwright/test'

/**
 * Real-backend integration for the conversational optimizer.
 *
 * MANDATORY for this change: `optimizer-conversational-agent` has DB schema
 * changes (`optimization_live_tests` + the enum + the nullable
 * `runtime_tool_calls.optimization_live_test_request_id`), so one E2E variant
 * must hit the REAL stack with no `page.route()` mocks — an unapplied migration
 * must surface here instead of being hidden by mocks
 * (`docs/master/qa/testing-strategy.md`).
 *
 * Skips honestly when the stack/token are unavailable, but NEVER tolerates a 5xx
 * on the new endpoints: that is the unapplied-migration signal (see the change's
 * Edge Cases: "an unapplied migration surfaces as a 500 on conversation/ledger
 * endpoints — the real-backend E2E variant must fail loudly on that, not skip").
 */

const API = process.env.REAL_API_BASE_URL || 'http://localhost:8000/api/v1'
const TOKEN =
  process.env.REAL_API_TOKEN || process.env.AGENT_TEST_TOKEN || process.env.E2E_TEST_TOKEN || ''

function authHeaders() {
  return { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
}

/** Fails loudly on any 5xx (unapplied migration / broken contract). */
async function expectNoServerError(response: APIResponse, label: string): Promise<number> {
  const status = response.status()
  if (status >= 500) {
    const body = await response.text().catch(() => '<unreadable body>')
    throw new Error(
      `${label} returned HTTP ${status} — this is the unapplied-migration / broken-schema signal.\nBody: ${body}`,
    )
  }
  return status
}

/** True when a live backend answers the health probe at all. */
async function backendReachable(request: APIRequestContext): Promise<boolean> {
  try {
    const health = await request.get(`${API.replace(/\/api\/v1$/, '')}/api/v1/health`)
    return health.ok() || health.status() === 401 || health.status() === 403
  } catch {
    return false
  }
}

test.describe('Real Backend Integration - conversational optimizer', () => {
  test.skip(!TOKEN, 'Requires REAL_API_TOKEN / AGENT_TEST_TOKEN and a running backend')

  test('optimizer-model config endpoint answers from the real database (never 500)', async ({
    request,
  }) => {
    if (!(await backendReachable(request))) {
      test.skip(true, 'Backend not reachable — skipping real backend integration test')
      return
    }

    const response = await request.get(`${API}/agents/model-configs/optimizer-model`, {
      headers: authHeaders(),
    })
    const status = await expectNoServerError(response, 'GET /agents/model-configs/optimizer-model')
    // 200 = the tenant-scoped read works; 401/403 = the token lacks the grant
    // (honest skip, never a silent pass of a broken schema).
    if (status === 401 || status === 403) {
      test.skip(true, 'Token lacks agent::read — cannot verify the optimizer-model read')
      return
    }
    expect(status).toBe(200)

    const body = await response.json()
    expect(body).toHaveProperty('selected_model_id')
    expect(body).toHaveProperty('effective_model_id')
    expect(body).toHaveProperty('source')
    expect(body).toHaveProperty('configured')
    expect(body).toHaveProperty('enabled')
    expect(body).toHaveProperty('options')
    expect(Array.isArray(body.options)).toBe(true)
  })

  test('optimization conversation + ledger round-trip through the real stack', async ({
    request,
  }) => {
    if (!(await backendReachable(request))) {
      test.skip(true, 'Backend not reachable — skipping real backend integration test')
      return
    }

    const name = `e2e-optimizer-${Date.now()}`
    let agentTypeId: string | null = null
    let conversationId: string | null = null

    try {
      // ── A real subject agent type (typed) ────────────────────────────────
      const createAgent = await request.post(`${API}/agents/types`, {
        headers: authHeaders(),
        data: {
          name,
          description: 'E2E conversational-optimizer subject',
          input_type: 'none',
          output_type: 'auto',
          is_active: true,
        },
      })
      const createStatus = await expectNoServerError(createAgent, 'POST /agents/types')
      if (createStatus === 401 || createStatus === 403) {
        test.skip(true, 'Token cannot create an agent type (needs agent::update)')
        return
      }
      expect(createStatus).toBe(201)
      const agent = await createAgent.json()
      agentTypeId = agent.id as string
      expect(agentTypeId).toBeTruthy()

      // ── The subject-only optimization conversation create ────────────────
      const createConversation = await request.post(`${API}/conversations/optimization`, {
        headers: authHeaders(),
        data: { agent_type_id: agentTypeId },
      })
      const convStatus = await expectNoServerError(
        createConversation,
        'POST /conversations/optimization',
      )
      expect(convStatus).toBe(201)
      const created = await createConversation.json()

      conversationId = created.conversation.id as string
      expect(conversationId).toBeTruthy()
      // The mode is the persisted channel; the subject is the session's own
      // agent type — never a second/scope field.
      expect(created.conversation.channel).toBe('optimization')
      expect(created.subject.agent_type_id).toBe(agentTypeId)
      expect(created.subject.name).toBe(name)
      // Availability is computed and returned (never a hard failure to open).
      expect(created.availability).toHaveProperty('available')
      expect(created.availability).toHaveProperty('optimizer_model')

      // ── Read: subject + availability + replay/live audit ─────────────────
      const readConversation = await request.get(
        `${API}/conversations/${conversationId}/optimization`,
        { headers: authHeaders() },
      )
      const readStatus = await expectNoServerError(
        readConversation,
        'GET /conversations/{id}/optimization',
      )
      expect(readStatus).toBe(200)
      const detail = await readConversation.json()
      expect(detail.subject.agent_type_id).toBe(agentTypeId)
      expect(detail.audit).toHaveProperty('replay_verifications')
      expect(detail.audit).toHaveProperty('live_operations')
      expect(detail.audit).toHaveProperty('replay_only')

      // ── Ledger endpoint answers (empty is correct for a fresh session) ───
      const ledger = await request.get(
        `${API}/conversations/${conversationId}/live-test-requests`,
        { headers: authHeaders() },
      )
      const ledgerStatus = await expectNoServerError(
        ledger,
        'GET /conversations/{id}/live-test-requests',
      )
      expect(ledgerStatus).toBe(200)
      const rows = await ledger.json()
      expect(Array.isArray(rows)).toBe(true)
      expect(rows).toHaveLength(0)
    } finally {
      // Cleanup: end the conversation, then delete the subject agent type.
      if (conversationId) {
        await request
          .post(`${API}/conversations/${conversationId}/end`, { headers: authHeaders() })
          .catch(() => undefined)
      }
      if (agentTypeId) {
        const deleted = await request
          .delete(`${API}/agents/types/${agentTypeId}`, { headers: authHeaders() })
          .catch(() => null)
        if (deleted) {
          const status = deleted.status()
          // 204 is the success path; anything else is only acceptable when the
          // token lacks the grant we already exercised above.
          expect([200, 204, 403, 404]).toContain(status)
        }
      }
    }
  })

  test('the optimization read/ledger endpoints fail closed (not 500) for an unknown session', async ({
    request,
  }) => {
    if (!(await backendReachable(request))) {
      test.skip(true, 'Backend not reachable — skipping real backend integration test')
      return
    }

    const unknown = '00000000-0000-0000-0000-000000000000'
    for (const path of [
      `${API}/conversations/${unknown}/optimization`,
      `${API}/conversations/${unknown}/live-test-requests`,
    ]) {
      const response = await request.get(path, { headers: authHeaders() })
      const status = await expectNoServerError(response, `GET ${path}`)
      expect([401, 403, 404]).toContain(status)
    }
  })
})
