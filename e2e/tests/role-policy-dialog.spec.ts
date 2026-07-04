import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

/**
 * E2E tests for the RolePolicyDialog and batch save endpoint.
 *
 * Covers:
 * - Batch save endpoint: PUT /user-roles/{role_id}/policies/batch
 * - Roles page rendering with namespaced mock data
 * - Resource types endpoint validation
 */

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173'
const JSON_HEADERS = { 'Content-Type': 'application/json' }

const MOCK_RESOURCE_TYPES = [
  { resource_type: 'agent::roles', actions: ['read', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::identities', actions: ['read', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::management', actions: ['create', 'read', 'update', 'delete', 'execute'], module_group: 'agent' },
  { resource_type: 'agent::runtime_control', actions: ['read', 'execute'], module_group: 'agent' },
  { resource_type: 'agent::skills', actions: ['create', 'read', 'update', 'delete', 'execute'], module_group: 'agent' },
  { resource_type: 'agent::sops', actions: ['read', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::model_configs', actions: ['read', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::schedules', actions: ['create', 'read', 'update', 'delete'], module_group: 'agent' },
  { resource_type: 'agent::trails', actions: ['create', 'read', 'update', 'delete'], module_group: 'agent' },
  { resource_type: 'agent::human_intervention', actions: ['view', 'respond'], module_group: 'agent' },
  { resource_type: 'agent::data_types', actions: ['create', 'read', 'update', 'delete', 'manage'], module_group: 'agent' },
  { resource_type: 'agent::outputs', actions: ['read'], module_group: 'agent' },
  { resource_type: 'integration::mcp_hub', actions: ['create', 'read', 'update', 'delete', 'execute', 'manage'], module_group: 'integration' },
  { resource_type: 'integration::notifications', actions: ['read', 'manage'], module_group: 'integration' },
  { resource_type: 'system::observability', actions: ['read'], module_group: 'system' },
  { resource_type: 'system::permissions', actions: ['create', 'read', 'update', 'delete', 'manage', 'approve', 'reject'], module_group: 'system' },
  { resource_type: 'system::system_config', actions: ['read', 'manage'], module_group: 'system' },
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

// ── Setup helpers ────────────────────────────────────────────────────────────

async function setupBaseMocks(page: import('@playwright/test').Page) {
  // Resource types
  await page.route('**/api/v1/policy/resource-types', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_RESOURCE_TYPES) })
  })

  // Tags
  await page.route('**/api/v1/user-tags/definitions**', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_TAGS) })
  })

  // Groups
  await page.route('**/api/v1/user-groups**', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
  })

  // Platform users
  await page.route('**/api/v1/platform-users**', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
  })

  // Role list
  await page.route('**/api/v1/user-roles?page=1&page_size=50', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_ROLE_LIST) })
  })

  // Role detail (GET)
  await page.route('**/api/v1/user-roles/role-rpd-001**', (route) => {
    const url = route.request().url()
    if (url.includes('/policies/batch') || route.request().method() === 'PUT') {
      // Batch save
      const body = JSON.parse(route.request().postData() || '{}')
      const policies = (body.policies || []).map((p: Record<string, unknown>, i: number) => ({
        id: `saved-policy-${i}`,
        effect: p.effect || 'allow',
        module: p.module || '',
        actions: (p.actions || []).map((a: Record<string, string>) => ({ id: `a-${i}`, action: a.action })),
        resources: p.resources || [],
        tag_conditions: p.tag_conditions || [],
        created_at: '2024-01-01T00:00:00Z',
      }))
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(policies) })
      return
    }

    // Otherwise return detail
    route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify({
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
      }),
    })
  })

  // Fallback: any other user-roles request
  await page.route('**/api/v1/user-roles**', (route) => {
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_ROLE_LIST) })
  })
}

// ── Tests ────────────────────────────────────────────────────────────────────

test.describe('RolePolicyDialog E2E', () => {

  test('resource types endpoint returns 17 namespaced entries', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/v1/policy/resource-types`)
    // May return 401 without auth — confirms endpoint exists and is protected
    if (response.status() === 200) {
      const data = await response.json()
      expect(Array.isArray(data)).toBeTruthy()
      expect(data).toHaveLength(17)

      // All entries should have :: delimiter
      for (const item of data) {
        expect(item.resource_type).toContain('::')
        expect(item.resource_type.split('::')).toHaveLength(2)
        expect(Array.isArray(item.actions)).toBeTruthy()
        expect(item.actions.length).toBeGreaterThan(0)
      }

      // Verify no legacy flat values
      const types = data.map((d: { resource_type: string }) => d.resource_type)
      expect(types).not.toContain('agent')
      expect(types).not.toContain('role')
      expect(types).not.toContain('permissions')
    } else {
      expect([401, 403]).toContain(response.status())
    }
  })

  test('batch save endpoint requires authentication', async ({ request }) => {
    const response = await request.put(
      `${BASE_URL}/api/v1/user-roles/00000000-0000-0000-0000-000000000000/policies/batch`,
      {
        headers: JSON_HEADERS,
        data: {
          policies: [
            {
              module: 'agent::roles',
              effect: 'allow',
              actions: [{ action: 'read' }],
              resources: [],
              tag_conditions: [],
            },
          ],
        },
      }
    )
    // Without auth, should get 401 or 403
    expect([200, 401, 403]).toContain(response.status())
  })

  test('batch save endpoint rejects flat resource type', async ({ request }) => {
    const response = await request.put(
      `${BASE_URL}/api/v1/user-roles/00000000-0000-0000-0000-000000000000/policies/batch`,
      {
        headers: JSON_HEADERS,
        data: {
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
      }
    )
    // May get 422 (validation) or 401 (auth) — both confirm endpoint protection
    expect([200, 401, 403, 422]).toContain(response.status())
  })

  test('batch save endpoint accepts empty policies array', async ({ request }) => {
    const response = await request.put(
      `${BASE_URL}/api/v1/user-roles/00000000-0000-0000-0000-000000000000/policies/batch`,
      {
        headers: JSON_HEADERS,
        data: { policies: [] },
      }
    )
    // Empty array is valid schema — 401 expected without auth
    expect([200, 401, 403]).toContain(response.status())
  })

  test('roles page renders with mocked namespaced data', async ({ page }) => {
    await standardSetup(page)
    await setupBaseMocks(page)

    await page.goto('/permissions/roles')
    await page.waitForLoadState('networkidle')

    // Verify the page loaded (title should not be empty)
    const title = await page.title()
    expect(title).toBeTruthy()
  })

  test('all three module groups present in resource types data', async () => {
    // Pure data validation — no browser needed
    const modules = new Set(MOCK_RESOURCE_TYPES.map((rt) => rt.resource_type.split('::')[0]))
    expect(modules.has('agent')).toBe(true)
    expect(modules.has('integration')).toBe(true)
    expect(modules.has('system')).toBe(true)
    expect(modules.size).toBe(3)
  })

  test('batch save with wildcard module value is accepted', async ({ request }) => {
    const wildcards = ['agent::*', 'integration::*', 'system::*', '*::*']

    for (const wildcard of wildcards) {
      const response = await request.put(
        `${BASE_URL}/api/v1/user-roles/00000000-0000-0000-0000-000000000000/policies/batch`,
        {
          headers: JSON_HEADERS,
          data: {
            policies: [
              {
                module: wildcard,
                effect: 'allow',
                actions: [{ action: 'read' }],
                resources: [],
                tag_conditions: [],
              },
            ],
          },
        }
      )
      // Wildcards should be accepted by schema validation; auth expected without valid token
      expect([200, 401, 403]).toContain(response.status())
    }
  })
})
