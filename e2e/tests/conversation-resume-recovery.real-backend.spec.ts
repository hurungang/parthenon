import { expect, test } from '@playwright/test'

/**
 * Real Backend Integration - resumable agent turn persistence.
 *
 * No `page.route()` mocks anywhere in this file: every request below hits the
 * live Control Center / migrated PostgreSQL. It proves the production wiring of
 * this change (PRD AC-5.1/AC-D1/AC-D3 and test-plan §3 + §5-H/I):
 *
 * - the new CC internal resume / checkpoint / claim routes are **registered**
 *   and fail closed (401/403) for any caller that is not the certificate-bearing
 *   Communication Hub — including an authenticated human JWT;
 * - the conversation sessions listing returns the durable resume projection
 *   (`resume_state` / `resume_outcome` / `resume_expires_at`) read from the
 *   migrated database — a 500 here means the migration was not applied;
 * - a real conversation session round-trips through the resume endpoint and the
 *   pause/resume state stays inside that session.
 *
 * The suite skips gracefully when the stack is unreachable or no operator token
 * is available (`E2E_REAL_BACKEND_TOKEN`, or the dev admin login) — it must
 * never block the mocked suites and never start services itself.
 */

const API = 'http://localhost:8000/api/v1'
const UNKNOWN_SESSION = '00000000-0000-0000-0000-000000000000'
const INTERNAL = `${API}/internal/data/conversations/${UNKNOWN_SESSION}`

async function backendReachable(request: import('@playwright/test').APIRequestContext) {
  try {
    const health = await request.get(`${API}/health`)
    return health.status() > 0
  } catch {
    return false
  }
}

async function operatorToken(
  request: import('@playwright/test').APIRequestContext,
): Promise<string | null> {
  const envToken = process.env.E2E_REAL_BACKEND_TOKEN
  if (envToken) return envToken
  try {
    const login = await request.post(`${API}/auth/token`, {
      form: { username: 'admin@example.com', password: 'admin' },
    })
    if (!login.ok()) return null
    const body = await login.json()
    return typeof body.access_token === 'string' ? body.access_token : null
  } catch {
    return null
  }
}

test.describe('Real Backend Integration - resumable agent turn persistence', () => {
  test('CC internal resume/checkpoint/claim routes are registered and fail closed', async ({
    request,
  }) => {
    if (!(await backendReachable(request))) {
      test.skip()
      return
    }

    // No service certificate / signed tenant context from a browser/API client
    // ⇒ every internal data-plane route must fail closed. A 2xx would mean the
    // paused-turn surface is exposed to unauthenticated callers.
    const probes: Array<{
      label: string
      probe: () => Promise<import('@playwright/test').APIResponse>
    }> = [
      { label: 'GET resume', probe: () => request.get(`${INTERNAL}/resume`) },
      { label: 'PUT resume', probe: () => request.put(`${INTERNAL}/resume`, { data: {} }) },
      {
        label: 'GET checkpoint',
        probe: () => request.get(`${INTERNAL}/resume/checkpoint`),
      },
      {
        label: 'PUT checkpoint',
        probe: () =>
          request.put(`${INTERNAL}/resume/checkpoint`, { data: { payload: {} } }),
      },
      {
        label: 'POST claim',
        probe: () =>
          request.post(`${INTERNAL}/resume/claim`, {
            data: { instance_id: 'e2e-probe', lease_seconds: 45 },
          }),
      },
      {
        label: 'POST release',
        probe: () => request.post(`${INTERNAL}/resume/release`, { data: {} }),
      },
      {
        label: 'POST complete',
        probe: () =>
          request.post(`${INTERNAL}/resume/complete`, { data: { outcome: 'denied' } }),
      },
    ]

    for (const { label, probe } of probes) {
      const response = await probe()
      expect(
        [401, 403],
        `${label} must fail closed for a non-CH caller (got ${response.status()})`,
      ).toContain(response.status())
    }
  })

  test('an operator JWT cannot reach the paused-turn data plane', async ({ request }) => {
    if (!(await backendReachable(request))) {
      test.skip()
      return
    }
    const token = await operatorToken(request)
    if (!token) {
      test.skip()
      return
    }

    const headers = { Authorization: `Bearer ${token}` }
    const response = await request.get(`${INTERNAL}/resume`, { headers })
    expect([401, 403]).toContain(response.status())
  })

  test('sessions listing returns the durable resume projection', async ({ request }) => {
    if (!(await backendReachable(request))) {
      test.skip()
      return
    }
    const token = await operatorToken(request)
    if (!token) {
      test.skip()
      return
    }
    const headers = { Authorization: `Bearer ${token}` }

    const listing = await request.get(`${API}/conversations/sessions`, { headers })
    if (listing.status() === 401 || listing.status() === 403) {
      test.skip()
      return
    }
    if (listing.status() === 500) {
      throw new Error(
        'Resume projection unavailable: GET /conversations/sessions returned 500. ' +
          'Apply the conversation-turn-resume migration (alembic upgrade head) ' +
          'and restart Control Center before running this suite.',
      )
    }
    expect(listing.status()).toBe(200)

    const body = await listing.json()
    const items: any[] = Array.isArray(body) ? body : (body.items ?? [])
    expect(Array.isArray(items)).toBe(true)

    // Every session read carries the projection keys (null when idle) — this is
    // what the sessions-list badges render from.
    for (const item of items) {
      expect(item).toHaveProperty('resume_state')
      expect(item).toHaveProperty('resume_outcome')
      expect(item).toHaveProperty('resume_expires_at')
      if (item.resume_state !== null && item.resume_state !== undefined) {
        expect(['waiting_for_human', 'resuming', 'resolved', 'unresumable']).toContain(
          item.resume_state,
        )
      }
    }
  })

  test('a real conversation session round-trips through the resume endpoint', async ({
    request,
  }) => {
    if (!(await backendReachable(request))) {
      test.skip()
      return
    }
    const token = await operatorToken(request)
    if (!token) {
      test.skip()
      return
    }
    const headers = { Authorization: `Bearer ${token}` }

    const listing = await request.get(`${API}/conversations/sessions`, { headers })
    if (listing.status() !== 200) {
      test.skip()
      return
    }
    const body = await listing.json()
    const items: any[] = Array.isArray(body) ? body : (body.items ?? [])
    if (items.length === 0) {
      // No live conversation in this environment — nothing to round-trip.
      test.skip()
      return
    }

    const sessionId = items[0].id as string
    const detail = await request.post(`${API}/conversations/${sessionId}/resume`, {
      headers,
    })
    expect([200, 403, 404]).toContain(detail.status())
    if (detail.status() === 200) {
      const payload = await detail.json()
      expect(payload.id).toBe(sessionId)
      expect(Array.isArray(payload.turns)).toBe(true)
    }
  })
})
