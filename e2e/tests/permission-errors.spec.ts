import { test, expect } from '@playwright/test'
import { loginViaUI } from './_helpers'

/**
 * E2E tests to verify permission error handling is standardized across all pages.
 * Tests that users without permissions see structured error messages with:
 * - Resource type
 * - Action required
 * - Resource ID (if applicable)
 * - "Request Access" link
 */

test.describe('Permission Error Handling', () => {
  test.beforeEach(async ({ page }) => {
    // Login as testuser who has no permissions
    await loginViaUI(page, 'testuser', 'testuser')
  })

  const pagesToTest = [
    {
      name: 'Agents',
      path: '/agents',
      expectedResource: 'RT_AGENT',
      expectedAction: 'read',
    },
    {
      name: 'MCP Hub',
      path: '/mcp',
      expectedResource: 'RT_MCP_SERVER',
      expectedAction: 'read',
    },
    {
      name: 'Skills',
      path: '/skills',
      expectedResource: 'RT_SKILL',
      expectedAction: 'read',
    },
    {
      name: 'SOPs',
      path: '/sops',
      expectedResource: 'RT_SOP',
      expectedAction: 'read',
    },
    {
      name: 'Schedules',
      path: '/schedules',
      expectedResource: 'RT_SCHEDULING',
      expectedAction: 'read',
    },
    {
      name: 'Conversations',
      path: '/conversations',
      expectedResource: 'RT_CONVERSATION',
      expectedAction: 'read',
    },
    {
      name: 'Results',
      path: '/results',
      expectedResource: 'RT_RESULT',
      expectedAction: 'read',
    },
    {
      name: 'Notifications',
      path: '/notifications',
      expectedResource: 'RT_NOTIFICATION',
      expectedAction: 'read',
    },
    {
      name: 'Gateway',
      path: '/gateway',
      expectedResource: 'RT_AGENT', // Gateway uses agent types
      expectedAction: 'read',
    },
  ]

  for (const pageConfig of pagesToTest) {
    test(`${pageConfig.name} page shows structured permission error`, async ({ page }) => {
      // Navigate to the page
      await page.goto(`http://localhost:4173${pageConfig.path}`)
      await page.waitForLoadState('networkidle')

      // Check for PermissionDeniedAlert component
      const alert = page.locator('[role="alert"]').first()
      await expect(alert).toBeVisible({ timeout: 10000 })

      // Verify it's an error alert (red/error severity)
      await expect(alert).toHaveClass(/MuiAlert-standardError/)

      // Verify the text contains the expected resource type
      const alertText = await alert.textContent()
      expect(alertText).toContain('Permission Denied')
      expect(alertText).toContain(`Action: ${pageConfig.expectedAction}`)
      expect(alertText).toContain(`Resource: ${pageConfig.expectedResource}`)

      // Verify "Request Access" button exists and links to correct page
      const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
      await expect(requestAccessBtn).toBeVisible()
      await expect(requestAccessBtn).toContainText('Request Access')
    })
  }

  test('Tags page (in permissions tab) shows structured permission error', async ({ page }) => {
    await page.goto('http://localhost:4173/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click on Tags tab
    await page.click('text=Tags')
    await page.waitForLoadState('networkidle')

    // Check for permission error
    const alert = page.locator('[role="alert"]').first()
    await expect(alert).toBeVisible({ timeout: 10000 })
    
    const alertText = await alert.textContent()
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: RT_TAG')

    const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
    await expect(requestAccessBtn).toBeVisible()
  })

  test('Roles page (in permissions tab) shows structured permission error', async ({ page }) => {
    await page.goto('http://localhost:4173/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click on Roles tab
    await page.click('text=Roles')
    await page.waitForLoadState('networkidle')

    // Check for permission error
    const alert = page.locator('[role="alert"]').first()
    await expect(alert).toBeVisible({ timeout: 10000 })
    
    const alertText = await alert.textContent()
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: RT_ROLE')

    const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
    await expect(requestAccessBtn).toBeVisible()
  })

  test('Groups page (in permissions tab) shows structured permission error', async ({ page }) => {
    await page.goto('http://localhost:4173/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click on Groups tab
    await page.click('text=Groups')
    await page.waitForLoadState('networkidle')

    // Check for permission error
    const alert = page.locator('[role="alert"]').first()
    await expect(alert).toBeVisible({ timeout: 10000 })
    
    const alertText = await alert.textContent()
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: RT_GROUP')

    const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
    await expect(requestAccessBtn).toBeVisible()
  })

  test('Users page (in permissions tab) shows structured permission error', async ({ page }) => {
    await page.goto('http://localhost:4173/user-permissions')
    await page.waitForLoadState('networkidle')

    // Click on Users tab
    await page.click('text=Users')
    await page.waitForLoadState('networkidle')

    // Check for permission error
    const alert = page.locator('[role="alert"]').first()
    await expect(alert).toBeVisible({ timeout: 10000 })
    
    const alertText = await alert.textContent()
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: RT_USER')

    const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
    await expect(requestAccessBtn).toBeVisible()
  })

  test('Dialog permission errors show structured message (example: Agents page)', async ({ page }) => {
    // First, login as admin to access the page
    await page.goto('http://localhost:4173/login')
    await page.waitForLoadState('networkidle')
    
    // Logout testuser
    const userMenuButton = page.locator('[aria-label="user menu"]')
    if (await userMenuButton.isVisible()) {
      await userMenuButton.click()
      await page.click('text=Logout')
      await page.waitForLoadState('networkidle')
    }

    // Login as admin (assuming adminuser has some permissions but not manage agent)
    await loginViaUI(page, 'adminuser', 'adminuser')
    
    await page.goto('http://localhost:4173/agents')
    await page.waitForLoadState('networkidle')

    // Try to create a new agent (assuming user doesn't have manage permission)
    const createButton = page.locator('button:has-text("Create Agent")')
    if (await createButton.isVisible()) {
      await createButton.click()
      
      // Fill in form
      await page.fill('input[name="name"]', 'Test Agent')
      await page.fill('textarea[name="description"]', 'Test description')
      
      // Try to save
      await page.click('button:has-text("Save")')
      await page.waitForTimeout(1000)
      
      // Check for error in dialog
      const dialogAlert = page.locator('[role="dialog"] [role="alert"]')
      if (await dialogAlert.isVisible()) {
        const alertText = await dialogAlert.textContent()
        expect(alertText).toContain('Permission Denied')
        expect(alertText).toContain('Action: manage')
        expect(alertText).toContain('Resource: RT_AGENT')
        
        const requestAccessBtn = dialogAlert.locator('a[href="/permissions/access-requests"]')
        await expect(requestAccessBtn).toBeVisible()
      }
    }
  })

  test('Access Requests page is accessible without permissions', async ({ page }) => {
    // Access Requests page should be accessible to all users
    await page.goto('http://localhost:4173/permissions/access-requests')
    await page.waitForLoadState('networkidle')

    // Should NOT show permission error
    const errorAlert = page.locator('[role="alert"]')
    const errorCount = await errorAlert.count()
    
    // Should see the tabs instead
    await expect(page.locator('text=Pending Requests')).toBeVisible()
    await expect(page.locator('text=My Requests')).toBeVisible()
    
    // If there are alerts, they should not be permission errors
    if (errorCount > 0) {
      const alertText = await errorAlert.first().textContent()
      expect(alertText).not.toContain('Permission Denied')
    }
  })

  test('Request Access link navigation works', async ({ page }) => {
    // Go to any restricted page
    await page.goto('http://localhost:4173/agents')
    await page.waitForLoadState('networkidle')

    // Wait for error alert
    const alert = page.locator('[role="alert"]').first()
    await expect(alert).toBeVisible({ timeout: 10000 })

    // Click Request Access button
    const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
    await requestAccessBtn.click()
    await page.waitForLoadState('networkidle')

    // Should navigate to access requests page
    expect(page.url()).toBe('http://localhost:4173/permissions/access-requests')
    
    // Should see the tabs
    await expect(page.locator('text=Pending Requests')).toBeVisible()
    await expect(page.locator('text=My Requests')).toBeVisible()
  })
})
