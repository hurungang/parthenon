import { expect, test } from '@playwright/test'
import { standardSetup } from './_helpers'

const BACKEND = process.env.CONTROL_CENTER_URL || 'http://localhost:8000'
const API = `${BACKEND}/api/v1`

test.describe('Real Backend Integration - Service Segregation Deny Paths', () => {
  test('internal authorize endpoint is wired and rejects missing service certificate', async ({ request }) => {
    const response = await request.post(`${API}/internal/authorize/tool-call`, {
      data: {
        certificate_serial_number: 'e2e-missing-cert-probe',
        tool_name: 'system____save_result',
      },
    })

    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([401, 403]).toContain(response.status())
  })

  test('internal system-tools endpoint is wired and rejects missing service certificate', async ({ request }) => {
    const response = await request.post(`${API}/internal/system-tools/save-result`, {
      data: {
        session_id: '00000000-0000-0000-0000-000000000001',
        tool_args: { content: 'e2e probe' },
      },
    })

    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([401, 403]).toContain(response.status())
  })

  test('revocation contract endpoint uses revoked/{serial_number} path', async ({ request }) => {
    const response = await request.get(`${API}/internal/certificates/revoked/e2e-probe-serial`)

    expect(response.status()).not.toBe(404)
    expect(response.status()).not.toBe(500)
    expect([200, 401, 403, 422]).toContain(response.status())
  })
})

test.describe('Browser Boundary - Frontend Uses API/WS Boundaries Only', () => {
  test.beforeEach(async ({ page }) => {
    await standardSetup(page)
  })

  test('dashboard traffic does not attempt direct database connections', async ({ page }) => {
    const requestUrls: string[] = []
    page.on('request', (req) => requestUrls.push(req.url().toLowerCase()))

    await page.route('**/api/v1/agents/sessions*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ items: [], total: 0 }) })
    )

    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    expect(requestUrls.some((u) => u.includes('/api/v1/'))).toBe(true)
    expect(requestUrls.some((u) => u.includes('postgres'))).toBe(false)
    expect(requestUrls.some((u) => u.includes('supabase'))).toBe(false)
    expect(requestUrls.some((u) => u.includes(':5432'))).toBe(false)
  })
})
