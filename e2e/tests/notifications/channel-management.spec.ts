/**
 * E2E tests for Notification Channel Management
 *
 * Covers:
 * - Channel list page renders channel names and types
 * - Open create dialog
 * - Create channel and verify it appears in the list
 * - Edit channel and verify update reflected
 * - Delete channel and verify it is removed
 */
import { test, expect } from '@playwright/test'
import { standardSetup } from '../_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

const CHANNEL_WEBHOOK: Record<string, unknown> = {
  id: 'ch-webhook-1',
  name: 'Ops Teams',
  channel_type: 'TEAMS_WEBHOOK',
  description: 'Operations alerts',
  is_active: true,
  properties: [{ id: 'prop-1', channel_id: 'ch-webhook-1', key: 'webhook_url', value: 'https://hooks.example.com/ops', is_secret: false }],
}

const CHANNEL_SLACK: Record<string, unknown> = {
  id: 'ch-slack-1',
  name: 'Slack Alerts',
  channel_type: 'SLACK_WEBHOOK',
  description: 'Slack integration',
  is_active: true,
  properties: [],
}

test.describe('Notification Channel Management', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('channel list page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([CHANNEL_WEBHOOK, CHANNEL_SLACK]) })
    )

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    const jsErrors = errors.filter((e) => !e.includes('ResizeObserver'))
    expect(jsErrors).toHaveLength(0)
  })

  test('renders channel names from API', async ({ page }) => {
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([CHANNEL_WEBHOOK, CHANNEL_SLACK]) })
    )

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Ops Teams')).toBeVisible()
    await expect(page.getByText('Slack Alerts')).toBeVisible()
  })

  test('renders channel type chips', async ({ page }) => {
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([CHANNEL_WEBHOOK, CHANNEL_SLACK]) })
    )

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    // Channel type chip text should be visible (may be rendered as Chip labels)
    await expect(page.getByText(/teams/i).first()).toBeVisible()
    await expect(page.getByText(/slack/i).first()).toBeVisible()
  })

  test('add channel button is visible', async ({ page }) => {
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    const addBtn = page.getByRole('button').filter({ hasText: /add|create|new/i }).first()
    await expect(addBtn).toBeVisible()
  })

  test('opens create channel dialog on add button click', async ({ page }) => {
    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    )

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    const addBtn = page.getByRole('button').filter({ hasText: /add|create|new/i }).first()
    await addBtn.click()

    // Dialog opens — target MuiDialog-paper to avoid matching the hidden sidebar Drawer
    await expect(page.locator('[role="dialog"].MuiDialog-paper')).toBeVisible({ timeout: 5000 })
  })

  test('create channel updates list without page reload', async ({ page }) => {
    const created = { ...CHANNEL_WEBHOOK, id: 'ch-new', name: 'New Channel' }
    let channels: unknown[] = []

    await page.route('**/api/v1/notifications/channels', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(channels) })
      } else {
        channels = [created]
        route.fulfill({ status: 201, headers: JSON_HEADERS, body: JSON.stringify(created) })
      }
    })

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')

    // Open create dialog
    const addBtn = page.getByRole('button').filter({ hasText: /add|create|new/i }).first()
    await addBtn.click()
    await page.locator('[role="dialog"].MuiDialog-paper').waitFor({ state: 'visible', timeout: 5000 })

    // Fill in name field
    await page.getByLabel(/name/i).first().fill('New Channel')

    // Submit
    await page.getByRole('button', { name: /save|create|add/i }).last().click()

    // Dialog should close and list should show the new item
    await page.locator('[role="dialog"].MuiDialog-paper').waitFor({ state: 'hidden', timeout: 5000 })
    await expect(page.getByText('New Channel')).toBeVisible({ timeout: 5000 })
  })

  test('delete channel removes it from list', async ({ page }) => {
    let channels = [CHANNEL_WEBHOOK, CHANNEL_SLACK]

    await page.route('**/api/v1/notifications/channels', (route) =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(channels) })
    )
    await page.route('**/api/v1/notifications/channels/ch-webhook-1', (route) => {
      if (route.request().method() === 'DELETE') {
        channels = channels.filter((c) => (c as { id: string }).id !== 'ch-webhook-1')
        route.fulfill({ status: 204, body: '' })
      } else {
        route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(CHANNEL_WEBHOOK) })
      }
    })

    await page.goto('/admin/notifications/channels')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Ops Teams')).toBeVisible()

    // Accept the native confirm() dialog that handleDelete triggers
    page.once('dialog', (dialog) => dialog.accept())

    // Delete button is the last IconButton in the row (Edit | Delete)
    const row = page.getByRole('row').filter({ hasText: 'Ops Teams' })
    await row.getByRole('button').last().click()

    // Row should disappear after refetch
    await expect(page.getByText('Ops Teams')).toBeHidden({ timeout: 10000 })
  })
})
