import { expect, test } from '@playwright/test'

/**
 * Real Backend Integration - Self-Serve Registration & Quotas (Phase 10).
 *
 * No-mock variant running against the live backend + real PostgreSQL.
 * Atomicity of the account + tenant + root-membership registration is
 * only provable against the real database; this suite exercises the
 * public registration endpoint end to end and reads back the tenant's
 * quota usage through the real enforcement-path data.
 *
 * Scope (mirrors multi-tenant-isolation.real-backend.spec.ts):
 * - migration-liveness check: /auth/tenant returning 500 means the
 *   multi-tenant migration is NOT applied → fail loudly (per the
 *   test-plan pre-test checklist), never skip silently,
 * - a real registration returns a tenant-bound root session,
 * - a SECOND registration with the same email is blocked (one tenant
 *   per user) and leaves exactly one tenant,
 * - the tenant usage API reads the fresh tenant's free-tier limits with
 *   the returned token.
 *
 * Skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is
 * unreachable — it must never block the mocked suites.
 */

const API = 'http://localhost:8000/api/v1'

test.describe('Real Backend Integration - Self-Serve Registration & Quotas', () => {
  test('registration + one-tenant block + usage read against the live backend', async ({
    page,
  }) => {
    if (!process.env.E2E_REAL_BACKEND_TOKEN) {
      test.skip()
      return
    }

    // Liveness probe — no live backend → skip gracefully.
    let healthStatus = 0
    try {
      const health = await page.request.get(`${API}/health`)
      healthStatus = health.status()
    } catch {
      healthStatus = 0
    }
    if (healthStatus === 0) {
      test.skip()
      return
    }

    // ── 1. Discovery is migration-backed — a 500 means UNAPPLIED
    //      migration → fail loudly (per AGENTS.md debugging guidance).
    const discovery = await page.request.get(`${API}/auth/tenant`)
    if (discovery.status() === 500) {
      throw new Error(
        'Multi-tenant migration not applied: /auth/tenant returned 500. ' +
          'Run `alembic upgrade head` and restart backend before this suite.',
      )
    }
    expect(discovery.status()).toBe(200)
    const discoveryBody = await discovery.json()
    expect(typeof discoveryBody.multi_tenancy_enabled).toBe('boolean')
    if (!discoveryBody.multi_tenancy_enabled) {
      // Registration is switch-gated (CS-29) — the contract holds but the
      // self-serve journey needs the switch on.
      test.skip()
      return
    }

    // ── 2. Real registration: atomic account + tenant + root ──────────
    const unique = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}`
    const email = `${unique}@e2e.test`
    const slug = `e2e-${unique}`.toLowerCase().replace(/[^a-z0-9-]/g, '-')

    const registered = await page.request.post(`${API}/auth/register`, {
      data: {
        email,
        password: 'E2ePassword1',
        organization_name: `E2E Org ${unique}`,
        slug,
      },
    })
    expect(registered.status()).toBe(200)
    const body = await registered.json()
    expect(body.slug).toBe(slug)
    expect(body.is_root).toBe(true)
    expect(body.your_role).toBe('tenant_admin')
    expect(body.access_token).toBeTruthy()

    // ── 3. One tenant per user: the same email is blocked ─────────────
    const second = await page.request.post(`${API}/auth/register`, {
      data: {
        email,
        password: 'E2ePassword1',
        organization_name: `E2E Org Two ${unique}`,
        slug: `${slug}-two`,
      },
    })
    expect(second.status()).toBe(409)
    const secondDetail = (await second.json()).detail
    expect(
      secondDetail.includes('one organization') ||
        secondDetail.includes('already exists'),
    ).toBeTruthy()

    // ── 4. The fresh root reads its own tenant usage (free defaults) ──
    const usage = await page.request.get(`${API}/tenant/usage`, {
      headers: { Authorization: `Bearer ${body.access_token}` },
    })
    expect(usage.status()).toBe(200)
    const usageBody = await usage.json()
    expect(usageBody.tier).toBe('free')
    expect(usageBody.max_users).toBeGreaterThan(0)
    expect(usageBody.users).toBe(1) // exactly the root membership — atomicity
    expect(usageBody.executions_this_month).toBe(0) // fresh bucket

    // ── 5. Cross-check: slug resolution reflects the new tenant ───────
    const discovered = await page.request.get(
      `${API}/auth/tenant?slug=${slug}`,
    )
    expect(discovered.status()).toBe(200)
    const discoveredBody = await discovered.json()
    expect(discoveredBody.tenant?.slug).toBe(slug)
  })
})
