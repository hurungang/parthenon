import { test, expect, type Page } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * E2E tests for `RolePolicyDialog` and the batch save endpoint it drives
 * (`PUT /user-roles/{role_id}/policies/batch`).
 *
 * Canonical mocked E2E: the backend/Keycloak are stopped, so every API call
 * is fulfilled from `page.route` mocks and the dialog contract is exercised
 * through the UI:
 *  - the resource-type catalogue is namespaced (`module::submodule`) only;
 *  - a 403 on batch save surfaces `PermissionDeniedAlert` inside the dialog
 *    (Dialog Error Handling Standard) and keeps the dialog open;
 *  - client-side JSON validation rejects flat module values;
 *  - an empty / wildcard policy set is accepted and saved.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

const MOCK_RESOURCE_TYPES = [
  { resource_type: 'agent::roles', actions: ['read', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::management', actions: ['create', 'read', 'update', 'delete', 'execute'], module_group: 'agent' },
  { resource_type: 'integration::mcp_hub', actions: ['create', 'read', 'update', 'delete', 'execute', 'manage'], module_group: 'integration' },
  { resource_type: 'system::permissions', actions: ['create', 'read', 'update', 'delete', 'manage', 'approve', 'reject'], module_group: 'system' },
]

const MOCK_ROLE_LIST = [
  {
    id: 'role-rpd-001',
    name: 'Dialog Test Role',
    description: 'Role for dialog testing',
    is_active: true,
    is_system: false,
    role_type: 'user_defined',
    policy_count: 2,
    user_assignment_count: 1,
    group_assignment_count: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
]

const MOCK_TAGS = [
  {
    id: 'tag-001',
    key: 'environment',
    scope: 'global',
    allowed_values: [
      { id: 'v1', tag_definition_id: 'tag-001', value: 'production', created_at: '' },
      { id: 'v2', tag_definition_id: 'tag-001', value: 'staging', created_at: '' },
    ],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  },
]

const MOCK_ROLE_DETAIL = {
  ...MOCK_ROLE_LIST[0],
  policy_statements: [
    {
      id: 'rpd-policy-1',
      effect: 'allow',
      module: 'agent::roles',
      actions: [{ id: 'a1', action: 'read' }, { id: 'a2', action: 'manage' }],
      resources: [],
      tag_conditions: [],
      created_at: '2024-01-01T00:00:00Z',
    },
    {
      id: 'rpd-policy-2',
      effect: 'deny',
      module: 'system::permissions',
      actions: [{ id: 'a3', action: 'manage' }],
      resources: [],
      tag_conditions: [{ id: 'tc1', tag_key: 'env', tag_value: 'prod' }],
      created_at: '2024-01-01T00:00:00Z',
    },
  ],
}

// ── Setup helpers ────────────────────────────────────────────────────────────

async function setupBaseMocks(page: Page) {
  // Resource types catalogue
  await page.route(/\/api\/v1\/policy\/resource-types$/, (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_RESOURCE_TYPES) })
  })

  // Tags
  await page.route(/\/api\/v1\/user-tags\/definitions(\?.*)?$/, (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_TAGS) })
  })

  // Groups
  await page.route(/\/api\/v1\/user-groups(\?.*)?$/, (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
  })

  // Platform users
  await page.route(/\/api\/v1\/platform-users(\?.*)?$/, (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
  })

  // Roles: list, detail and batch save
  await page.route(/\/api\/v1\/user-roles.*$/, (route) => {
    const url = route.request().url()
    const method = route.request().method()

    if (url.match(/\/user-roles\/[^/]+\/policies\/batch$/) && method === 'PUT') {
      const body = JSON.parse(route.request().postData() || '{}')
      const policies = (body.policies || []).map((p: Record<string, unknown>, i: number) => ({
        id: `saved-policy-${i}`,
        effect: p.effect || 'allow',
        module: p.module || '',
        actions: ((p.actions as { action: string }[] | undefined) ?? []).map((a, idx) => ({
          id: `a-${idx}`,
          action: a.action,
        })),
        resources: p.resources || [],
        tag_conditions: p.tag_conditions || [],
        created_at: '2024-01-01T00:00:00Z',
      }))
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(policies) })
      return
    }

    if (url.match(/\/user-roles\/[^/]+$/) && method === 'GET') {
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_ROLE_DETAIL) })
      return
    }

    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_ROLE_LIST) })
  })
}

/** Opens the Roles tab and the policy dialog for the mocked role. */
async function openPolicyDialog(page: Page) {
  await page.goto('/user-permissions')
  await page.waitForLoadState('load')

  await page.getByRole('tab', { name: 'Roles' }).waitFor({ state: 'visible', timeout: 15000 })
  await page.getByRole('tab', { name: 'Roles' }).click()

  const row = page.getByRole('row').filter({ hasText: 'Dialog Test Role' }).first()
  await row.getByRole('button', { name: 'Edit Policy' }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.locator('.MuiCard-root').first()).toBeVisible({ timeout: 10000 })
  return dialog
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('RolePolicyDialog E2E', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupBaseMocks(page)
  })

  test('roles page renders with mocked namespaced data', async ({ page }) => {
    await page.goto('/user-permissions')
    await page.waitForLoadState('load')
    await page.getByRole('tab', { name: 'Roles' }).click()

    await expect(page.getByText('Dialog Test Role')).toBeVisible({ timeout: 10000 })
    expect(await page.title()).toBeTruthy()
  })

  test('resource type catalogue exposes namespaced (module::submodule) entries only', async ({
    page,
  }) => {
    const dialog = await openPolicyDialog(page)

    await dialog.getByRole('button', { name: 'Add Policy' }).click()
    const newCard = dialog.locator('.MuiCard-root').nth(2)

    // Open the free-solo resource type dropdown
    await newCard.getByLabel('Resource Type').click()
    await expect(page.getByRole('option').first()).toBeVisible()

    const options = await page.getByRole('option').allInnerTexts()
    const values = options.map((o) => o.trim()).filter(Boolean)

    // Every option is namespaced (wildcards included) — no legacy flat values
    for (const value of values) {
      expect(value).toContain('::')
      expect(['agent', 'role', 'permissions']).not.toContain(value)
    }

    expect(values).toEqual(expect.arrayContaining(['agent::roles', 'system::permissions']))
    // The manifest covers all three module groups
    expect(values.filter((v) => v.startsWith('agent::')).length).toBeGreaterThan(0)
    expect(values.filter((v) => v.startsWith('integration::')).length).toBeGreaterThan(0)
    expect(values.filter((v) => v.startsWith('system::')).length).toBeGreaterThan(0)
  })

  test('403 on batch save shows PermissionDeniedAlert inside the dialog and keeps it open', async ({
    page,
  }) => {
    // Higher priority than the base mock (registered later wins)
    await page.route(/\/api\/v1\/user-roles\/[^/]+\/policies\/batch$/, (route) =>
      route.fulfill({
        status: 403,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          detail: {
            detail: "Missing permission 'manage' on system::permissions",
            required_permission: {
              resource_type: 'system::permissions',
              action: 'manage',
              resource_id: null,
            },
          },
        }),
      }),
    )

    const dialog = await openPolicyDialog(page)

    await dialog.getByRole('button', { name: 'Save All Policies' }).click()

    const alert = dialog.locator('[role="alert"]').filter({ hasText: /Permission Denied:/ })
    await expect(alert).toBeVisible({ timeout: 10000 })

    const alertText = (await alert.textContent()) ?? ''
    expect(alertText).toContain('Action: manage')
    expect(alertText).toContain('Resource: system::permissions')
    await expect(alert.locator('a[href="/permissions/access-requests"]')).toBeVisible()

    // Standard: the dialog stays open for correction
    await expect(dialog).toBeVisible()
  })

  test('JSON view rejects a flat (non-namespaced) resource type', async ({ page }) => {
    const dialog = await openPolicyDialog(page)

    await dialog.getByRole('button', { name: 'JSON' }).click()
    await dialog.locator('textarea').first().fill(
      JSON.stringify(
        {
          policies: [
            {
              module: 'agent', // flat value, not namespaced
              effect: 'allow',
              actions: [{ action: 'read' }],
              resources: [],
              tag_conditions: [],
            },
          ],
        },
        null,
        2,
      ),
    )

    await dialog.getByRole('button', { name: 'Save All Policies' }).click()

    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(/Invalid module format/)).toBeVisible({ timeout: 5000 })
  })

  test('saving an empty policy set is accepted and closes the dialog', async ({ page }) => {
    const batchBodies: { policies: unknown[] }[] = []
    await page.route(/\/api\/v1\/user-roles\/[^/]+\/policies\/batch$/, (route) => {
      batchBodies.push(JSON.parse(route.request().postData() || '{}'))
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    })

    const dialog = await openPolicyDialog(page)

    // Delete every policy card (second icon button on each card)
    const cards = dialog.locator('.MuiCard-root')
    while ((await cards.count()) > 0) {
      await cards.first().locator('button').nth(1).click()
    }
    await expect(dialog.getByText('No policies defined for this role.')).toBeVisible()

    await dialog.getByRole('button', { name: 'Save All Policies' }).click()

    await expect(dialog).not.toBeVisible({ timeout: 5000 })
    expect(batchBodies).toHaveLength(1)
    expect(batchBodies[0].policies).toEqual([])
  })

  test('wildcard module values are accepted by the client validation and saved', async ({
    page,
  }) => {
    const batchBodies: { policies: { module: string }[] }[] = []
    await page.route(/\/api\/v1\/user-roles\/[^/]+\/policies\/batch$/, (route) => {
      batchBodies.push(JSON.parse(route.request().postData() || '{}'))
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    })

    const dialog = await openPolicyDialog(page)

    await dialog.getByRole('button', { name: 'JSON' }).click()
    await dialog.locator('textarea').first().fill(
      JSON.stringify(
        {
          policies: [
            {
              module: '*::*',
              effect: 'allow',
              actions: [{ action: 'read' }],
              resources: [],
              tag_conditions: [],
            },
          ],
        },
        null,
        2,
      ),
    )

    await dialog.getByRole('button', { name: 'Save All Policies' }).click()

    await expect(dialog).not.toBeVisible({ timeout: 5000 })
    expect(batchBodies).toHaveLength(1)
    expect(batchBodies[0].policies[0].module).toBe('*::*')
  })
})
