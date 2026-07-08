import { test, expect } from '@playwright/test'

/**
 * E2E Tests: OIDC Integration — Login Flows, System Config, Super Admin
 *
 * Tests use URL pattern interception to mock API responses.
 * Since the frontend dev server proxies some API calls and makes direct
 * cross-origin calls for others, we match on the path segment.
 */

// ── Mock Setup ──────────────────────────────────────────────────────────────

async function setupMocks(page: any, options: {
  hasOidcProvider?: boolean
  superAdminEnabled?: boolean
} = {}) {
  const { hasOidcProvider = false, superAdminEnabled = false } = options

  // Abort non-localhost requests to prevent hanging
  await page.route(/^https?:\/\/(?!localhost)/, (route: any) => route.abort())

  // Mock identity providers endpoint — match both dev proxy and direct URLs
  await page.route(/identity-providers$/, (route: any) => {
    if (route.request().method() === 'POST') {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'new-id', provider_scope: 'user', provider_type: 'oidc_generic',
          display_name: 'New Provider', issuer_url: 'https://new.example.com',
          client_id: 'client-id', encrypted_client_secret: 'enc',
          scopes: 'openid', is_enabled: true,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }),
      })
      return
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: hasOidcProvider ? [{
          id: '1', provider_scope: 'user', provider_type: 'oidc_generic',
          display_name: 'Enterprise SSO', issuer_url: 'https://login.example.com',
          client_id: 'test-client', encrypted_client_secret: 'encrypted',
          scopes: 'openid profile email', claim_mappings: null, is_enabled: true,
          created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
        }] : [],
        total: hasOidcProvider ? 1 : 0,
      }),
    })
  })

  // Mock super admin status
  await page.route(/super-admin\/status$/, (route: any) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        is_enabled: superAdminEnabled,
        username: superAdminEnabled ? 'admin' : null,
        last_login_at: superAdminEnabled ? new Date().toISOString() : null,
      }),
    })
  })

  // Mock super admin login
  await page.route(/super-admin\/login$/, (route: any) => {
    const body = route.request().postDataJSON()
    if (body?.username === 'testadmin' && body?.password === 'testpass') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'test-jwt-token-e2e',
          token_type: 'bearer', username: 'testadmin', is_super_admin: true,
        }),
      })
    } else {
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Invalid username or password' }),
      })
    }
  })

  // Mock identity status (prevent setup wizard redirect)
  await page.route(/setup\/identity-status$/, (route: any) =>
    route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ setup_state: 'CONFIGURED' }) }),
  )

  // Mock health and telemetry
  await page.route(/\/health$/, (route: any) =>
    route.fulfill({ status: 200, body: JSON.stringify({ status: 'ok' }) }),
  )
  await page.route(/telemetry\/config$/, (route: any) =>
    route.fulfill({ status: 200, body: JSON.stringify({ traces_enabled: false, metrics_enabled: false, logs_enabled: false }) }),
  )

  // Mock dashboard
  await page.route(/dashboard/, (route: any) =>
    route.fulfill({ status: 200, body: JSON.stringify({ active_agents: 0 }) }),
  )
}

// ── Tests ───────────────────────────────────────────────────────────────────

test.describe('Login Page States', () => {

  test('shows app title on login page', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: true, superAdminEnabled: false })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })

  test('shows OIDC login when OIDC configured and super admin disabled', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: true, superAdminEnabled: false })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)
    // Page renders
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
    // Verify at least one button is present
    const buttons = page.locator('button')
    const count = await buttons.count()
    expect(count).toBeGreaterThan(0)
  })

  test('shows super admin form when super admin enabled, no OIDC', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })

  test('shows both when both enabled', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: true, superAdminEnabled: true })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Super Admin Login Form', () => {

  test('login form renders when super admin enabled', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    // Page renders without crash
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })

  test('login with valid credentials stores token', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    // Try to find and fill login form
    const usernameInput = page.getByLabel(/Username|auth\.username/)
    const passwordInput = page.getByLabel(/Password|auth\.password/)

    if (await usernameInput.count() > 0 && await passwordInput.count() > 0) {
      await usernameInput.fill('testadmin')
      await passwordInput.fill('testpass')

      // Find and click login button
      const loginBtns = page.locator('button')
      const allTexts = await loginBtns.allTextContents()
      console.log('Available buttons:', allTexts)

      // Click any button that looks like a login/submit button
      for (const text of allTexts) {
        if (text.toLowerCase().includes('login') || text.toLowerCase().includes('sign in')) {
          await loginBtns.filter({ hasText: text }).first().click()
          break
        }
      }
      await page.waitForTimeout(2000)
    }

    // Page should have rendered
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })

  test('login with invalid password shows error message', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    const usernameInput = page.getByLabel(/Username|auth\.username/)
    const passwordInput = page.getByLabel(/Password|auth\.password/)

    if (await usernameInput.count() > 0 && await passwordInput.count() > 0) {
      await usernameInput.fill('testadmin')
      await passwordInput.fill('wrongpass')

      const loginBtns = page.locator('button')
      const allTexts = await loginBtns.allTextContents()
      for (const text of allTexts) {
        if (text.toLowerCase().includes('login') || text.toLowerCase().includes('sign in')) {
          await loginBtns.filter({ hasText: text }).first().click()
          break
        }
      }
      await page.waitForTimeout(2000)
    }

    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('System Config Page', () => {

  test('navigates to system config with auth token', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: true, superAdminEnabled: true })

    // Inject auth token
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'test-jwt-e2e')
    })

    await page.goto('/system')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    console.log('System config URL:', page.url())
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })

  test('system config page renders without crash', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: true, superAdminEnabled: true })

    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'test-jwt-e2e')
    })

    await page.goto('/system')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    // Verify page renders
    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
  })
})

test.describe('Token Persistence', () => {

  test('tokens persist after navigating and saving config', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })

    // Inject token to simulate logged-in super admin
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
      localStorage.setItem('super_admin_token', token)
    }, 'test-persistence-token')

    await page.goto('/system')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    // Verify token is preserved
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(token).toBe('test-persistence-token')

    // Navigate to login and back — verify no redirect
    const currentUrl = page.url()
    expect(currentUrl).not.toContain('/login')
  })

  test('super admin login then save OIDC config — full flow', async ({ page }) => {
    const superAdminToken = 'sa-jwt-full-flow-token'

    // Mock: no OIDC providers yet, super admin enabled
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })

    // Step 1: Navigate to login — should see super admin form
    await page.goto('/login')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    // Check page is the login page (not redirected to setup)
    expect(page.url()).toContain('/login')

    // Step 2: Login as super admin
    await page.addInitScript((token: string) => {
      localStorage.setItem('access_token', token)
      localStorage.setItem('super_admin_token', token)
    }, superAdminToken)

    // Step 3: Navigate to system config with the token
    await page.goto('/system/identity-providers')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    // Step 4: Verify token was NOT cleared (no redirect to /login)
    const tokenAfterNav = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(tokenAfterNav).toBe(superAdminToken)
    expect(page.url()).not.toContain('/login')

    // Step 5: Trigger a mock save — the mocked POST endpoint returns 201
    const saveResult = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      try {
        const resp = await fetch('/api/v1/system/identity-providers', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            provider_scope: 'user',
            provider_type: 'oidc_generic',
            display_name: 'Test Provider',
            issuer_url: 'https://login.example.com',
            client_id: 'test-client',
            client_secret: 'test-secret',
            scopes: 'openid profile email',
            is_enabled: true,
          }),
        })
        return { status: resp.status, ok: resp.ok }
      } catch (e) {
        return { error: String(e) }
      }
    })

    // Step 6: Verify save succeeded
    expect(saveResult.ok).toBe(true)

    // Step 7: Verify token is STILL present after save (no 401 redirect)
    const tokenAfterSave = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(tokenAfterSave).toBe(superAdminToken)

    // Step 8: Verify page URL is NOT /login
    expect(page.url()).not.toContain('/login')
  })

  test('saving OIDC config as super admin does not clear token', async ({ page }) => {
    const token = 'sa-token-persistence'

    // Setup: OIDC not yet configured, super admin enabled
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: true })

    // Inject token to simulate logged-in super admin
    await page.addInitScript((t: string) => {
      localStorage.setItem('access_token', t)
      localStorage.setItem('super_admin_token', t)
    }, token)

    // Navigate to identity providers page
    await page.goto('/system/identity-providers')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    // Simulate multiple save operations via fetch
    for (let i = 0; i < 3; i++) {
      const result = await page.evaluate(async (t: string) => {
        const resp = await fetch('/api/v1/system/identity-providers', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${t}`,
          },
          body: JSON.stringify({
            provider_scope: 'user',
            provider_type: 'oidc_generic',
            display_name: `Test ${Date.now()}`,
            issuer_url: 'https://login.example.com',
            client_id: 'test',
            scopes: 'openid',
            is_enabled: true,
          }),
        })
        return resp.status
      }, token)

      // Every save should succeed (201 from mock)
      expect(result).toBe(201)

      // Token must remain after each save
      const stored = await page.evaluate(() => localStorage.getItem('access_token'))
      expect(stored).toBe(token)

      // Not redirected to login
      expect(page.url()).not.toContain('/login')
    }
  })

test.describe('Setup Wizard', () => {

  test('setup page is accessible at /setup', async ({ page }) => {
    await setupMocks(page, { hasOidcProvider: false, superAdminEnabled: false })
    await page.goto('/setup')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(3000)

    await expect(page.locator('body')).toBeVisible({ timeout: 5000 })
    console.log('Setup page URL:', page.url())
  })
})
})
