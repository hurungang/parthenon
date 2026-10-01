import { expect, test } from '@playwright/test'

/**
 * Real Backend Integration - Multi-Tenant Isolation (Phase 9.7).
 *
 * No-mock variant running against the live backend + real PostgreSQL.
 * Every assertion below only passes when the multi-tenant migration is
 * applied: `/api/v1/auth/tenant` reads `multi_tenancy_enabled` from the
 * `platform_settings` table, and the platform/tenant APIs query the five
 * tenant-era tables — an un-migrated database makes them 500.
 *
 * Scope (conservative, mirroring agent-runtime-monitor.real-backend.spec.ts):
 * - discovery contract reports the switch state (migration-backed read),
 * - platform admin APIs return metadata + aggregates ONLY (never business rows),
 * - direct-addressed bogus tenant ids yield 404 (no data leak, fail-closed),
 * - audit events carry tenant attribution.
 *
 * Skips cleanly when `E2E_REAL_BACKEND_TOKEN` is unset or the backend is
 * unreachable — it must never block the mocked suites.
 */

const API = 'http://localhost:8000/api/v1'

test.describe('Real Backend Integration - Multi-Tenant Isolation', () => {
  test('isolation contract holds against the live backend', async ({ page }) => {
    const realToken = process.env.E2E_REAL_BACKEND_TOKEN
    if (!realToken) {
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

    const headers = { Authorization: `Bearer ${realToken}` }

    // ── 1. Discovery (public, migration-backed settings read) ────────────
    // A 500 here means the multi-tenant migration is NOT applied — fail
    // loudly (per test-plan pre-test checklist) rather than skip.
    const discovery = await page.request.get(`${API}/auth/tenant`, { headers })
    if (discovery.status() === 500) {
      throw new Error(
        'Multi-tenant migration not applied: /auth/tenant returned 500. ' +
          'Run `alembic upgrade head` and restart backend before this suite.',
      )
    }
    expect(discovery.status()).toBe(200)
    const discoveryBody = await discovery.json()
    expect(typeof discoveryBody.multi_tenancy_enabled).toBe('boolean')

    // ── 2. Platform tenants API: metadata + aggregates only (CS-22) ──────
    const tenants = await page.request.get(`${API}/platform/tenants`, { headers })
    if (tenants.status() === 401 || tenants.status() === 403) {
      // Token lacks platform-admin rights — the permission guard worked.
      test.skip()
      return
    }
    expect(tenants.status()).toBe(200)
    const tenantsBody = await tenants.json()
    expect(Array.isArray(tenantsBody.items)).toBe(true)
    for (const t of tenantsBody.items) {
      // Metadata + aggregate shape only — never nested business rows.
      expect(typeof t.id).toBe('string')
      expect(typeof t.slug).toBe('string')
      expect(['active', 'suspended', 'deleted']).toContain(t.status)
      expect(typeof t.user_count).toBe('number')
      expect(typeof t.agent_count).toBe('number')
      const keys = Object.keys(t)
      expect(keys).not.toContain('roles')
      expect(keys).not.toContain('agents')
      expect(keys).not.toContain('members')
    }

    // ── 3. Direct-addressed bogus tenant id → 404, never a leak (CS-12) ──
    const bogus = await page.request.get(
      `${API}/platform/tenants/00000000-0000-0000-0000-000000000000`,
      { headers },
    )
    expect(bogus.status()).toBe(404)

    // ── 4. Platform audit API: tenant-attributed security events ─────────
    const audit = await page.request.get(`${API}/platform/audit-events?limit=50`, {
      headers,
    })
    if (audit.status() === 200) {
      const auditBody = await audit.json()
      expect(Array.isArray(auditBody.items)).toBe(true)
      for (const evt of auditBody.items) {
        expect(typeof evt.event_type).toBe('string')
        expect(typeof evt.is_security_relevant).toBe('boolean')
        // Tenant attribution present (slug or platform-level null).
        expect('tenant_slug' in evt).toBe(true)
      }
    } else {
      // Tenant admins must NOT see the platform audit API (fail-closed).
      expect([401, 403]).toContain(audit.status())
    }

    // ── 5. Tenant self-service surface is fail-closed without context ────
    const tenantSettings = await page.request.get(`${API}/tenant/settings`, { headers })
    expect([200, 401, 403]).toContain(tenantSettings.status())
    if (tenantSettings.status() === 200) {
      // If readable, it is scoped to the caller's own tenant only.
      const body = await tenantSettings.json()
      expect(typeof body.slug).toBe('string')
    }
  })
})
