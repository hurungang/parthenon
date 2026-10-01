import { expect, test, type Page } from '@playwright/test'
import { mockHealth, mockIdentityStatus, mockTelemetry } from './_helpers'

/**
 * Self-serve sign-up journey (Phase 10, CS-26/CS-27/CS-28/CS-29 UI side).
 * Mocked-backend variant for speed; the real-backend variant proves the
 * atomic registration against the migrated database.
 *
 * - CS-29: sign-up entry link absent from the login page when the tenancy
 *   switch is off; /signup renders inert (no form) and discovery hides
 *   the tenant.
 * - CS-26: switch on → login page shows the entry link → two-step wizard
 *   (account → organization) → successful registration stores the
 *   session and lands the new ROOT user in guided onboarding.
 * - CS-27: duplicate email blocked with a clear inline error.
 * - CS-28: a user who already owns a tenant is blocked with the
 *   one-tenant-per-user message.
 */

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64')
const exp = Math.floor(Date.now() / 1000) + 7200
const header = b64({ alg: 'HS256', typ: 'JWT' })

/** Tenant-bound platform-account session returned by the mock register. */
function platformAccountToken(slug: string) {
  return `${header}.${b64({
    sub: `platform_account:${slug}`,
    email: `owner-${slug}@test.dev`,
    name: 'Owner',
    platform_account: true,
    platform_role: 'tenant_admin',
    tenant: slug,
    tenant_id: `t-${slug}`,
    tenant_access: 'tenant',
    exp,
    iat: 0,
  })}.fake-sig`
}

interface Registration {
  email: string
  slug: string
  name: string
  password: string
  /** Self-serve registrations are owners (root memberships). */
  owns_tenant: boolean
}

/**
 * Mocks the PUBLIC auth surface + the tenant workspace read APIs a fresh
 * root hits after landing in onboarding.  Rejection semantics mirror the
 * real backend: an existing OWNER re-registering receives the dedicated
 * one-tenant-per-user message; any other duplicate email receives the
 * generic already-exists error.
 */
async function setupSignup(page: Page, enabled: boolean, store: Registration[]) {
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant') && !url.href.includes('tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ multi_tenancy_enabled: enabled, tenant: null }),
      }),
  )

  await page.route(
    (url) => url.href.includes('/api/v1/auth/register'),
    async (route) => {
      const body = route.request().postDataJSON()
      const existingEmail = store.find((r) => r.email === body.email.toLowerCase())
      if (existingEmail) {
        const detail = existingEmail.owns_tenant
          ? 'Each user can own only one organization'
          : 'An account with this email already exists'
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail }),
        })
      }
      if (store.some((r) => r.slug === body.slug)) {
        return route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: `The address '${body.slug}' is already taken`,
          }),
        })
      }
      store.push({
        email: body.email.toLowerCase(),
        slug: body.slug,
        name: body.organization_name,
        password: body.password,
        owns_tenant: true,
      })
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tenant_id: `t-${body.slug}`,
          name: body.organization_name,
          slug: body.slug,
          your_role: 'tenant_admin',
          is_root: true,
          access_token: platformAccountToken(body.slug),
          token_type: 'bearer',
        }),
      })
    },
  )

  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant-memberships'),
    (route) => {
      // After a successful registration the fresh root's membership is
      // listed (drives the session gate / workspace resolution).
      const owner = [...store].reverse().find((r) => r.owns_tenant)
      const items = owner
        ? [
            {
              tenant_id: `t-${owner.slug}`,
              tenant_slug: owner.slug,
              tenant_name: owner.name,
              tenant_role: 'tenant_admin',
              is_default: true,
            },
          ]
        : []
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ multi_tenancy_enabled: enabled, items }),
      })
    },
  )

  // Tenant workspace reads the fresh root hits after the redirect.
  await page.route(
    (url) => url.href.includes('/api/v1/tenant/usage'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tier: 'free',
          max_users: 10,
          max_agent_types: 5,
          monthly_agent_executions: 100,
          users: 1,
          agent_types: 0,
          executions_this_month: 0,
        }),
      }),
  )
  await page.route(
    (url) => url.href.includes('/api/v1/tenant/onboarding'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tenant_id: 't-1', is_onboarded: false }),
      }),
  )
  await page.route(
    (url) => url.href.includes('/api/v1/tenant/settings'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          tenant_id: 't-1',
          slug: 'acme',
          name: 'Acme Corp',
          admin_contact_name: null,
          admin_contact_email: null,
          is_onboarded: false,
          your_role: 'tenant_admin',
          is_root: true,
        }),
      }),
  )
  await page.route(
    (url) => url.href.includes('/api/v1/tenant/members'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      }),
  )

  // Public-surface setup: health/telemetry/identity-status mocks but NO
  // injected token — /login must render for anonymous visitors (the
  // sign-up session is stored by the app itself after registration).
  await mockHealth(page)
  await mockTelemetry(page)
  await mockIdentityStatus(page)
}

test.describe('Self-Serve Sign-Up (mocked)', () => {
  test('CS-29: switch off — no entry link on login, /signup inert', async ({
    page,
  }) => {
    const store: Registration[] = []
    await setupSignup(page, false, store)

    // The login page hides the sign-up entry link when the switch is off.
    await page.goto('/login')
    await page.waitForLoadState('load')
    await expect(page.getByTestId('signup-entry-link')).toHaveCount(0)

    // /signup renders inert: an explicit unavailable note, no form.
    await page.goto('/signup')
    await expect(page.getByText('Self-serve registration is not available on this platform')).toBeVisible()
    await expect(page.getByTestId('signup-email-input')).toHaveCount(0)
    await expect(page.getByTestId('signup-submit')).toHaveCount(0)
  })

  test('CS-26: full journey — entry link → wizard → lands in onboarding as root', async ({
    page,
  }) => {
    const store: Registration[] = []
    await setupSignup(page, true, store)

    // Entry point: the login page advertises self-serve sign-up.
    await page.goto('/login')
    await page.waitForLoadState('load')
    await expect(page.getByTestId('signup-entry-link')).toBeVisible()
    await page.getByTestId('signup-entry-link').click()
    await expect(page).toHaveURL(/\/signup$/)

    // Step 1 — account.
    await page.getByTestId('signup-email-input').locator('input').fill('owner-acme@test.dev')
    await page.getByTestId('signup-password-input').locator('input').fill('Sup3rSecret')
    await page.getByLabel('Confirm password').fill('Sup3rSecret')
    await page.getByRole('button', { name: 'Continue' }).click()

    // Step 2 — organization (address auto-derived from the name).
    await expect(page.getByTestId('signup-step-organization')).toBeVisible()
    await page.getByLabel('Organization name').fill('Acme Corp')
    await expect(page.getByLabel('Organization address')).toHaveValue('acme-corp')
    await page.getByTestId('signup-submit').click()

    // Lands in guided onboarding as the tenant root — no platform-admin
    // action involved.
    await expect(page).toHaveURL(/\/tenant\/onboarding/)
    await expect(
      page.getByRole('heading', { name: 'Welcome — set up your organization' }),
    ).toBeVisible()
    await expect(page.getByText('Invite users')).toBeVisible()
  })

  test('CS-27: duplicate email blocked with a clear inline error', async ({
    page,
  }) => {
    const store: Registration[] = [
      {
        email: 'member@acme.test',
        slug: 'existing-slug',
        name: 'Existing',
        password: 'Sup3rSecret',
        owns_tenant: false, // invited member — no owned tenant
      },
    ]
    await setupSignup(page, true, store)

    await page.goto('/signup')
    await page.getByTestId('signup-email-input').locator('input').fill('member@acme.test')
    await page.getByTestId('signup-password-input').locator('input').fill('Sup3rSecret')
    await page.getByLabel('Confirm password').fill('Sup3rSecret')
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Organization name').fill('Acme Two')
    await page.getByTestId('signup-submit').click()

    await expect(page.getByTestId('signup-error')).toContainText(
      'An account with this email already exists',
    )
    // Still on the sign-up page — no session, no redirect.
    await expect(page).toHaveURL(/\/signup$/)
  })

  test('CS-28: one-tenant-per-user message on a second registration attempt', async ({
    page,
  }) => {
    const store: Registration[] = []
    await setupSignup(page, true, store)

    // First registration succeeds.
    await page.goto('/signup')
    await page.getByTestId('signup-email-input').locator('input').fill('owner-glob@test.dev')
    await page.getByTestId('signup-password-input').locator('input').fill('Sup3rSecret')
    await page.getByLabel('Confirm password').fill('Sup3rSecret')
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Organization name').fill('Globex')
    await page.getByTestId('signup-submit').click()
    await expect(page).toHaveURL(/\/tenant\/onboarding/)

    // The same person tries again with a new organization: blocked.
    await page.goto('/signup')
    await page.getByTestId('signup-email-input').locator('input').fill('owner-glob@test.dev')
    await page.getByTestId('signup-password-input').locator('input').fill('Sup3rSecret')
    await page.getByLabel('Confirm password').fill('Sup3rSecret')
    await page.getByRole('button', { name: 'Continue' }).click()
    await page.getByLabel('Organization name').fill('Globex Two')
    await page.getByTestId('signup-submit').click()

    await expect(
      page.getByText('Each user can own only one organization'),
    ).toBeVisible()
  })
})
