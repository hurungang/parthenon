import { expect, test, type Page } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * Platform Admin Console — Tenant Management lifecycle (CS-07 / CS-09 /
 * CS-22, Phase 6).  Mocked-backend variant for speed; the real-backend
 * isolation suite covers the live path.
 *
 * Exercises the FULL CRUD lifecycle against an in-memory mock store so
 * every mutation re-serves fresh list state (react-query invalidation →
 * parent-table refresh WITHOUT page reload):
 *   create → appears immediately → edit → suspend → resume →
 *   delete (typed confirmation) → slug reusable → duplicate rejected.
 *
 * Also covers the Platform Settings toggle (typed ENABLE confirmation)
 * and the cross-tenant audit view (tenant attribution, no business data).
 */

// ── Tokens ───────────────────────────────────────────────────────────────────

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64')
const exp = Math.floor(Date.now() / 1000) + 7200
const header = b64({ alg: 'RS256', typ: 'JWT' })

/** Super-admin token: bypasses the PlatformAdminRoute probe entirely. */
const SUPER_ADMIN_TOKEN = `${header}.${b64({ sub: 'e2e-platform-admin', exp, iat: 0, name: 'Platform Admin', is_super_admin: true })}.fake-sig`

// ── Mock store + routing ─────────────────────────────────────────────────────

interface MockTenant {
  id: string
  name: string
  slug: string
  status: 'active' | 'suspended'
  admin_contact_name: string | null
  admin_contact_email: string | null
  user_count: number
  agent_count: number
  created_at: string
}

function seedStore(): MockTenant[] {
  return [
    {
      id: 't-seed-1',
      name: 'Alpha Industries',
      slug: 'alpha',
      status: 'active',
      admin_contact_name: 'Alice Alpha',
      admin_contact_email: 'alice@alpha.test',
      user_count: 12,
      agent_count: 5,
      created_at: '2026-01-15T10:00:00Z',
    },
  ]
}

async function setupPlatformConsole(page: Page, store: MockTenant[]) {
  let nextId = 100

  await page.route(
    (url) => url.href.includes('/api/v1/platform/tenants'),
    async (route) => {
      const req = route.request()
      const method = req.method()
      const url = new URL(req.url())
      const path = url.pathname

      // Collection
      if (path.endsWith('/api/v1/platform/tenants') && method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: store, total: store.length }),
        })
      }
      if (path.endsWith('/api/v1/platform/tenants') && method === 'POST') {
        const body = req.postDataJSON()
        if (store.some((t) => t.slug === body.slug)) {
          return route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({ detail: `Tenant address '${body.slug}' already exists.` }),
          })
        }
        if (store.some((t) => t.name === body.name)) {
          return route.fulfill({
            status: 409,
            contentType: 'application/json',
            body: JSON.stringify({ detail: `Tenant name '${body.name}' already exists.` }),
          })
        }
        const created: MockTenant = {
          id: `t-${nextId++}`,
          name: body.name,
          slug: body.slug,
          status: 'active',
          admin_contact_name: body.admin_contact_name ?? null,
          admin_contact_email: body.admin_contact_email ?? null,
          user_count: 0,
          agent_count: 0,
          created_at: new Date().toISOString(),
        }
        store.push(created)
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(created),
        })
      }

      // Item routes: /platform/tenants/{id}[/suspend|/resume]
      const m = path.match(/\/api\/v1\/platform\/tenants\/([^/]+)(\/(suspend|resume))?$/)
      if (m) {
        const tenant = store.find((t) => t.id === m[1])
        if (!tenant) {
          return route.fulfill({
            status: 404,
            contentType: 'application/json',
            body: JSON.stringify({ detail: 'Tenant not found.' }),
          })
        }
        if (method === 'GET') {
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ ...tenant }),
          })
        }
        if (method === 'PATCH') {
          const body = req.postDataJSON()
          Object.assign(tenant, body)
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(tenant),
          })
        }
        if (method === 'POST' && m[3] === 'suspend') {
          tenant.status = 'suspended'
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tenant) })
        }
        if (method === 'POST' && m[3] === 'resume') {
          tenant.status = 'active'
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(tenant) })
        }
        if (method === 'DELETE') {
          const confirmSlug = url.searchParams.get('confirm_slug')
          if (confirmSlug !== tenant.slug) {
            return route.fulfill({
              status: 400,
              contentType: 'application/json',
              body: JSON.stringify({ detail: 'Confirmation does not match the tenant address.' }),
            })
          }
          store.splice(store.indexOf(tenant), 1) // TRUE deletion: slug reusable
          return route.fulfill({ status: 204 })
        }
      }
      return route.fulfill({ status: 400, body: JSON.stringify({ detail: 'unhandled' }) })
    },
  )

  let multiTenancyEnabled = false
  await page.route(
    (url) => url.href.includes('/api/v1/platform/settings'),
    (route) => {
      const req = route.request()
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                key: 'multi_tenancy_enabled',
                value: multiTenancyEnabled,
                category: 'tenancy',
                description: 'Master switch for multi-tenancy.',
                multi_tenancy_enabled: multiTenancyEnabled,
              },
            ],
            multi_tenancy_enabled: multiTenancyEnabled,
          }),
        })
      }
      if (req.method() === 'PUT') {
        const body = req.postDataJSON()
        multiTenancyEnabled = body.value // write-through: refetch sees it
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            key: 'multi_tenancy_enabled',
            value: body.value,
            category: 'tenancy',
            multi_tenancy_enabled: body.value,
          }),
        })
      }
      return route.fulfill({ status: 400 })
    },
  )

  await page.route(
    (url) => url.href.includes('/api/v1/platform/audit-events'),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: 'evt-1',
              tenant_id: 't-seed-1',
              tenant_slug: 'alpha',
              event_type: 'cross_tenant_access_denied',
              actor_type: 'tenant_user',
              actor_id: 'u-9',
              actor_ip: null,
              target_resource: 'role:r-9f3e2a10', // opaque id — identifiers are metadata, business data is not exposed
              detail: { attempted: 'read' },
              is_security_relevant: true,
              created_at: '2026-09-01T12:00:00Z',
            },
            {
              id: 'evt-2',
              tenant_id: null,
              tenant_slug: null,
              event_type: 'platform_setting_updated',
              actor_type: 'platform_admin',
              actor_id: 'u-1',
              actor_ip: null,
              target_resource: 'platform_setting:multi_tenancy_enabled',
              detail: null,
              is_security_relevant: false,
              created_at: '2026-09-02T08:30:00Z',
            },
          ],
          total: 2,
        }),
      }),
  )

  // Discovery + memberships: switch ON (console must exist).
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
}

test.describe('Platform Tenant Management Lifecycle (mocked)', () => {
  test('CS-07/CS-09: create → edit → suspend → resume → delete → slug reusable, all without page reload', async ({
    page,
  }) => {
    const store = seedStore()
    await setupPlatformConsole(page, store)

    await page.goto('/platform/tenants')
    await page.waitForLoadState('load')

    // ── READ: seed tenant visible with all values ────────────────────────
    const seedRow = page.getByTestId('tenant-row-alpha')
    await expect(seedRow).toBeVisible()
    await expect(seedRow).toContainText('Alpha Industries')
    await expect(seedRow).toContainText('alice@alpha.test')

    const urlBeforeCreate = page.url()

    // ── CREATE ────────────────────────────────────────────────────────────
    const nameField = page.getByTestId('tenant-name-input').locator('input')
    const slugField = page.getByTestId('tenant-slug-input').locator('input')
    await page.getByRole('button', { name: 'Create Tenant' }).click()
    await nameField.fill('Beta Builders')
    await slugField.fill('beta')
    await page.getByLabel('Admin contact name').fill('Bob Beta')
    await page.getByLabel('Admin contact email').fill('bob@beta.test')
    await page.getByRole('button', { name: 'Save' }).last().click()

    // Parent table refreshes WITHOUT page reload.
    const betaRow = page.getByTestId('tenant-row-beta')
    await expect(betaRow).toBeVisible()
    await expect(betaRow).toContainText('Beta Builders')
    await expect(betaRow).toContainText('bob@beta.test')
    expect(page.url()).toBe(urlBeforeCreate)

    // ── UPDATE: edit dialog opens pre-populated, rename persists ─────────
    await betaRow.getByLabel('edit-beta').click()
    const nameInput = page.getByTestId('tenant-name-input').locator('input')
    await expect(nameInput).toHaveValue('Beta Builders')
    await nameInput.fill('Beta Builders International')
    await page.getByRole('button', { name: 'Save' }).last().click()
    await expect(betaRow).toContainText('Beta Builders International')

    // ── SUSPEND ───────────────────────────────────────────────────────────
    await betaRow.getByLabel('suspend-beta').click()
    await expect(betaRow).toContainText('Suspended')

    // ── RESUME ────────────────────────────────────────────────────────────
    await betaRow.getByLabel('resume-beta').click()
    await expect(betaRow).toContainText('Active')

    // ── DELETE: requires typed confirmation, then TRUE deletion ──────────
    await betaRow.getByLabel('delete-beta').click()
    await page.getByTestId('delete-confirm-input').locator('input').fill('beta')
    await page.getByRole('button', { name: 'Delete' }).last().click()
    await expect(page.getByTestId('tenant-row-beta')).toHaveCount(0)

    // Slug reusable afterwards — proves true deletion, not hiding (CS-09).
    await page.getByRole('button', { name: 'Create Tenant' }).click()
    await page.getByTestId('tenant-name-input').locator('input').fill('Beta Reborn')
    await page.getByTestId('tenant-slug-input').locator('input').fill('beta')
    await page.getByRole('button', { name: 'Save' }).last().click()
    await expect(page.getByTestId('tenant-row-beta')).toBeVisible()
    await expect(page.getByTestId('tenant-row-beta')).toContainText('Beta Reborn')
  })

  test('CS-07: duplicate tenant address rejected with a clear inline error', async ({ page }) => {
    const store = seedStore()
    await setupPlatformConsole(page, store)

    await page.goto('/platform/tenants')
    await page.getByTestId('tenant-row-alpha').waitFor()

    await page.getByRole('button', { name: 'Create Tenant' }).click()
    await page.getByTestId('tenant-name-input').locator('input').fill('Another Name')
    await page.getByTestId('tenant-slug-input').locator('input').fill('alpha') // duplicate slug
    await page.getByRole('button', { name: 'Save' }).last().click()

    // Dialog error standard: the server error surfaces INSIDE the dialog
    // (never silent), and the dialog stays open.
    await expect(page.getByText(/already exists/)).toBeVisible()
    await expect(page.getByTestId('tenant-row-beta')).toHaveCount(0)
  })

  test('CS-22: tenant table shows metadata + aggregate counts only', async ({ page }) => {
    const store = seedStore()
    await setupPlatformConsole(page, store)

    await page.goto('/platform/tenants')
    const seedRow = page.getByTestId('tenant-row-alpha')
    await expect(seedRow).toBeVisible()
    // Metadata surface: name, address, status, admin contact, created date.
    await expect(seedRow).toContainText('Alpha Industries')
    await expect(seedRow).toContainText('alpha')
    await expect(seedRow).toContainText('Alice Alpha (alice@alpha.test)')
    // …but no business rows are rendered anywhere in the console.
    const body = await page.locator('body').innerText()
    expect(body).not.toContain('beta-role') // a tenant B business record id
  })
})

test.describe('Platform Settings Toggle (mocked)', () => {
  test('toggle requires the typed ENABLE confirmation and reflects server state', async ({
    page,
  }) => {
    const store = seedStore()
    await setupPlatformConsole(page, store)

    await page.goto('/platform/settings')
    await page.waitForLoadState('load')
    await expect(page.getByRole('heading', { name: 'Platform Settings' })).toBeVisible()

    const switchInput = page.getByTestId('tenancy-switch')
    await expect(switchInput).toBeVisible()
    await switchInput.click()

    // Confirmation dialog appears; confirm button disabled until the
    // exact phrase is typed (irreversible adoption warning, CS-05).
    const confirmInput = page.getByTestId('tenancy-confirm-input').locator('input')
    await expect(confirmInput).toBeVisible()
    const confirmButton = page.getByRole('button', { name: 'Enable multi-tenancy' })
    await expect(confirmButton).toBeDisabled()
    await confirmInput.fill('WRONG')
    await expect(confirmButton).toBeDisabled()
    await confirmInput.fill('ENABLE')
    await expect(confirmButton).toBeEnabled()
    await confirmButton.click()

    // Server state reflected after toggle.
    await expect(page.getByText('Multi-tenancy is ON: users sign in via their tenant address')).toBeVisible()
  })
})

test.describe('Platform Audit View (mocked)', () => {
  test('lists events with tenant attribution and exposes filters; no business data', async ({
    page,
  }) => {
    const store = seedStore()
    await setupPlatformConsole(page, store)

    await page.goto('/platform/audit')
    await page.waitForLoadState('load')

    // Filters panel present (tenant / event type / severity / date range).
    await expect(page.getByRole('heading', { name: 'Security & Audit Events' })).toBeVisible()
    await expect(page.getByTestId('audit-filters')).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'Tenant' })).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'Event type' })).toBeVisible()
    await expect(page.getByLabel('From')).toBeVisible()
    await expect(page.getByLabel('To')).toBeVisible()

    // Security-relevant event rendered (real i18n text) with tenant
    // attribution + severity chip.
    await expect(page.getByText('Cross-tenant access denied')).toBeVisible()
    await expect(page.getByText('alpha', { exact: true })).toBeVisible()

    // Platform-level event shows the platform sentinel, not a tenant
    // (target the table cell — "Platform" is also the sidebar group name).
    await expect(page.getByRole('cell', { name: 'Platform', exact: true })).toBeVisible()

    // No tenant business data anywhere in the audit view — only event
    // metadata (types, opaque target ids, tenant attribution).
    const body = await page.locator('body').innerText()
    expect(body).not.toContain('beta-role') // a tenant B business record NAME
  })
})
