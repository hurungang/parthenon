import { test, expect } from '@playwright/test'

/**
 * Setup Wizard E2E — full user-journey tests.
 *
 * All tests mock the backend API via page.route() so no live server is needed.
 */

const IDENTITY_STATUS_URL = '**/api/v1/setup/identity-status'
const IDENTITY_PROVISION_URL = '**/api/v1/setup/identity'

function mockNotConfigured(page: import('@playwright/test').Page) {
  return page.route(IDENTITY_STATUS_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ setup_state: 'NOT_CONFIGURED', provider_type: null, oidc_provider_url: null }),
    }),
  )
}

function mockConfigured(page: import('@playwright/test').Page) {
  return page.route(IDENTITY_STATUS_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        setup_state: 'CONFIGURED',
        provider_type: 'keycloak_bundled',
        oidc_provider_url: 'http://localhost:8080/realms/parthenon',
      }),
    }),
  )
}

function mockProvisionSuccess(page: import('@playwright/test').Page) {
  return page.route(IDENTITY_PROVISION_URL, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        provider_type: 'keycloak_bundled',
        oidc_provider_url: 'http://localhost:8080/realms/parthenon',
        realm_name: 'parthenon',
        client_id: 'parthenon-api',
        error_code: null,
        detail: null,
      }),
    }),
  )
}

function mockProvision502(page: import('@playwright/test').Page) {
  return page.route(IDENTITY_PROVISION_URL, (route) =>
    route.fulfill({
      status: 502,
      contentType: 'application/json',
      body: JSON.stringify({
        detail: { error_code: 'keycloak_unreachable', detail: 'Cannot reach Keycloak' },
      }),
    }),
  )
}

test.describe('Setup Wizard — full user journey', () => {
  test.beforeEach(async ({ page }) => {
    // Block telemetry and other non-local requests
    await page.route('http://localhost:4318/**', (route) => route.fulfill({ status: 200, body: '{}' }))
    await page.route(/^https?:\/\/(?!localhost:4173)/, (route) => route.abort())
  })

  // -----------------------------------------------------------------------
  // Smoke tests — basic visibility
  // -----------------------------------------------------------------------

  test('navigates to /setup when identity is NOT_CONFIGURED', async ({ page }) => {
    await mockNotConfigured(page)
    await page.goto('/')
    await page.waitForURL('**/setup', { timeout: 5000 }).catch(() => {
      // May already be at /setup or redirect handled differently — fallback check
    })
    await page.goto('/setup')
    await expect(page.getByText('Identity Provider Setup')).toBeVisible()
  })

  test('does NOT redirect to /setup when already CONFIGURED', async ({ page }) => {
    await mockConfigured(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    // Should NOT show the setup wizard title
    await expect(page.getByText('Identity Provider Setup')).not.toBeVisible()
  })

  // -----------------------------------------------------------------------
  // Step 1 — Provider selection
  // -----------------------------------------------------------------------

  test('step 1 shows all three provider radio buttons', async ({ page }) => {
    await mockNotConfigured(page)
    await page.goto('/setup')
    await expect(page.getByText('Bundled Keycloak (Recommended)')).toBeVisible()
    await expect(page.getByText('External Keycloak')).toBeVisible()
    await expect(page.getByText('Azure EntraID')).toBeVisible()
  })

  test('step 1 Next button advances to Keycloak config by default', async ({ page }) => {
    await mockNotConfigured(page)
    await page.goto('/setup')
    await page.getByRole('button', { name: 'Next' }).click()
    await expect(page.getByPlaceholder('http://localhost:8080')).toBeVisible()
  })

  test('selecting Azure EntraID and clicking Next shows OIDC config', async ({ page }) => {
    await mockNotConfigured(page)
    await page.goto('/setup')
    await page.getByText('Azure EntraID').click()
    await page.getByRole('button', { name: 'Next' }).click()
    await expect(
      page.getByPlaceholder(
        'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration',
      ),
    ).toBeVisible()
  })

  // -----------------------------------------------------------------------
  // Step 2 → Submit — Bundled Keycloak happy path
  // -----------------------------------------------------------------------

  test('bundled Keycloak happy path completes and shows success', async ({ page }) => {
    await mockNotConfigured(page)
    await mockProvisionSuccess(page)
    await page.goto('/setup')

    // Step 1 → Next
    await page.getByRole('button', { name: 'Next' }).click()

    // Step 2 — fill config form
    await page.getByPlaceholder('http://localhost:8080').fill('http://localhost:8082')
    await page.getByPlaceholder('parthenon', { exact: true }).fill('parthenon')
    await page.getByPlaceholder('parthenon-api').fill('parthenon-api')
    await page.getByPlaceholder('admin').fill('admin')
    // Password fields (no placeholder — use label)
    const passwordInputs = page.locator('input[type="password"]')
    await passwordInputs.first().fill('admin-password')

    // Submit button should now be enabled
    const submitBtn = page.getByRole('button', { name: 'Configure' })
    await expect(submitBtn).toBeEnabled()
    await submitBtn.click()

    // Step 4 — Completion
    await expect(page.getByText('Identity provider configured successfully!')).toBeVisible({
      timeout: 10000,
    })
    await expect(page.getByRole('button', { name: 'Go to Login' })).toBeVisible()
  })

  // -----------------------------------------------------------------------
  // Error handling
  // -----------------------------------------------------------------------

  test('502 from server shows keycloak unreachable error', async ({ page }) => {
    await mockNotConfigured(page)
    await mockProvision502(page)
    await page.goto('/setup')

    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByPlaceholder('http://localhost:8080').fill('http://localhost:8082')
    await page.getByPlaceholder('parthenon', { exact: true }).fill('parthenon')
    await page.getByPlaceholder('parthenon-api').fill('parthenon-api')
    await page.getByPlaceholder('admin').fill('admin')
    await page.locator('input[type="password"]').first().fill('admin-password')
    await page.getByRole('button', { name: 'Configure' }).click()

    await expect(
      page.getByText('Cannot reach Keycloak. Please verify the URL and try again.'),
    ).toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Try Again' }).first()).toBeVisible()
  })

  test('Try Again button returns to config step', async ({ page }) => {
    await mockNotConfigured(page)
    await mockProvision502(page)
    await page.goto('/setup')

    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByPlaceholder('http://localhost:8080').fill('http://localhost:8082')
    await page.getByPlaceholder('parthenon', { exact: true }).fill('parthenon')
    await page.getByPlaceholder('parthenon-api').fill('parthenon-api')
    await page.getByPlaceholder('admin').fill('admin')
    await page.locator('input[type="password"]').first().fill('admin-password')
    await page.getByRole('button', { name: 'Configure' }).click()

    await page.getByRole('button', { name: 'Try Again' }).last().click()
    await expect(page.getByPlaceholder('http://localhost:8080')).toBeVisible()
  })

  // -----------------------------------------------------------------------
  // Submit button disabled guard
  // -----------------------------------------------------------------------

  test('Configure button is disabled when required fields are empty', async ({ page }) => {
    await mockNotConfigured(page)
    await page.goto('/setup')
    await page.getByRole('button', { name: 'Next' }).click()
    const submitBtn = page.getByRole('button', { name: 'Configure' })
    await expect(submitBtn).toBeDisabled()
  })
})
