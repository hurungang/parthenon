import { expect, test } from '@playwright/test'
import { FAKE_TOKEN, mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * System One provider configuration — admin config flow (mocked backend).
 *
 * Covers the SystemOneProviderConfigPage UI against mocked /system-one APIs:
 * - provider table renders with key-status chips (write-only key never shown),
 * - create dialog sends POST /system-one/providers with the api_key,
 * - status chip reflects the configured/notConfigured state.
 */
const PROVIDER = {
  id: '11111111-1111-1111-1111-111111111111',
  provider_type: 'typesafe',
  display_name: 'TypeSafe Jev (e2e)',
  base_url: 'https://api.typesafe.example/v1',
  default_model: 'jev-latest',
  enabled: true,
  enabled_models: ['jev-latest'],
  has_api_key: true,
}

test.describe('System One Provider Config (mocked)', () => {
  test('renders providers and creates one via the dialog', async ({ page }) => {
    await mockApiCatchAllProxyAware(page)

    let createdPayload: unknown = null
    await page.route(/\/api\/v1\/system-one\/providers$/, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([PROVIDER]),
        })
      }
      if (route.request().method() === 'POST') {
        createdPayload = route.request().postDataJSON()
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(PROVIDER),
        })
      }
      return route.fulfill({ status: 405, body: '{}' })
    })
    await page.route(/\/api\/v1\/system-one\/status$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          provider_type: 'typesafe',
          provider_id: PROVIDER.id,
          model: 'jev-latest',
        }),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')

    // Table renders the provider row — with a "key stored" chip, never the key.
    await expect(page.getByText('TypeSafe Jev (e2e)')).toBeVisible()
    await expect(page.getByText('Stored')).toBeVisible()

    // Open the create dialog and save.
    await page.getByText('Add Provider').click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByLabel('Display Name').fill('E2E Provider')
    // Round 2: the base URL is preset and read-only — it can't be filled,
    // and create sends the preset URL.
    const baseUrl = dialog.getByLabel('Base URL')
    await expect(baseUrl).toBeDisabled()
    await expect(baseUrl).toHaveValue('https://api.typesafe.ai/v1')
    await dialog.getByLabel('API Key').fill('sk-e2e-secret')
    await dialog.getByText('Save').click()

    await expect
      .poll(() => createdPayload, { timeout: 10_000 })
      .toBeTruthy()
    expect((createdPayload as Record<string, unknown>)['api_key']).toBe(
      'sk-e2e-secret',
    )
    expect((createdPayload as Record<string, unknown>)['display_name']).toBe(
      'E2E Provider',
    )
    expect((createdPayload as Record<string, unknown>)['base_url']).toBe(
      'https://api.typesafe.ai/v1',
    )
  })

  test('shows the unconfigured status when no providers exist', async ({
    page,
  }) => {
    await mockApiCatchAllProxyAware(page)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
    )
    await page.route(/\/api\/v1\/system-one\/status$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: false }),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')

    await expect(page.getByText('No System One providers configured yet.')).toBeVisible()
    await expect(page.getByText('Not configured')).toBeVisible()
  })

  test('shows a permission error when the API denies access', async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await page.route(/\/api\/v1\/system-one\/providers$/, (route) =>
      route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'forbidden' }),
      }),
    )

    await standardSetup(page)
    await page.goto('/system/system-one')

    // PermissionDeniedAlert surfaces the backend detail ("forbidden").
    await expect(page.getByText('forbidden').first()).toBeVisible()
  })
})
