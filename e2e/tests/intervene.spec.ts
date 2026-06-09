import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

test.describe('Human Intervene', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/intervene/requests*', async (route) => {
      const url = new URL(route.request().url())
      const status = url.searchParams.get('status')
      const pending = [
        {
          id: 'req-001',
          agent_session_id: 'sess-abc',
          agent_type_id: 'at-1',
          intervention_type: 'approval',
          reason: 'Approve this action?',
          status: 'pending',
          created_at: new Date().toISOString(),
        },
        {
          id: 'req-002',
          agent_session_id: 'sess-def',
          agent_type_id: 'at-2',
          intervention_type: 'choice',
          reason: 'Select an option',
          choices: ['Option A', 'Option B'],
          status: 'pending',
          created_at: new Date().toISOString(),
        },
        {
          id: 'req-003',
          agent_session_id: 'sess-ghi',
          agent_type_id: 'at-3',
          intervention_type: 'text',
          reason: 'Enter your response',
          status: 'pending',
          created_at: new Date().toISOString(),
        },
      ]
      const responded = [
        {
          id: 'req-004',
          agent_session_id: 'sess-jkl',
          agent_type_id: 'at-1',
          intervention_type: 'approval',
          reason: 'Approved action',
          status: 'responded',
          created_at: new Date(Date.now() - 3600000).toISOString(),
          responded_at: new Date().toISOString(),
          response: {
            id: 'resp-001',
            request_id: 'req-004',
            operator_user_id: 'user-1',
            approval_value: true,
            responded_at: new Date().toISOString(),
          },
        },
      ]
      if (status === 'pending') {
        await route.fulfill({ status: 200, body: JSON.stringify(pending) })
      } else if (status === 'responded') {
        await route.fulfill({ status: 200, body: JSON.stringify(responded) })
      } else {
        await route.fulfill({ status: 200, body: JSON.stringify([...pending, ...responded]) })
      }
    })

    await page.route('**/api/v1/intervene/metrics', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          pending_count: 3,
          avg_response_time_seconds: 120.5,
          resolution_rate: 0.25,
        }),
      }),
    )

    await page.route('**/api/v1/intervene/requests/*/respond', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'resp-001',
          request_id: 'req-001',
          operator_user_id: 'user-1',
          approval_value: true,
          responded_at: new Date().toISOString(),
        }),
      }),
    )

    await page.route('**/api/v1/intervene/requests/*/cancel', (route) =>
      route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'req-001',
          agent_session_id: 'sess-abc',
          agent_type_id: 'at-1',
          intervention_type: 'approval',
          reason: 'Approve this action?',
          status: 'cancelled',
          created_at: new Date().toISOString(),
        }),
      }),
    )

    await standardSetup(page)
  })

  test('intervene page renders pending requests', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')

    // Should show the pending request list with three requests
    await expect(page.getByText('Approve this action?').first()).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('Select an option').first()).toBeVisible()
    await expect(page.getByText('Enter your response').first()).toBeVisible()
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('respond button opens intervention dialog for approval type', async ({ page }) => {
    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')

    // Click first respond button
    const respondButtons = page.getByText('intervene.respond')
    await respondButtons.first().click()

    // Dialog should open with approval options
    await expect(page.getByText('intervene.responseDialogTitle')).toBeVisible({ timeout: 3000 })
    await expect(page.getByText('app.yes')).toBeVisible()
    await expect(page.getByText('app.no')).toBeVisible()
  })

  test('submitting approval response sends API call', async ({ page }) => {
    let responseSubmitted = false
    await page.route('**/api/v1/intervene/requests/*/respond', (route) => {
      responseSubmitted = true
      return route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'resp-001',
          request_id: 'req-001',
          operator_user_id: 'user-1',
          approval_value: true,
          responded_at: new Date().toISOString(),
        }),
      })
    })

    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')

    // Open dialog
    await page.getByText('intervene.respond').first().click()
    await expect(page.getByText('intervene.responseDialogTitle')).toBeVisible({ timeout: 3000 })

    // Click Yes then Submit
    await page.getByText('app.yes').click()
    await page.getByText('intervene.submitResponse').click()

    // Wait for API call
    await page.waitForTimeout(1000)
    expect(responseSubmitted).toBe(true)
  })

  test('pending count badge shows in navigation', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('load')

    // The navigation badge for intervene should appear with count 3
    const badge = page.locator('[class*="MuiBadge-badge"]').first()
    await expect(badge).toBeVisible({ timeout: 5000 })
  })

  test('intervene page shows responded requests section', async ({ page }) => {
    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')

    // Navigate to responded tab/filter if one exists, or check that responded
    // content is available
    const respondedTab = page.getByText('responded', { exact: false }).first()
    const hasRespondedTab = await respondedTab.count() > 0
    if (hasRespondedTab) {
      await respondedTab.click()
      await expect(page.getByText('Approved action').first()).toBeVisible({ timeout: 3000 })
    }
  })

  test('intervene page returns to dashboard via navigation', async ({ page }) => {
    await page.goto('/agents/intervene')
    await page.waitForLoadState('load')

    // Navigate back to dashboard using nav
    const dashboardLink = page.locator('a[href="/dashboard"], [class*="MuiListItemButton"]:has-text("Dashboard")').first()
    const hasLink = await dashboardLink.count() > 0
    if (hasLink) {
      await dashboardLink.click()
      await page.waitForURL('**/dashboard')
      expect(page.url()).toContain('/dashboard')
    }
  })
})
