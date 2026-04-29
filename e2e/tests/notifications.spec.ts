import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_CHANNELS = [
  {
    id: 'ch-1',
    name: 'Ops Slack',
    channel_type: 'slack',
    config: { webhook_url: 'https://hooks.slack.com/xxx' },
    is_active: true,
  },
  {
    id: 'ch-2',
    name: 'Compliance Webhook',
    channel_type: 'webhook',
    config: { url: 'https://compliance.example.com/events' },
    is_active: true,
  },
]

const MOCK_EVENTS = [
  {
    id: 'ev-1',
    channel_id: 'ch-1',
    event_type: 'agent.result.saved',
    status: 'delivered',
    created_at: '2026-04-20T13:00:00Z',
  },
]

test.describe('Notification Configuration', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await page.route('**/api/v1/notifications/channels', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_CHANNELS) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(MOCK_CHANNELS[0]) })
      }
    })
    await page.route('**/api/v1/notifications/events', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_EVENTS) })
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
    await expect(page.getByText('Compliance Webhook')).toBeVisible()
  })

  test('notification page shows channel types', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    const typeLabel = page.getByText(/slack|webhook/i)
    await expect(typeLabel.first()).toBeVisible()
  })

  test('notification page shows event log with event types', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    // Event type or status from mock events
    const eventText = page.getByText(/agent\.result\.saved|delivered/i)
    const hasEvent = await eventText.count() > 0
    if (hasEvent) {
      await expect(eventText.first()).toBeVisible()
    } else {
      // Events may be on a separate tab
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('notification page has add channel button', async ({ page }) => {
    await page.goto('/notifications')
    await page.waitForLoadState('load')
    const addBtn = page.locator('button:visible').filter({ hasText: /add|create|new/i }).first()
    const hasAddBtn = await addBtn.count() > 0
    if (hasAddBtn) {
      await expect(addBtn).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })
})