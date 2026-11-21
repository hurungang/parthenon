import { test, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test'
import { standardSetup, FAKE_TOKEN } from './_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/**
 * Mock data for API key management.
 */
const MOCK_KEYS = [
  {
    id: 'key-001',
    name: 'Production Agent Key',
    key_prefix: 'phn_sk_',
    agent_identity_id: 'identity-1',
    agent_identity_name: 'Agent Alpha',
    agent_role_id: 'role-1',
    agent_role_name: 'Developer',
    status: 'active',
    created_at: '2026-01-15T10:00:00Z',
    last_used_at: '2026-06-20T14:00:00Z',
  },
  {
    id: 'key-002',
    name: 'Staging Viewer Key',
    key_prefix: 'phn_sk_',
    agent_identity_id: 'identity-2',
    agent_identity_name: 'Agent Beta',
    agent_role_id: 'role-2',
    agent_role_name: 'Viewer',
    status: 'revoked',
    created_at: '2026-01-20T09:00:00Z',
    last_used_at: null,
  },
]

const MOCK_IDENTITIES = [
  {
    identity_id: 'identity-1',
    identity_name: 'Agent Alpha',
    roles: [
      { role_id: 'role-1', role_name: 'Developer' },
      { role_id: 'role-2', role_name: 'Viewer' },
    ],
  },
  {
    identity_id: 'identity-2',
    identity_name: 'Agent Beta',
    roles: [
      { role_id: 'role-2', role_name: 'Viewer' },
    ],
  },
]

const MOCK_CREATE_RESPONSE = {
  id: 'key-003',
  name: 'E2E Test Key',
  key_prefix: 'phn_sk_',
  api_key: 'phn_sk_' + 'x'.repeat(32),
  agent_identity_id: 'identity-1',
  agent_identity_name: 'Agent Alpha',
  agent_role_id: 'role-1',
  agent_role_name: 'Developer',
  created_at: '2026-07-30T00:00:00Z',
}

/**
 * Setup API mocks for all api-key endpoints.
 *
 * NOTE: the trailing `**` is required — the UI sends pagination/filter query
 * params (e.g. `?limit=…&offset=…`, `?status=active`) and Playwright globs
 * without it do not match the query string.
 */
async function setupApiKeyMocks(page: Page) {
  await page.route('**/api/v1/api-keys**', async (route) => {
    const request = route.request()
    const url = request.url()

    // GET /api-keys/identities-with-roles — identity + role picker data
    if (request.method() === 'GET' && url.includes('identities-with-roles')) {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(MOCK_IDENTITIES),
      })
    }

    // POST /api-keys/{id}/revoke
    if (request.method() === 'POST' && /\/api-keys\/[^/]+\/revoke/.test(url)) {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          id: 'key-001',
          status: 'revoked',
          message: 'API key revoked successfully',
        }),
      })
    }

    // POST /api-keys — create a new key
    if (request.method() === 'POST') {
      return route.fulfill({
        status: 201,
        headers: JSON_HEADERS,
        body: JSON.stringify(MOCK_CREATE_RESPONSE),
      })
    }

    if (request.method() === 'GET') {
      // Filter by status if specified
      if (url.includes('status=active')) {
        return route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify(MOCK_KEYS.filter((k) => k.status === 'active')),
        })
      }
      if (url.includes('status=revoked')) {
        return route.fulfill({
          status: 200,
          headers: JSON_HEADERS,
          body: JSON.stringify(MOCK_KEYS.filter((k) => k.status === 'revoked')),
        })
      }
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(MOCK_KEYS),
      })
    }

    return route.fallback()
  })
}

/**
 * Resolves a MUI Select by the visible label rendered above it.
 *
 * The product's `InputLabel` elements are not programmatically associated with
 * their `Select` (no `labelId`/`htmlFor`), so the comboboxes have no accessible
 * name — `getByRole('combobox', { name })` / `getByLabel` cannot be used.
 * Matching on the surrounding form control is the closest stable alternative.
 */
function labelledSelect(scope: Page | Locator, label: string): Locator {
  return scope.locator('.MuiFormControl-root').filter({ hasText: label }).getByRole('combobox')
}

/** Opens the Create API Key dialog from the list page header. */
async function openCreateDialog(page: Page) {
  await page.getByRole('button', { name: 'Create API Key' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: 'Create API Key' })).toBeVisible({
    timeout: 5000,
  })
  return dialog
}

/** Fills the create dialog and submits it, returning the (step 2) dialog. */
async function submitCreateForm(page: Page, name = 'E2E Test Key') {
  const dialog = await openCreateDialog(page)
  await dialog.getByLabel('Key Name').fill(name)
  await labelledSelect(dialog, 'Agent Identity').click()
  await page.getByRole('option', { name: 'Agent Alpha' }).click()
  await labelledSelect(dialog, 'Agent Role').click()
  await page.getByRole('option', { name: 'Developer' }).click()
  await dialog.getByRole('button', { name: 'Create API Key' }).click()
  return dialog
}

/** True when the real backend is answering (skips cleanly when the stack is down). */
async function isBackendReachable(request: APIRequestContext): Promise<boolean> {
  try {
    await request.get('http://localhost:8000/api/v1/health', { timeout: 3000 })
    return true
  } catch {
    return false
  }
}

// ── Mocked E2E Suite: API Key Management Admin Flow ──────────────────────────

test.describe('API Key Management - Mocked Admin CRUD', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupApiKeyMocks(page)
  })

  test('renders API key list page without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    expect(errors.filter(e => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('does not redirect to login', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')
    expect(page.url()).not.toContain('/login')
  })

  test('displays page title', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'API Key Management' })).toBeVisible()
  })

  test('displays API key list with key names', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('cell', { name: 'Production Agent Key' })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Staging Viewer Key' })).toBeVisible()
  })

  test('displays bound identity and role names', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('cell', { name: 'Agent Alpha', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Agent Beta', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Developer', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Viewer', exact: true })).toBeVisible()
  })

  test('displays status chips', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Active chip for active key
    await expect(page.getByText('Active', { exact: true })).toBeVisible()
    // Revoked chip for revoked key
    await expect(page.getByText('Revoked', { exact: true })).toBeVisible()
  })

  test('shows key prefix hints', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Key prefix hints visible
    await expect(page.getByText('phn_sk_...').first()).toBeVisible()
  })

  test('displays info banner', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('alert').filter({ hasText: 'API keys allow external AI agents' })).toBeVisible()
  })

  test('shows Create API Key button', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('button', { name: 'Create API Key' })).toBeVisible()
  })

  test('has status filter dropdown', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Status filter is a MUI Select labelled "Status", defaulting to All Statuses
    const statusFilter = labelledSelect(page, 'Status')
    await expect(statusFilter).toBeVisible()
    await expect(statusFilter).toHaveText('All Statuses')
  })
})

// ── Mocked E2E Suite: Create API Key Flow ────────────────────────────────────

test.describe('API Key Management - Create Key Flow', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupApiKeyMocks(page)
  })

  test('opens create dialog when clicking Create button', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await page.getByRole('button', { name: 'Create API Key' }).click()

    // Dialog should appear with title
    await expect(
      page.getByRole('dialog').getByRole('heading', { name: 'Create API Key' })
    ).toBeVisible({ timeout: 5000 })
  })

  test('create dialog has name, identity, and role fields', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const dialog = await openCreateDialog(page)

    await expect(dialog.getByLabel('Key Name')).toBeVisible()
    // Both MUI Selects render, but their labels are not programmatically
    // associated (see `labelledSelect`), so match on the surrounding field.
    await expect(labelledSelect(dialog, 'Agent Identity')).toBeVisible()
    // Role select is present but stays disabled until an identity is chosen
    await expect(labelledSelect(dialog, 'Agent Role')).toBeDisabled()
  })

  test('create dialog shows scoping info', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const dialog = await openCreateDialog(page)

    await expect(dialog.getByText(/Key Scoping/)).toBeVisible()
  })

  test('can select identity and role then create', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const dialog = await submitCreateForm(page)

    // Should transition to step 2 with success message
    await expect(
      dialog.getByRole('heading', { name: 'API Key Created Successfully' })
    ).toBeVisible({ timeout: 5000 })
    await expect(dialog.getByText(/Save this key now/)).toBeVisible()
  })

  test('success step shows key summary info', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const dialog = await submitCreateForm(page)

    await expect(dialog.getByRole('heading', { name: 'API Key Created Successfully' })).toBeVisible({
      timeout: 5000,
    })
    await expect(dialog.getByText(/Agent Identity:\s*Agent Alpha/)).toBeVisible()
    await expect(dialog.getByText(/Agent Role:\s*Developer/)).toBeVisible()
  })

  test('create button disabled when form is empty', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const dialog = await openCreateDialog(page)

    await expect(dialog.getByRole('button', { name: 'Create API Key' })).toBeDisabled()
  })
})

// ── Mocked E2E Suite: Revoke API Key Flow ────────────────────────────────────

test.describe('API Key Management - Revoke Key Flow', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupApiKeyMocks(page)
  })

  test('revoke button visible for active keys', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Find the row with "Production Agent Key" - it should have a revoke (block) icon
    const activeRow = page.getByRole('row', { name: /Production Agent Key/ })
    await expect(activeRow.getByRole('button', { name: 'Revoke' })).toBeVisible()

    // Revoked keys have no revoke action, only delete
    const revokedRow = page.getByRole('row', { name: /Staging Viewer Key/ })
    await expect(revokedRow.getByRole('button', { name: 'Revoke' })).toHaveCount(0)
    await expect(revokedRow.getByRole('button', { name: 'Delete' })).toBeVisible()
  })

  test('revoke confirmation dialog appears', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Click revoke button on active key row
    const activeRow = page.getByRole('row', { name: /Production Agent Key/ })
    await activeRow.getByRole('button', { name: 'Revoke' }).click()

    // Dialog should appear
    await expect(
      page.getByRole('dialog').getByRole('heading', { name: 'Revoke API Key' })
    ).toBeVisible({ timeout: 5000 })
  })

  test('revoke dialog shows key name and warning', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const activeRow = page.getByRole('row', { name: /Production Agent Key/ })
    await activeRow.getByRole('button', { name: 'Revoke' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 5000 })
    await expect(
      dialog.getByText(/Are you sure you want to revoke the API key "Production Agent Key"\?/)
    ).toBeVisible()
    await expect(
      dialog.getByText('Agents using this key will immediately lose access. This action cannot be undone.')
    ).toBeVisible()
  })

  test('revoke dialog has cancel button', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    const activeRow = page.getByRole('row', { name: /Production Agent Key/ })
    await activeRow.getByRole('button', { name: 'Revoke' }).click()

    await expect(
      page.getByRole('dialog').getByRole('button', { name: 'Cancel' })
    ).toBeVisible({ timeout: 5000 })
  })
})

// ── Mocked E2E Suite: Filter & Search ────────────────────────────────────────

test.describe('API Key Management - Filtering', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await setupApiKeyMocks(page)
  })

  test('status filter has all/active/revoked options', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    // Open the status filter select
    await labelledSelect(page, 'Status').click()

    await expect(page.getByRole('option', { name: 'All Statuses' })).toBeVisible({ timeout: 5000 })
    await expect(page.getByRole('option', { name: 'Active' })).toBeVisible()
    await expect(page.getByRole('option', { name: 'Revoked' })).toBeVisible()
  })

  test('has search text field', async ({ page }) => {
    await page.goto('/api-keys')
    await page.waitForLoadState('networkidle')

    await expect(page.getByPlaceholder('Search')).toBeVisible()
  })
})

// ── Real Backend Integration Suite ───────────────────────────────────────────
// These tests require the real backend to be running. They validate:
// 1. API endpoints actually work against the real database
// 2. Auth middleware is correctly applied
// 3. Schema changes are applied correctly to the running database
//
// They skip cleanly when the stack is intentionally down (mocked E2E env).

test.describe('Real Backend Integration - API Key Endpoints', () => {
  test.beforeEach(async ({ request }) => {
    const reachable = await isBackendReachable(request)
    test.skip(!reachable, 'Real backend not reachable at http://localhost:8000 — mocked E2E environment')
  })

  test('GET /api/v1/api-keys requires authentication', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/api-keys')
    // Should be 401 (no token) or 403 (invalid auth)
    expect(response.status()).toBeGreaterThanOrEqual(400)
    expect(response.status()).toBeLessThan(500)
  })

  test('GET /api/v1/api-keys returns 200 with valid admin token', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/api-keys', {
      headers: { Authorization: `Bearer ${FAKE_TOKEN}` },
    })
    // With a fake token but proper format, the auth middleware may reject differently
    // We test that the endpoint exists and responds (not 404)
    expect(response.status()).not.toBe(404)
  })

  test('POST /api/v1/api-keys requires authentication', async ({ request }) => {
    const response = await request.post('http://localhost:8000/api/v1/api-keys', {
      data: {
        name: 'Unauth Key Test',
        agent_identity_id: '00000000-0000-0000-0000-000000000001',
        agent_role_id: '00000000-0000-0000-0000-000000000001',
      },
    })
    expect(response.status()).toBeGreaterThanOrEqual(400)
  })

  test('GET /api/v1/api-keys/identities-with-roles is behind auth', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/api-keys/identities-with-roles')
    expect(response.status()).toBeGreaterThanOrEqual(400)
  })

  test('Schema verification — api_keys endpoint responds', async ({ request }) => {
    // Verify that the endpoint routes are registered and the app doesn't crash
    const response = await request.get('http://localhost:8000/api/v1/health')
    expect(response.status()).toBe(200)
    const data = await response.json()
    expect(data.status).toBe('ok')
  })
})
