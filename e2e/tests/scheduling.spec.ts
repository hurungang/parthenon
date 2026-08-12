import { test, expect } from '@playwright/test'
import { standardSetup, mockApiCatchAll } from './_helpers'

const API = 'http://localhost:8000/api/v1'

const MOCK_SCHEDULES = [
  {
    id: 'sched-1',
    name: 'Daily Report',
    description: 'Runs daily at 8 AM',
    cron_expression: '0 8 * * *',
    target_type: 'agent',
    target_id: 'at-1',
    payload: { prompt: 'Generate daily report' },
    status: 'active',
    scheduler_job_id: 'aps-job-1',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 'sched-2',
    name: 'Weekly Cleanup',
    description: 'Runs weekly on Sunday midnight',
    cron_expression: '0 0 * * 0',
    target_type: 'agent',
    target_id: 'at-2',
    payload: null,
    status: 'paused',
    scheduler_job_id: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

const MOCK_EXECUTIONS = [
  {
    id: 'exec-1',
    job_id: 'sched-1',
    status: 'success',
    error: null,
    result: { output: 'Report generated' },
    started_at: '2026-06-07T08:00:00Z',
    finished_at: '2026-06-07T08:01:00Z',
  },
  {
    id: 'exec-2',
    job_id: 'sched-1',
    status: 'failure',
    error: 'Agent type not found',
    result: null,
    started_at: '2026-06-06T08:00:00Z',
    finished_at: '2026-06-06T08:00:30Z',
  },
]

const MOCK_AGENT_TYPES = [
  { id: 'at-1', name: 'Research Agent', input_type: 'typed', input_schema: { type: 'object', properties: { prompt: { type: 'string' } } }, is_active: true },
  { id: 'at-2', name: 'Chat Agent', input_type: 'conversation', input_schema: null, is_active: true },
]

const NEW_SCHEDULE = {
  id: 'sched-3',
  name: 'New Test Schedule',
  description: null,
  cron_expression: '*/5 * * * *',
  target_type: 'agent',
  target_id: 'at-1',
  payload: { prompt: 'Run every 5 min' },
  status: 'active',
  scheduler_job_id: 'aps-job-3',
  created_at: '2026-06-07T12:00:00Z',
  updated_at: '2026-06-07T12:00:00Z',
}

/**
 * Register common background mocks needed by all schedule tests.
 * These handle APIs that the ScheduleManagerPage calls on mount.
 * Must be called BEFORE mockApiCatchAll so they take priority.
 */
async function mockScheduleBackground(page: import('@playwright/test').Page) {
  await page.route('http://localhost:8000/api/v1/intervene/metrics', (route) =>
    route.fulfill({ status: 200, body: JSON.stringify({}) })
  )
}

test.describe('Schedule Manager — E2E User Journeys', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('schedule list renders with schedules from API', async ({ page }) => {
    // Catch-all FIRST (lowest priority — last registered wins)
    await mockApiCatchAll(page)
    // Specific mocks AFTER (higher priority)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else {
        route.fulfill({ status: 201, body: JSON.stringify(NEW_SCHEDULE) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES) })
    )

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Verify schedule names appear
    await expect(page.getByText('Daily Report')).toBeVisible()
    await expect(page.getByText('Weekly Cleanup')).toBeVisible()

    // Verify cron expressions appear
    await expect(page.getByText('0 8 * * *').first()).toBeVisible()

    // Verify status labels appear
    await expect(page.getByText('active').first()).toBeVisible()
    await expect(page.getByText('paused').first()).toBeVisible()
  })

  test('create schedule dialog opens, fill form, and submit', async ({ page }) => {
    let postCalled = false
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else if (route.request().method() === 'POST') {
        postCalled = true
        route.fulfill({ status: 201, body: JSON.stringify(NEW_SCHEDULE) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_AGENT_TYPES) })
    )

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Click the "Create Schedule" button (not the sidebar "Schedules" nav item)
    await page.getByRole('button', { name: 'Create Schedule' }).first().click()
    await page.waitForTimeout(300)

    // Fill schedule name
    await page.getByLabel('Name').fill('New Test Schedule')

    // Click save
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(500)

    expect(postCalled).toBe(true)
  })

  test('pause schedule', async ({ page }) => {
    let pauseCalled = false
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules\/[^/]+\/pause/, (route) => {
      pauseCalled = true
      route.fulfill({
        status: 200,
        body: JSON.stringify({ ...MOCK_SCHEDULES[0], status: 'paused' }),
      })
    })

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Wait for the schedule list to render
    await expect(page.getByText('Daily Report')).toBeVisible()

    // Pause button has no title/aria-label; filter by data-testid="PauseIcon"
    const pauseButton = page.locator('button').filter({ has: page.locator('[data-testid="PauseIcon"]') })
    await expect(pauseButton).toBeVisible()
    await pauseButton.click()
    await page.waitForTimeout(500)
    expect(pauseCalled).toBe(true)
  })

  test('resume schedule', async ({ page }) => {
    let resumeCalled = false
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules\/[^/]+\/resume/, (route) => {
      resumeCalled = true
      route.fulfill({
        status: 200,
        body: JSON.stringify({ ...MOCK_SCHEDULES[1], status: 'active' }),
      })
    })

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Wait for the schedule list to render
    await expect(page.getByText('Weekly Cleanup')).toBeVisible()

    // Resume button has no title/aria-label; filter by data-testid="PlayArrowIcon"
    const resumeButton = page.locator('button').filter({ has: page.locator('[data-testid="PlayArrowIcon"]') })
    await expect(resumeButton).toBeVisible()
    await resumeButton.click()
    await page.waitForTimeout(500)
    expect(resumeCalled).toBe(true)
  })

  test('delete schedule with confirmation', async ({ page }) => {
    let deleteCalled = false
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          body: JSON.stringify([MOCK_SCHEDULES[0]]), // Only one active schedule
        })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules\/[^/]+$/, (route) => {
      if (route.request().method() === 'DELETE') {
        deleteCalled = true
        route.fulfill({ status: 204 })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Wait for schedule to render
    await expect(page.getByText('Daily Report')).toBeVisible()

    // Delete button has no title/aria-label; filter by data-testid="DeleteIcon"
    const deleteButton = page.locator('button').filter({ has: page.locator('[data-testid="DeleteIcon"]') })
    await expect(deleteButton).toBeVisible()

    // Note: handleDelete uses confirm() which Playwright auto-accepts
    page.on('dialog', (dialog) => dialog.accept())
    await deleteButton.click()
    await page.waitForTimeout(500)
    expect(deleteCalled).toBe(true)
  })

  test('execution history dialog opens', async ({ page }) => {
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules\/[^/]+\/executions/, (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_EXECUTIONS) })
    )

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Wait for schedule to render
    await expect(page.getByText('Daily Report')).toBeVisible()

    // History/Execution button — uses `title={t('schedules.executions')}` = "Executions"
    await page.getByRole('button', { name: 'Executions' }).first().click()
    await page.waitForTimeout(500)

    // Execution dialog should be visible — title is `t('schedules.executions')` = "Executions"
    await expect(page.getByRole('dialog').getByRole('heading', { name: 'Executions' })).toBeVisible()
  })

  test('edit schedule pre-fills dialog and submits update', async ({ page }) => {
    let putCalled = false
    let updatedName = ''
    await mockApiCatchAll(page)
    await mockScheduleBackground(page)
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules(\?.*)?$/, (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({ status: 200, body: JSON.stringify(MOCK_SCHEDULES) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })
    await page.route('http://localhost:8000/api/v1/agents/types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify([]) })
    )
    await page.route(/http:\/\/localhost:8000\/api\/v1\/schedules\/sched-1$/, async (route) => {
      if (route.request().method() === 'PUT') {
        putCalled = true
        const body = JSON.parse(route.request().postData() || '{}')
        updatedName = body.name
        route.fulfill({ status: 200, body: JSON.stringify({ ...MOCK_SCHEDULES[0], name: body.name }) })
      } else {
        route.fulfill({ status: 200, body: JSON.stringify({}) })
      }
    })

    await page.goto('/schedules')
    await page.waitForLoadState('load')

    // Wait for schedule to render
    await expect(page.getByText('Daily Report')).toBeVisible()

    // Click the Edit button — no title, filter by data-testid="EditIcon"
    const editButton = page.locator('button').filter({ has: page.locator('[data-testid="EditIcon"]') }).first()
    await expect(editButton).toBeVisible()
    await editButton.click()
    await page.waitForTimeout(300)

    // Dialog should show "Edit Schedule" title
    await expect(page.getByRole('dialog').getByRole('heading', { name: 'Edit Schedule' })).toBeVisible()

    // Name field should be pre-filled with "Daily Report"
    const nameField = page.getByLabel('Name')
    await expect(nameField).toHaveValue('Daily Report')

    // Change the name
    await nameField.clear()
    await nameField.fill('Daily Report v2')

    // Click Save
    await page.getByRole('button', { name: 'Save' }).click()
    await page.waitForTimeout(500)

    expect(putCalled).toBe(true)
    expect(updatedName).toBe('Daily Report v2')
  })
})
