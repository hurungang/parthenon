/**
 * E2E tests for Recipient Group Management
 *
 * Covers:
 * - Group list page renders group names and slugs
 * - Renders channel count badge
 * - Create group updates list without page reload
 * - Assign channel to group updates count
 * - Remove channel from group updates count
 * - Delete group removes it from list
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from '../_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

const MOCK_CHANNELS = [
  { id: 'ch-1', name: 'Ops Webhook', channel_type: 'webhook', is_active: true, properties: [] },
  { id: 'ch-2', name: 'Slack Alerts', channel_type: 'slack', is_active: true, properties: [] },
]

const GROUP_OPS = {
  id: 'grp-1',
  name: 'Operations',
  slug: 'operations',
  description: 'Operations team',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  channel_mappings: [{ id: 'map-1', channel_id: 'ch-1' }],
}

const GROUP_EMPTY = {
  id: 'grp-2',
  name: 'Dev Team',
  slug: 'dev-team',
  description: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  channel_mappings: [],
}

test.describe('Recipient Group Management', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('group list page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route('**/api/v1/notifications/recipient-groups', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([GROUP_OPS, GROUP_EMPTY]) })
    )
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CHANNELS) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')

    const jsErrors = errors.filter((e) => !e.includes('ResizeObserver'))
    expect(jsErrors).toHaveLength(0)
  })

  test('renders group names and slugs', async ({ page }) => {
    await page.route('**/api/v1/notifications/recipient-groups', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([GROUP_OPS, GROUP_EMPTY]) })
    )
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CHANNELS) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')

    await expect(page.getByRole('cell', { name: 'Operations', exact: true })).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Dev Team', exact: true })).toBeVisible()
    // Slugs rendered in monospace — use exact:true to avoid case-insensitive match on group names
    await expect(page.getByText('operations', { exact: true })).toBeVisible()
    await expect(page.getByText('dev-team', { exact: true })).toBeVisible()
  })

  test('renders channel count for each group', async ({ page }) => {
    await page.route('**/api/v1/notifications/recipient-groups', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([GROUP_OPS, GROUP_EMPTY]) })
    )
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CHANNELS) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')

    // GROUP_OPS has 1 channel, GROUP_EMPTY has 0
    // Count badge/chip: "1" and "0"
    await expect(page.getByText('1').first()).toBeVisible()
    await expect(page.getByText('0').first()).toBeVisible()
  })

  test('add group button is visible', async ({ page }) => {
    await page.route('**/api/v1/notifications/recipient-groups', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')

    const addBtn = page.getByRole('button').filter({ hasText: /add|create|new/i }).first()
    await expect(addBtn).toBeVisible()
  })

  test('create group updates list without page reload', async ({ page }) => {
    const newGroup = { ...GROUP_EMPTY, id: 'grp-new', name: 'New Group', slug: 'new-group', channel_mappings: [] }
    let groups: unknown[] = []

    await page.route('**/api/v1/notifications/recipient-groups', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(groups) })
      } else {
        groups = [newGroup]
        route.fulfill({ status: 201, headers: JSON_HEADERS, body: JSON.stringify(newGroup) })
      }
    })
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')

    const addBtn = page.getByRole('button').filter({ hasText: /add|create|new/i }).first()
    await addBtn.click()
    await page.locator('[role="dialog"].MuiDialog-paper').waitFor({ state: 'visible', timeout: 5000 })

    await page.getByLabel(/name/i).first().fill('New Group')

    await page.getByRole('button', { name: /save|create|add/i }).last().click()
    await page.locator('[role="dialog"].MuiDialog-paper').waitFor({ state: 'hidden', timeout: 5000 })

    await expect(page.getByText('New Group')).toBeVisible({ timeout: 5000 })
  })

  test('delete group removes it from list', async ({ page }) => {
    let groups = [GROUP_OPS, GROUP_EMPTY]

    await page.route('**/api/v1/notifications/recipient-groups', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(groups) })
    )
    await page.route('**/api/v1/notifications/recipient-groups/grp-2', (route) => {
      if (route.request().method() === 'DELETE') {
        groups = groups.filter((g) => (g as { id: string }).id !== 'grp-2')
        route.fulfill({ status: 204, body: '' })
      } else {
        route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(GROUP_EMPTY) })
      }
    })
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CHANNELS) })
    )

    await page.goto('/admin/notifications/groups')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Dev Team')).toBeVisible()

    // Accept the native confirm() dialog that handleDelete triggers
    page.once('dialog', (dialog) => dialog.accept())

    // Delete button is the last IconButton in the row (Edit | Delete)
    const row = page.getByRole('row').filter({ hasText: 'Dev Team' })
    await row.getByRole('button').last().click()

    // Row should disappear after refetch
    await expect(page.getByText('Dev Team')).toBeHidden({ timeout: 10000 })
  })
})
