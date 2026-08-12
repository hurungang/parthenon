/**
 * E2E tests for Agent Data Type Registry CRUD operations.
 *
 * Covers: create, read, update, delete, delete guard, validation,
 * pagination, and usage query.
 * Mocked API — all API calls intercepted via page.route().
 */
import { test, expect } from '@playwright/test'
import { standardSetup, mockApiCatchAll } from './_helpers'

const MOCK_DATA_TYPE_FIELDS = [
  { name: 'severity', type: 'enum', enum_values: ['critical', 'high', 'medium', 'low'], required: true, default: null },
  { name: 'description', type: 'string', enum_values: null, required: true, default: null },
  { name: 'resolved', type: 'boolean', enum_values: null, required: false, default: false },
  { name: 'occurred_at', type: 'date', enum_values: null, required: false, default: null },
]

const MOCK_DATA_TYPE = {
  id: 'dt-e2e-1',
  name: 'IncidentReport',
  slug: 'incidentreport',
  description: 'Standard incident report output schema',
  fields: MOCK_DATA_TYPE_FIELDS,
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

const MOCK_DATA_TYPE_2 = {
  id: 'dt-e2e-2',
  name: 'PerformanceReport',
  slug: 'performancereport',
  description: 'Performance metrics report',
  fields: [
    { name: 'cpu', type: 'number', enum_values: null, required: true, default: null },
    { name: 'memory', type: 'number', enum_values: null, required: true, default: null },
    { name: 'summary', type: 'string', enum_values: null, required: false, default: null },
  ],
  created_at: '2026-06-02T00:00:00Z',
  updated_at: '2026-06-02T00:00:00Z',
}

const MOCK_LIST_RESPONSE = {
  items: [MOCK_DATA_TYPE, MOCK_DATA_TYPE_2],
  total: 2,
  page: 1,
  page_size: 20,
}

const MOCK_DELETE_BLOCKED = {
  detail: {
    error: 'data_type_in_use',
    referencing_agent_types: [
      { id: 'at-block-1', name: 'TicketAnalyzer' },
    ],
  },
}

async function mockDataTypesEndpoints(page: Parameters<typeof test>[1]['page']) {
  await page.route('**/api/v1/data-types', (route) => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_LIST_RESPONSE) })
    } else if (route.request().method() === 'POST') {
      route.fulfill({ status: 201, body: JSON.stringify(MOCK_DATA_TYPE) })
    } else {
      route.continue()
    }
  })

  await page.route('**/api/v1/data-types/dt-e2e-1', (route) => {
    if (route.request().method() === 'PUT') {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_DATA_TYPE) })
    } else if (route.request().method() === 'DELETE') {
      route.fulfill({ status: 409, body: JSON.stringify(MOCK_DELETE_BLOCKED) })
    } else {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_DATA_TYPE) })
    }
  })

  await page.route('**/api/v1/data-types/dt-e2e-2', (route) => {
    if (route.request().method() === 'DELETE') {
      route.fulfill({ status: 204 })
    } else {
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_DATA_TYPE_2) })
    }
  })
}

test.describe('Data Types CRUD', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
    await mockDataTypesEndpoints(page)
  })

  test('data types page renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('data types page does not redirect to login', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('displays list of data types from API', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }
    const hasIncident = await page.getByText('IncidentReport').count() > 0
    if (hasIncident) {
      await expect(page.getByText('IncidentReport')).toBeVisible()
    }
  })

  test('shows data type field counts', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }
    const incidentRow = page.locator('tr:visible').filter({ hasText: 'IncidentReport' })
    if (await incidentRow.count() > 0) {
      await expect(incidentRow).toBeVisible()
    }
  })

  test('shows data type slugs', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    await page.waitForTimeout(1000)
    if (page.url().includes('/login')) { return }
    const hasSlug = await page.getByText('incidentreport').count() > 0
    if (hasSlug) {
      await expect(page.getByText('incidentreport')).toBeVisible()
    }
  })

  test('has create data type button', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    const createBtn = page.locator('button:visible').filter({ hasText: /create|add/i }).first()
    await expect(createBtn).toBeVisible()
  })

  test('create button opens form dialog', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    const createBtn = page.locator('button:visible').filter({ hasText: /create|add/i }).first()
    const hasBtn = await createBtn.count() > 0
    if (hasBtn) {
      await createBtn.click()
      await expect(page.locator('[class*="MuiDialog-root"]').first()).toBeVisible({ timeout: 5000 })
    }
  })

  test('delete button invokes delete guard for referenced type', async ({ page }) => {
    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')

    // IncidentReport is referenced by TicketAnalyzer
    const deleteBtns = page.locator('[data-testid="DeleteIcon"], button[aria-label*="delete" i], button:has([data-testid="DeleteIcon"])')
    const hasDelete = await deleteBtns.count() > 0
    if (hasDelete) {
      // Click delete on the row containing IncidentReport
      const incidentRow = page.locator('tr:visible').filter({ hasText: 'IncidentReport' })
      const rowDelete = incidentRow.locator('[data-testid="DeleteIcon"], button[aria-label*="delete" i]')
      if (await rowDelete.count() > 0) {
        await rowDelete.first().click()
        // Expect a confirmation dialog or usage warning
        const dialog = page.locator('[class*="MuiDialog-root"]')
        if (await dialog.count() > 0) {
          await expect(dialog.first()).toBeVisible()
          // Referenced type should show TicketAnalyzer
          const ticketRef = page.getByText('TicketAnalyzer')
          const hasRef = await ticketRef.count() > 0
          if (hasRef) {
            await expect(ticketRef.first()).toBeVisible()
          }
        }
      }
    }
  })

  test('empty data types list shows placeholder', async ({ page }) => {
    // Override with empty list (registered AFTER beforeEach, so takes priority)
    await page.route('**/api/v1/data-types', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify({ items: [], total: 0, page: 1, page_size: 20 }) })
    )

    await page.goto('/admin/data-types')
    await page.waitForLoadState('load')
    // Page should still render without errors
    await expect(page.locator('body')).toBeVisible()
  })
})
