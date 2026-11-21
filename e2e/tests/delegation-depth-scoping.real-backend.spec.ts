import { expect, test } from '@playwright/test'

/**
 * Real Backend Integration - Delegation Depth.
 *
 * Unmocked: drives the live Control Center REST API (and its PostgreSQL-backed
 * validation) to prove the platform-level delegation-depth ceiling is really
 * gone, not just relaxed in a mocked world.
 *
 * What this suite proves live:
 *  - `POST /agents/types` accepts a Max Delegation Depth above the former 32
 *    ceiling and persists it unchanged;
 *  - `PUT /agents/types/{id}` accepts a very large value (1000) and persists it;
 *  - a negative value is still rejected with a structured, per-field error;
 *  - recreating/patching keeps the stored value intact (no silent rewrite).
 *
 * What it deliberately does NOT do: run a real nested delegation to completion.
 * That requires a configured model provider and live LLM calls, which the
 * canonical E2E environment does not provide. The nested-delegation and
 * parent/child log scoping journeys are covered by the mocked spec
 * (`delegation-depth-scoping.spec.ts`) and by the backend unit/integration
 * suites.
 *
 * Skips cleanly (never fails) when the live stack is unavailable, or when the
 * tenant cannot be provisioned (self-serve registration rate limit).
 */

const API = 'http://localhost:8000/api/v1'

interface TenantSession {
  token: string
  slug: string
}

async function apiIsReachable(): Promise<boolean> {
  try {
    const resp = await fetch(`${API}/health`, { signal: AbortSignal.timeout(3000) })
    // 403 = CC is alive but wants tenant resolution; any HTTP status means the
    // control plane is up. Only a transport failure means "not running".
    return resp.status > 0
  } catch {
    return false
  }
}

async function provisionTenant(): Promise<TenantSession | null> {
  const unique = `e2e-depth-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
  try {
    const resp = await fetch(`${API}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: `${unique}@e2e.test`,
        password: 'E2ePassword1',
        organization_name: `E2E Depth Org ${unique}`,
        slug: unique,
      }),
    })
    if (resp.status !== 200) return null
    const body = (await resp.json()) as { access_token: string; slug: string }
    return { token: body.access_token, slug: body.slug }
  } catch {
    return null
  }
}

test.describe('Real Backend Integration - Delegation Depth', () => {
  test('configured depth above the former ceiling is accepted and persisted', async ({
    request,
  }) => {
    test.setTimeout(120_000)

    test.skip(!(await apiIsReachable()), 'Live backend not reachable on :8000')

    const tenant = await provisionTenant()
    test.skip(
      tenant === null,
      'Could not provision an E2E tenant (self-serve registration unavailable or rate-limited)',
    )
    if (!tenant) return

    const auth = {
      Authorization: `Bearer ${tenant.token}`,
      'X-Tenant': tenant.slug,
      'Content-Type': 'application/json',
    }
    const suffix = `${Date.now()}-${Math.floor(Math.random() * 1e6)}`
    const agentName = `e2e-depth-${suffix}`

    // ── 0. Bindable role: the API requires ≥1 SOP/Skill binding. ──────────
    const skill = await request.post(`${API}/skills`, {
      headers: auth,
      data: { name: `e2e-depth-skill-${suffix}`, tool_ids: [] },
    })
    expect(skill.status()).toBe(201)
    const skillId = ((await skill.json()) as { id: string }).id

    const role = await request.post(`${API}/agents/roles`, {
      headers: auth,
      data: { name: `e2e-depth-role-${suffix}`, skill_ids: [skillId], sop_ids: [] },
    })
    expect(role.status()).toBe(201)
    const roleId = ((await role.json()) as { id: string }).id

    // ── 1. Create with 64 (above the former 32 ceiling) ──────────────────
    const created = await request.post(`${API}/agents/types`, {
      headers: auth,
      data: {
        name: agentName,
        role_id: roleId,
        skill_bindings: [{ skill_id: skillId, order: 1 }],
        guardrail_max_delegation_depth: 64,
      },
    })
    expect(created.status()).toBe(201)
    const createdBody = (await created.json()) as {
      id: string
      guardrail_max_delegation_depth: number
    }
    expect(createdBody.guardrail_max_delegation_depth).toBe(64)

    try {
      // ── 2. Persisted unchanged (fresh read, not echoed input) ───────────
      const read = await request.get(`${API}/agents/types/${createdBody.id}`, { headers: auth })
      expect(read.status()).toBe(200)
      const readBody = (await read.json()) as { guardrail_max_delegation_depth: number }
      expect(readBody.guardrail_max_delegation_depth).toBe(64)

      // ── 3. Update to 1000 — no residual platform ceiling ────────────────
      const updated = await request.put(`${API}/agents/types/${createdBody.id}`, {
        headers: auth,
        data: { guardrail_max_delegation_depth: 1000 },
      })
      expect(updated.status()).toBe(200)
      const updatedBody = (await updated.json()) as { guardrail_max_delegation_depth: number }
      expect(updatedBody.guardrail_max_delegation_depth).toBe(1000)

      const reread = await request.get(`${API}/agents/types/${createdBody.id}`, { headers: auth })
      expect(
        ((await reread.json()) as { guardrail_max_delegation_depth: number })
          .guardrail_max_delegation_depth,
      ).toBe(1000)

      // ── 4. Negative is still rejected with a structured field error ─────
      const negative = await request.put(`${API}/agents/types/${createdBody.id}`, {
        headers: auth,
        data: { guardrail_max_delegation_depth: -1 },
      })
      expect(negative.status()).toBe(422)
      expect(JSON.stringify(await negative.json())).toContain('guardrail_max_delegation_depth')

      // The rejected write did not corrupt the stored value.
      const afterReject = await request.get(`${API}/agents/types/${createdBody.id}`, {
        headers: auth,
      })
      expect(
        ((await afterReject.json()) as { guardrail_max_delegation_depth: number })
          .guardrail_max_delegation_depth,
      ).toBe(1000)
    } finally {
      // ── 5. Cleanup ──────────────────────────────────────────────────────
      const deleted = await request.delete(`${API}/agents/types/${createdBody.id}`, {
        headers: auth,
      })
      expect([204, 404]).toContain(deleted.status())
    }
  })
})
