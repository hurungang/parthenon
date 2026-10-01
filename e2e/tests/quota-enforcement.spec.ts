import { expect, test, type Page } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * Quota enforcement UX (Phase 10, CS-35/CS-41 UI side).
 * Mocked-backend variant: the enforcement itself (403 + structured
 * payload at Control Center) is proven by the backend suites; this spec
 * proves the TENANT UI renders the structured feedback as-is and that
 * raising the license unblocks the action — without any page reload.
 *
 * - A blocked invitation shows the full contract: tier, limit, current
 *   usage and the upgrade path (the shared QuotaBlockedAlert).
 * - After the license is raised, the same invitation succeeds (token
 *   shown once) and the block disappears.
 * - The tenant usage panel mirrors tier + limits for the same tenant.
 */

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64')
const exp = Math.floor(Date.now() / 1000) + 7200
const header = b64({ alg: 'RS256', typ: 'JWT' })
const SUPER_ADMIN_TOKEN = `${header}.${b64({
  sub: 'e2e-tenant-admin',
  exp,
  iat: 0,
  name: 'Tenant Admin',
  is_super_admin: true,
})}.fake-sig`

const FREE_USAGE = {
  tier: 'free',
  max_users: 10,
  max_agent_types: 5,
  monthly_agent_executions: 100,
  users: 10,
  agent_types: 3,
  executions_this_month: 42,
}

const TEAM_USAGE = {
  ...FREE_USAGE,
  tier: 'team',
  max_users: 25,
  users: 10,
}

async function setupTenantWorkspace(page: Page) {
  // License state flips on demand (the platform admin raised the tier).
  let licenseRaised = false

  // Lowest-priority catch-all FIRST: any unmocked API call is fulfilled
  // instead of hitting the real backend (a stray 401 would trip the axios
  // interceptor → token cleared → redirect mid-test).
  await mockApiCatchAllProxyAware(page)

  await page.route(
    (url) => url.href.includes('/api/v1/tenant/invitations') &&
      !url.href.includes('revoke'),
    async (route) => {
      if (route.request().method() === 'POST') {
        if (!licenseRaised) {
          // The Control Center quota gate: structured 403 contract.
          return route.fulfill({
            status: 403,
            contentType: 'application/json',
            body: JSON.stringify({
              detail: {
                code: 'quota_exhausted',
                quota_type: 'users',
                tier: 'free',
                limit: 10,
                used: 10,
                upgrade_path:
                  'Upgrade your plan (contact your platform administrator) to raise this limit',
              },
            }),
          })
        }
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            invitation_id: 'inv-1',
            email: 'newbie@acme.test',
            tenant_role: 'member',
            status: 'pending',
            accept_token: 'ONE-TIME-TOKEN-123',
          }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
    },
  )

  await page.route(
    (url) => url.href.includes('/api/v1/tenant/usage'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(licenseRaised ? TEAM_USAGE : FREE_USAGE),
      }),
  )

  await page.route(
    (url) => url.href.includes('/api/v1/tenant/members'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              membership_id: 'm-1',
              user_id: 'u-1',
              display_name: 'Root Owner',
              email: 'root@acme.test',
              tenant_role: 'tenant_admin',
              status: 'active',
              is_default: true,
              is_root: true,
            },
          ],
          total: 1,
        }),
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
          is_onboarded: true,
          your_role: 'tenant_admin',
          is_root: true,
        }),
      }),
  )

  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ multi_tenancy_enabled: true, items: [] }),
      }),
  )
  await page.route(
    (url) => url.href.includes('/api/v1/auth/tenant') && !url.href.includes('tenant-memberships'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ multi_tenancy_enabled: true, tenant: null }),
      }),
  )

  await page.addInitScript((token) => {
    localStorage.setItem('access_token', token)
  }, SUPER_ADMIN_TOKEN)
  await standardSetup(page)

  return {
    raiseLicense: () => {
      licenseRaised = true
    },
  }
}

test.describe('Quota Enforcement (mocked)', () => {
  test('CS-35/CS-41: blocked invite shows tier/limit/usage/upgrade; unblocked once the license is raised', async ({
    page,
  }) => {
    const env = await setupTenantWorkspace(page)

    await page.goto('/tenant/members')
    await page.waitForLoadState('load')
    await expect(page.getByText('Root Owner')).toBeVisible()

    // ── Blocked: the invite surfaces the structured contract ──────────
    await page.getByRole('button', { name: 'Invite member' }).click()
    await page.getByLabel('Email').fill('newbie@acme.test')
    await page.getByRole('button', { name: 'Create invitation' }).click()

    const alert = page.getByTestId('quota-blocked-alert')
    await expect(alert).toBeVisible()
    // Tier + quota type + current usage + limit (rendered as-is).
    await expect(alert).toContainText('Action blocked — plan limit reached')
    await expect(alert).toContainText('Your Free plan allows up to 10 members')
    await expect(alert).toContainText('you are currently at 10')
    await expect(alert).toContainText('10 / 10 used')
    // The upgrade path.
    await expect(alert).toContainText(
      'Upgrade path: contact your platform administrator to raise this limit.',
    )

    // ── License raised: the SAME action now succeeds, no page reload ──
    env.raiseLicense()
    await page.getByRole('button', { name: 'Create invitation' }).click()
    await expect(page.getByText(/ONE-TIME-TOKEN-123/)).toBeVisible()
    await expect(page.getByTestId('quota-blocked-alert')).toHaveCount(0)
  })

  test('CS-34: the tenant usage panel mirrors tier and limits', async ({
    page,
  }) => {
    await setupTenantWorkspace(page)

    await page.goto('/tenant/settings')
    await page.waitForLoadState('load')

    const panel = page.getByTestId('license-usage-panel')
    await expect(panel).toBeVisible()
    await expect(page.getByTestId('license-tier-chip')).toHaveText('Free')
    await expect(panel).toContainText('No license assigned — built-in free-tier limits apply')
    await expect(panel).toContainText('Members (users)')
    await expect(panel).toContainText('10 of 10')
    await expect(panel).toContainText('Agent executions this month')
    await expect(panel).toContainText('42 of 100')
  })
})
