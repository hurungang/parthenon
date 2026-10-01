import { expect, test, type Page } from '@playwright/test'
import {
  mockHealth,
  mockIdentityStatus,
  mockTelemetry,
} from './_helpers'

/**
 * Tenant-aware sign-in flows (CS-24, Phase 7.2 / 7.1):
 * - suspended/deleted tenant at the resolved address → sign-in blocked
 * - multi-org users get the organization picker; one session = one tenant
 * - switching organizations re-runs sign-in (fresh token requirement)
 * - the resolved tenant slug lives in sessionStorage only (never durable)
 */

// ── Tokens ───────────────────────────────────────────────────────────────────

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64')
const exp = Math.floor(Date.now() / 1000) + 7200
const header = b64({ alg: 'RS256', typ: 'JWT' })

/** Regular (non-super) tenant user token bound to org-a via the tenant claim. */
const ORG_A_USER_TOKEN = `${header}.${b64({
  sub: 'e2e-tenant-user',
  exp,
  iat: 0,
  name: 'Tenant User',
  tenant: 'org-a',
})}.fake-sig`

const MEMBERSHIPS = [
  {
    tenant_id: 't-a',
    tenant_slug: 'org-a',
    tenant_name: 'Org A',
    tenant_role: 'tenant_admin',
    is_default: true,
  },
  {
    tenant_id: 't-b',
    tenant_slug: 'org-b',
    tenant_name: 'Org B',
    tenant_role: 'member',
    is_default: false,
  },
]

/** Base public-surface mocks (health/telemetry/identity-status) — no token. */
async function setupPublicSurface(page: Page) {
  await mockHealth(page)
  await mockTelemetry(page)
  await mockIdentityStatus(page)
  await page.route(
    (url) => url.href.includes('/api/v1/system/super-admin/status'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_enabled: false }),
      }),
  )
  await page.route(
    (url) => url.href.includes('/api/v1/system/identity-providers'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              provider_scope: 'user',
              provider_type: 'keycloak',
              display_name: 'Keycloak',
              is_enabled: true,
              issuer_url: 'http://localhost:4173/fake-realm',
              client_id: 'parthenon-api-ui',
              public_client_id: 'parthenon-api-ui',
            },
          ],
        }),
      }),
  )
}

async function mockDiscovery(
  page: Page,
  discovery: { multi_tenancy_enabled: boolean; tenant: object | null },
) {
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant') && !url.href.includes('tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(discovery),
      }),
  )
}

async function mockMemberships(page: Page, items: typeof MEMBERSHIPS) {
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ multi_tenancy_enabled: true, items }),
      }),
  )
}

test.describe('Suspended tenant sign-in', () => {
  test('suspended tenant at the address → sign-in blocked with a clear message', async ({
    page,
  }) => {
    await setupPublicSurface(page)
    await mockDiscovery(page, {
      multi_tenancy_enabled: true,
      tenant: {
        slug: 'acme',
        name: 'Acme Corp',
        status: 'suspended',
        sign_in_ready: true,
      },
    })

    await page.goto('/login')
    await page.waitForLoadState('load')

    // auth.tenantBlocked: no sign-in flow is rendered at all.
    await expect(
      page.getByText('This organization is not accessible (suspended).'),
    ).toBeVisible()
    // Data is not lost — the message never claims deletion.
    const body = await page.locator('body').innerText()
    expect(body).not.toContain('deleted')
  })

  test('deleted tenant at the address → sign-in blocked as well', async ({ page }) => {
    await setupPublicSurface(page)
    await mockDiscovery(page, {
      multi_tenancy_enabled: true,
      tenant: {
        slug: 'acme',
        name: 'Acme Corp',
        status: 'deleted',
        sign_in_ready: false,
      },
    })

    await page.goto('/login')
    await page.waitForLoadState('load')
    await expect(
      page.getByText('This organization is not accessible (deleted).'),
    ).toBeVisible()
  })
})

test.describe('Multi-org picker — one session = one tenant', () => {
  test.beforeEach(async ({ page }) => {
    await setupPublicSurface(page)
    await mockDiscovery(page, {
      multi_tenancy_enabled: true,
      tenant: { slug: 'org-a', name: 'Org A', status: 'active', sign_in_ready: true },
    })
    await mockMemberships(page, MEMBERSHIPS)
  })

  test('multi-org user sees the picker; single selection binds the session', async ({
    page,
  }) => {
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token)
    }, ORG_A_USER_TOKEN)

    await page.goto('/dashboard')
    const picker = page.getByTestId('tenant-picker')
    await expect(picker).toBeVisible()

    // Both organizations listed with their roles ("Org A" also appears in
    // the signed-in-as caption, so target the list items by role).
    await expect(picker.getByRole('button', { name: /Org A/ })).toBeVisible()
    await expect(picker.getByRole('button', { name: /Org B/ })).toBeVisible()
    // Real i18n bundle is active in E2E (unlike unit tests with mocked t()).
    await expect(picker.getByText('Tenant admin')).toBeVisible()
    await expect(picker.getByText('Member', { exact: true })).toBeVisible()

    // Selecting the CURRENT organization continues into the workspace and
    // binds the session (confirmed in sessionStorage, keyed to the token).
    await picker.getByRole('button', { name: /Org A/ }).click()
    await expect(page.getByTestId('tenant-picker')).toHaveCount(0)
    const confirmed = await page.evaluate(() =>
      sessionStorage.getItem('parthenon_tenant_confirmed'),
    )
    expect(confirmed).not.toBeNull()

    // Reload — the bound session does NOT re-prompt (session binding holds).
    await page.reload()
    await page.waitForLoadState('load')
    await expect(page.getByTestId('tenant-picker')).toHaveCount(0)
  })

  test('switching organizations requires a fresh sign-in and stores the slug in sessionStorage only', async ({
    page,
  }) => {
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token)
    }, ORG_A_USER_TOKEN)

    await page.goto('/dashboard')
    const picker = page.getByTestId('tenant-picker')
    await expect(picker).toBeVisible()

    await picker.getByRole('button', { name: /Org B/ }).click()

    // Selecting another organization re-runs the sign-in: the resolved
    // slug is recorded per-tab in sessionStorage (one session = one
    // tenant), then the OIDC redirect navigates to the (fake, same-origin)
    // realm — never written to durable localStorage.
    await page.waitForURL(/fake-realm\/protocol\/openid-connect\/auth/, {
      timeout: 10_000,
    })
    const slug = await page.evaluate(() =>
      sessionStorage.getItem('parthenon_tenant_slug'),
    )
    expect(slug).toBe('org-b')
    const durable = await page.evaluate(() =>
      localStorage.getItem('parthenon_tenant_slug'),
    )
    expect(durable).toBeNull()
  })

  test('single-org users never see the picker', async ({ page }) => {
    await mockMemberships(page, [MEMBERSHIPS[0]])
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token)
    }, ORG_A_USER_TOKEN)

    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    await expect(page.getByTestId('tenant-picker')).toHaveCount(0)
  })

  test('super admins never see the picker', async ({ page }) => {
    const superToken = `${header}.${b64({
      sub: 'e2e-platform-admin',
      exp,
      iat: 0,
      name: 'Platform Admin',
      is_super_admin: true,
    })}.fake-sig`
    await mockMemberships(page, MEMBERSHIPS) // even with 2 orgs available
    await page.addInitScript((token) => {
      localStorage.setItem('access_token', token)
    }, superToken)

    await page.goto('/dashboard')
    await page.waitForLoadState('load')
    await expect(page.getByTestId('tenant-picker')).toHaveCount(0)
  })
})

// ── OIDC workspace round-trip (FIX-20260929-043443) ─────────────────────────

test.describe('OIDC workspace sign-in keeps the session tenant-bound', () => {
  const WORKSPACE = 'test-com'
  /** Same-origin fake issuer so login() redirects within the app origin. */
  const TENANT_ISSUER = 'http://localhost:4173/fake-realm-testcom'

  /** Token exchange result as a REAL provider issues it: NO tenant claim —
   *  external / tenant-scoped providers never embed one.  The dashboard
   *  mock mirrors the FIXED backend contract (FIX-20260929-043443): the
   *  backend validates the token against the workspace's own provider and
   *  INJECTS the tenant claim at validation time, so a bound session is
   *  accepted even though the raw token carries no claim.  The frontend
   *  regression this guard catches is the binding being lost mid-round-
   *  trip (missing X-Tenant header → 401). */
  const OIDC_TOKEN_NO_TENANT_CLAIM = `${header}.${b64({
    sub: 'oidc-user-from-provider',
    exp,
    iat: 0,
    name: 'OIDC User',
  })}.fake-sig`

  /** Observed dashboard data calls: { xTenant, tokenTenant }. */
  let dashboardCalls: Array<{ xTenant: string | null; tokenTenant: string | null }>

  test.beforeEach(() => {
    dashboardCalls = []
  })

  /**
   * Full mocked workspace → SSO → callback → dashboard round-trip.
   * Discovery is query-aware: ?slug=test-com resolves the workspace (the
   * sign-in card), the bare host resolves to null (base-domain behaviour).
   */
  async function setupOidcRoundTrip(page: Page) {
    // Catch-all for the rest of the authenticated shell — registered FIRST
    // (Playwright resolves route handlers last-registered-first, so this
    // stays the lowest-priority handler behind every specific mock below).
    await page.route('http://localhost:8000/api/v1/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
    )

    await setupPublicSurface(page)
    await mockMemberships(page, [])

    // Tenant discovery — mirrors the REAL backend resolution order
    // (backend/app/api/v1/auth_tenant.py): explicit ?slug= wins, then the
    // X-Tenant header (apiClient attaches the bound slug), then the host.
    // A bare call with X-Tenant: test-com therefore ECHOES the workspace.
    await page.route(
      (url) => url.href.includes('/api/v1/auth/tenant') && !url.href.includes('tenant-memberships'),
      (route) => {
        const request = route.request()
        const slugParam = new URL(request.url()).searchParams.get('slug')
        const headerSlug = request.headers()['x-tenant'] ?? null
        const candidate = (slugParam ?? headerSlug ?? '').toLowerCase()
        const tenant =
          candidate === WORKSPACE
            ? { slug: WORKSPACE, name: 'Test Com', status: 'active', sign_in_ready: true }
            : null
        void route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ multi_tenancy_enabled: true, tenant }),
        })
      },
    )

    // Identity providers: the tenant's own provider (fake same-origin issuer).
    await page.route(
      (url) => url.href.includes('/api/v1/system/identity-providers'),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                provider_scope: 'user',
                provider_type: 'keycloak',
                display_name: `Keycloak (${WORKSPACE})`,
                is_enabled: true,
                issuer_url: TENANT_ISSUER,
                client_id: 'parthenon-api-ui',
                public_client_id: 'parthenon-api-ui',
              },
            ],
          }),
        }),
    )

    // Provider authorize endpoint → redirect straight back to the callback
    // (same tab, so sessionStorage behaves exactly like the real round-trip).
    await page.route(
      (url) => url.href.startsWith(`${TENANT_ISSUER}/protocol/openid-connect/auth`),
      (route) =>
        route.fulfill({
          status: 302,
          headers: { Location: '/callback?code=e2e-oidc-code&state=e2e' },
        }),
    )

    // Token exchange — OidcCallback posts to the built-in default authority
    // (VITE_OIDC_AUTHORITY unset in the e2e build → realms/parthenon).
    await page.route(
      (url) => url.href.includes('/protocol/openid-connect/token'),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            access_token: OIDC_TOKEN_NO_TENANT_CLAIM,
            refresh_token: 'e2e-refresh',
            id_token: 'e2e-id-token',
          }),
        }),
    )

    // Dashboard data — mirrors the FIXED backend contract (see the token
    // comment above): with X-Tenant bound the request is accepted (the
    // backend stamps the tenant claim from the provider registry binding
    // at validation time); a MISSING binding is rejected 401 — exactly
    // what a claim-less token produced against the pre-fix backend.
    await page.route(
      (url) => url.href.includes('/api/v1/dashboard/summary'),
      (route) => {
        const headers = route.request().headers()
        const xTenant = headers['x-tenant'] ?? null
        const payload = (headers['authorization'] ?? '')
          .replace('Bearer ', '')
          .split('.')[1]
        let tokenTenant: string | null = null
        try {
          const claims = JSON.parse(Buffer.from(payload, 'base64').toString())
          tokenTenant = typeof claims.tenant === 'string' ? claims.tenant : null
        } catch {
          tokenTenant = null
        }
        dashboardCalls.push({ xTenant, tokenTenant })
        if (!xTenant) {
          void route.fulfill({
            status: 401,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'Token is not valid for this tenant' }),
          })
          return
        }
        void route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            snapshot_counts: {},
            time_sensitive: {},
            permission_flags: {},
          }),
        })
      },
    )
  }

  test('SSO round-trip lands on /dashboard with X-Tenant bound and NO bounce to /login', async ({
    page,
  }) => {
    await setupOidcRoundTrip(page)

    // 1. Workspace card via deep link — binds the slug to the tab.
    await page.goto(`/login?workspace=${WORKSPACE}`)
    await page.waitForLoadState('load')
    await expect(page.getByTestId('password-signin-form')).toBeVisible()
    const slugBeforeSso = await page.evaluate(() =>
      sessionStorage.getItem('parthenon_tenant_slug'),
    )
    expect(slugBeforeSso).toBe(WORKSPACE)

    // 2. SSO button → provider authorize (mocked) → /callback → exchange
    //    (mocked) → /dashboard.
    await page.getByRole('button', { name: new RegExp(`Keycloak \\(${WORKSPACE}\\)`) }).click()
    await page.waitForURL(/\/dashboard/, { timeout: 15_000 })

    // 3. The dashboard data calls carry the workspace context (control —
    //    the binding survives the round-trip passively).
    await page.waitForTimeout(3_000) // window in which the redirect must NOT occur
    expect(dashboardCalls.length).toBeGreaterThan(0)
    for (const call of dashboardCalls) {
      expect(
        call.xTenant,
        'dashboard data calls must carry X-Tenant: test-com after the OIDC round-trip',
      ).toBe(WORKSPACE)
    }

    // 4. THE FIX under test (FIX-20260929-043443): the session must
    //    SURVIVE the dashboard load — the backend accepts bound sessions
    //    (claim injected at validation time) and the callback re-asserts
    //    the workspace binding, so no 401-triggered /login bounce occurs.
    const urlAfterWindow = page.url()
    expect(
      urlAfterWindow,
      'OIDC WORKSPACE SESSION BUG (FIX-20260929-043443): the user was bounced back to /login mid-load — either the workspace binding was lost during the provider round-trip (X-Tenant missing → 401) or the session was not established at all',
    ).not.toContain('/login')

    // 5. Tokens and binding intact after the window.
    const tokenAfter = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(tokenAfter).not.toBeNull()
    const slugAfter = await page.evaluate(() =>
      sessionStorage.getItem('parthenon_tenant_slug'),
    )
    expect(slugAfter).toBe(WORKSPACE)
  })
})
