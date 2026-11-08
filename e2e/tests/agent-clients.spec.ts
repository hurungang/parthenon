import { test, expect } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

const MOCK_CLIENTS = [
  {
    id: 'c1',
    name: 'Acme Support Bot',
    slug: 'acme',
    agent_type_id: 'at1',
    agent_type_name: 'Support Bot',
    key_type: 'publishable',
    key_prefix: 'phn_cl_pk_',
    status: 'active',
    white_label_theme: null,
    allowed_origins: ['https://acme.com'],
    rate_limit: 100,
    rate_limit_window: 'per_minute',
    created_at: '2026-01-01T00:00:00Z',
    last_used_at: null,
    expires_at: null,
  },
]

const MOCK_CREATE = {
  id: 'c2',
  name: 'Nimbus',
  key_type: 'secret',
  key_prefix: 'phn_cl_sk_',
  client_key: 'phn_cl_sk_e2e_secret',
  agent_type_id: 'at2',
  agent_type_name: 'Triage',
  created_at: '2026-01-01T00:00:00Z',
}

async function setupClientMocks(page: any) {
  // Agent type options for the searchable create-dialog dropdown.
  await page.route('http://localhost:8000/api/v1/agents/types**', async (route: any) => {
    return route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify([{ id: 'at2', name: 'Triage', input_type: 'typed' }]),
    })
  })
  await page.route('**/api/v1/agents/types**', async (route: any) => {
    return route.fulfill({
      status: 200,
      headers: JSON_HEADERS,
      body: JSON.stringify([{ id: 'at2', name: 'Triage', input_type: 'typed' }]),
    })
  })

  const handler = async (route: any) => {
    const method = route.request().method()
    if (method === 'GET') {
      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CLIENTS) })
    }
    if (method === 'POST') {
      return route.fulfill({ status: 201, headers: JSON_HEADERS, body: JSON.stringify(MOCK_CREATE) })
    }
    return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
  }
  await page.route('http://localhost:8000/api/v1/clients**', handler)
  await page.route('**/api/v1/clients**', handler)
  await page.route(/\/api\/v1\/clients\/[^/]+$/, async (route: any) => {
    if (route.request().method() === 'DELETE') {
      return route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: 'c1', status: 'revoked', message: 'ok' }),
      })
    }
    return route.fulfill({ status: 200, headers: JSON_HEADERS, body: '{}' })
  })
}

test.describe('Agent Clients - Mocked Management', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await standardSetup(page)
    await setupClientMocks(page)
  })

  test('renders the clients page without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/clients')
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('lists clients with agent type and credential type', async ({ page }) => {
    await page.goto('/clients')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Acme Support Bot')).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Support Bot', exact: true })).toBeVisible()
    await expect(page.getByText('publishable', { exact: true })).toBeVisible()
  })

  test('shows the publishable soft warning in the create dialog', async ({ page }) => {
    await page.goto('/clients')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: /New Client|agentClients\.new/ }).click()
    await expect(page.getByText(/exposes this agent type|publishableWarning/)).toBeVisible()
  })

  test('creates a client and shows the credential once', async ({ page }) => {
    await page.goto('/clients')
    await page.waitForLoadState('networkidle')
    await page.getByRole('button', { name: /New Client|agentClients\.new/ }).click()
    await page.getByLabel(/Client name|agentClients\.name/).fill('Nimbus')
    // Searchable agent-type dropdown.
    await page.getByRole('combobox', { name: /Agent type|agentClients\.agentType/ }).click()
    await page.getByRole('option', { name: 'Triage' }).click()
    await page.getByRole('button', { name: /Save|common\.save/ }).click()
    await expect(page.locator('input[readonly]')).toHaveValue('phn_cl_sk_e2e_secret')
  })
})
