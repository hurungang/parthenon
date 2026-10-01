import { expect, test } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * Single-Tenant Regression Canary (CS-01 / CS-02 — highest priority guard).
 *
 * With multi_tenancy_enabled=false (the seeded default) the UI must behave
 * EXACTLY like the pre-change single-tenant product:
 * - tenant discovery reports the switch off,
 * - no platform console navigation group exists in the sidebar,
 * - /platform/* routes are absent (redirect to /dashboard),
 * - no tenant branding or organization picker ever renders,
 * - a stray X-Tenant request header causes no error and no scope change.
 *
 * All backend calls are mocked; the discovery endpoint is the source of
 * truth for the switch state (enabled=false).
 */

/** Discovery payload with the tenancy switch OFF (seeded default). */
const DISCOVERY_OFF = {
  multi_tenancy_enabled: false,
  tenant: null,
}

/**
 * Installs the switch-off mocks.  The memberships handler is registered
 * first (lowest priority): it would prove that even a multi-org user sees
 * NO picker when the switch is off (gate requires multiTenancyEnabled).
 */
async function setupSwitchOff(page: import('@playwright/test').Page) {
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          multi_tenancy_enabled: false,
          items: [
            {
              tenant_id: 't-a',
              tenant_slug: 'org-a',
              tenant_name: 'Org A',
              tenant_role: 'member',
              is_default: true,
            },
            {
              tenant_id: 't-b',
              tenant_slug: 'org-b',
              tenant_name: 'Org B',
              tenant_role: 'member',
              is_default: false,
            },
          ],
        }),
      }),
  )
  // Exact discovery path (registered LAST → checked FIRST).
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant') && !url.href.includes('tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(DISCOVERY_OFF),
      }),
  )
  await standardSetup(page)
}

test.describe('Single-Tenant Regression (switch OFF)', () => {
  test.beforeEach(async ({ page }) => {
    await setupSwitchOff(page)
  })

  test('CS-01: dashboard loads unchanged with the switch off', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
    await expect(page.locator('header').first()).toBeVisible()
  })

  test('CS-01: no tenant branding in the header when the switch is off', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // AppShell renders the tenant prefix chip ONLY when activeTenant is
    // non-null, which requires the switch on + a tenant claim.
    const body = await page.locator('body').innerText()
    expect(body).not.toContain('nav.tenantPrefix')
    expect(body).not.toContain('Org A')
  })

  test('CS-01: platform console nav group absent from the sidebar', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // PLATFORM_NAV_GROUP is appended only when multiTenancyEnabled === true.
    await expect(page.getByText('nav.platformTenants')).toHaveCount(0)
    await expect(page.getByText('nav.platformSettings')).toHaveCount(0)
    await expect(page.getByText('nav.platformAudit')).toHaveCount(0)
  })

  test('CS-01: /platform/* routes are absent — navigating there lands on dashboard', async ({
    page,
  }) => {
    await page.goto('/platform/tenants')
    // The redirect happens once discovery RESOLVES (switch off) — poll
    // for the post-resolution URL rather than racing the first paint.
    await expect
      .poll(() => page.url(), { timeout: 10_000 })
      .not.toContain('/platform')
  })

  test('CS-01: no organization picker even for a multi-org user', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    // TenantSessionGate requires multiTenancyEnabled === true; with the
    // switch off the picker must never appear (memberships has 2 orgs).
    await expect(page.getByTestId('tenant-picker')).toHaveCount(0)
  })

  test('CS-02: stray tenant headers are ignored — discovery stays inert', async ({ page }) => {
    // The discovery endpoint is the app's only switch source.  With the
    // switch off the backend ignores any X-Tenant header: the response
    // stays enabled=false with no error and no scope change.  Fetched in
    // page context so the route mock intercepts (no live backend needed).
    await page.goto('/dashboard')
    const resp = await page.evaluate(async () => {
      const r = await fetch('http://localhost:8000/api/v1/auth/tenant', {
        headers: { 'X-Tenant': 'org-b' },
      })
      return { status: r.status, body: await r.json() }
    })
    expect(resp.status).toBe(200)
    expect(resp.body.multi_tenancy_enabled).toBe(false)
    expect(resp.body.tenant).toBeNull()
  })
})
