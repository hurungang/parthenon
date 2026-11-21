import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

// Shapes mirror `NotificationChannel` / `NotificationLog` in
// frontend/src/types/index.ts — the page reads `properties` (array) and
// `created_at`, and renders `channel_type` / `status` through i18n labels.
const MOCK_CHANNELS = [
  {
    id: 'ch-1',
    name: 'Ops Slack',
    channel_type: 'SLACK_WEBHOOK',
    description: 'Team alerts',
    is_active: true,
    created_at: '2026-04-01T00:00:00Z',
    updated_at: '2026-04-01T00:00:00Z',
    properties: [{ id: 'p-1', key: 'webhook_url', is_secret: true }],
  },
  {
    id: 'ch-2',
    name: 'Compliance Teams',
    channel_type: 'TEAMS_WEBHOOK',
    description: null,
    is_active: true,
    created_at: '2026-04-02T00:00:00Z',
    updated_at: '2026-04-02T00:00:00Z',
    properties: [{ id: 'p-2', key: 'webhook_url', is_secret: true }],
  },
]

const MOCK_LOGS = [
  {
    id: 'log-1',
    group_id: null,
    channel_id: 'ch-1',
    source_type: 'AGENT',
    source_id: null,
    subject: 'Daily report ready',
    body: 'Report body',
    recipient: '#ops',
    status: 'delivered',
    error: null,
    metadata_: null,
    created_at: '2026-04-20T13:00:00Z',
    delivered_at: '2026-04-20T13:00:05Z',
  },
]

test.describe('Notification Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    // List endpoints carry `?limit=&offset=` — the trailing `**` lets the
    // collection glob match the query string. Registered before the more
    // specific `/channels/*/test` route (last-registered wins).
    await page.route('**/api/v1/notifications/channels**', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_CHANNELS) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_CHANNELS[0]) })
      }
    })
    await page.route('**/api/v1/notifications/logs**', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_LOGS) })
    )
    await page.route('**/api/v1/notifications/channels/*/test', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ sent: true }) })
    )
  })

  test('notification config page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('notification config page does not redirect to login', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('notification page shows channel names from API', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    await expect(page.getByText('Ops Slack')).toBeVisible()
  })

  test('notification page shows second channel in list', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    await expect(page.getByText('Compliance Teams')).toBeVisible()
  })

  test('notification page shows channel types', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    // channel_type is rendered as an i18n label: SLACK_WEBHOOK → "Slack".
    const typeLabel = page.getByText(/slack|teams/i)
    await expect(typeLabel.first()).toBeVisible()
  })

  test('notification page shows event log with event types', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')

    // Delivery logs live on the third tab ("Delivery Logs").
    await page.getByRole('tab', { name: 'Delivery Logs' }).click()
    await expect(page.getByText('Daily report ready')).toBeVisible()
    await expect(page.getByText('Delivered').first()).toBeVisible()
  })

  test('notification page has add channel button', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    // "Add Channel" button lives on the channels tab header.
    await expect(page.getByRole('button', { name: 'Add Channel' }).first()).toBeVisible()
  })
})
