import { test, expect, type Page } from '@playwright/test'
import { mockApiCatchAllProxyAware, standardSetup } from './_helpers'

/**
 * E2E tests verifying that permission errors are standardised across pages.
 *
 * Canonical mocked E2E: the backend and Keycloak are intentionally stopped.
 * Authentication is a forged JWT injected into localStorage (standardSetup);
 * every API call is fulfilled from `page.route` mocks. A 403 is mocked with
 * the platform's structured payload (`detail.required_permission`), exactly
 * as the backend emits it, and the page must surface it through
 * `PermissionDeniedAlert` (resource type / action / "Request Access" link).
 *
 * Route note: the legacy `/results` page no longer exists in the router —
 * its successor is `/admin/agent-outputs` (Agent Outputs), which is covered
 * below instead.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** Structured 403 body as produced by the backend permission engine. */
function forbidden(resource_type: string, action = 'read') {
  return {
    status: 403,
    headers: JSON_HEADERS,
    body: JSON.stringify({
      detail: {
        detail: `Missing permission '${action}' on ${resource_type}`,
        required_permission: { resource_type, action, resource_id: null },
      },
    }),
  }
}

/** Fulfils a collection endpoint with an empty array (keeps `[].map` safe). */
async function emptyList(page: Page, pattern: RegExp) {
  await page.route(pattern, (route) =>
    route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) }),
  )
}

/**
 * The structured permission surface. Matched by the capitalised "Permission
 * Denied:" heading so it is never confused with the global 403 snackbar
 * ("Permission denied: you need …"), which is also role="alert".
 */
function permissionAlert(page: Page) {
  return page.locator('[role="alert"]').filter({ hasText: /Permission Denied:/ }).first()
}

const deniedPages = [
  {
    name: 'Agents',
    path: '/agents',
    resource: 'agent',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/agents\/types(\?.*)?$/, (route) => route.fulfill(forbidden('agent')))
    },
  },
  {
    name: 'MCP Hub',
    path: '/mcp',
    resource: 'integration::mcp_hub',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/mcp\/servers(\?.*)?$/, (route) =>
        route.fulfill(forbidden('integration::mcp_hub')),
      )
    },
  },
  {
    name: 'Skills',
    path: '/skills',
    resource: 'agent::skills',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/skills(\?.*)?$/, (route) =>
        route.fulfill(forbidden('agent::skills')),
      )
    },
  },
  {
    name: 'SOPs',
    path: '/sops',
    resource: 'agent::sops',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/sops(\?.*)?$/, (route) => route.fulfill(forbidden('agent::sops')))
    },
  },
  {
    name: 'Schedules',
    path: '/schedules',
    resource: 'agent::schedules',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/schedules(\?.*)?$/, (route) =>
        route.fulfill(forbidden('agent::schedules')),
      )
    },
  },
  {
    name: 'Conversations',
    path: '/conversations',
    resource: 'agent',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/conversations(\?.*)?$/, (route) =>
        route.fulfill(forbidden('agent')),
      )
    },
  },
  {
    name: 'Gateway',
    path: '/gateway',
    resource: 'agent',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/agents\/types(\?.*)?$/, (route) => route.fulfill(forbidden('agent')))
    },
  },
  {
    name: 'Agent Outputs',
    path: '/admin/agent-outputs',
    resource: 'agent::outputs',
    action: 'read',
    mock: async (page: Page) => {
      await page.route(/\/api\/v1\/agent-outputs(\?.*)?$/, (route) =>
        route.fulfill(forbidden('agent::outputs')),
      )
    },
  },
]

test.describe('Permission Error Handling', () => {
  test.beforeEach(async ({ page }) => {
    await mockApiCatchAllProxyAware(page)
    await standardSetup(page)

    // Safe defaults for collections read by the app shell and by editors that
    // mount alongside the page under test (the catch-all returns `{}`, which
    // breaks `.map`). Test-specific handlers registered afterwards win, since
    // Playwright resolves routes last-registered-first.
    await emptyList(page, /\/api\/v1\/agents\/roles(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/agents\/identities(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/agents\/types(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/mcp\/servers(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/mcp\/tools(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/user-tags\/definitions(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/user-roles(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/user-groups(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/user-access-requests\/pending(\?.*)?$/)
    await emptyList(page, /\/api\/v1\/user-access-requests\/my(\?.*)?$/)
  })

  for (const pageConfig of deniedPages) {
    test(`${pageConfig.name} page shows structured permission error`, async ({ page }) => {
      await pageConfig.mock(page)

      await page.goto(pageConfig.path)
      await page.waitForLoadState('load')

      const alert = permissionAlert(page)
      await expect(alert).toBeVisible({ timeout: 10000 })

      // Verify it is an error alert (red/error severity)
      await expect(alert).toHaveClass(/MuiAlert-standardError/)

      // Verify the structure: resource type + required action
      const alertText = (await alert.textContent()) ?? ''
      expect(alertText).toContain('Permission Denied')
      expect(alertText).toContain(`Action: ${pageConfig.action}`)
      expect(alertText).toContain(`Resource: ${pageConfig.resource}`)

      // "Request Access" button links to the access-request page
      const requestAccessBtn = alert.locator('a[href="/permissions/access-requests"]')
      await expect(requestAccessBtn).toBeVisible()
      await expect(requestAccessBtn).toContainText('Request Access')
    })
  }

  // Roles list is gated by system::permissions:read on the backend.
  test('Roles tab shows structured permission error', async ({ page }) => {
    await page.route(/\/api\/v1\/user-roles(\?.*)?$/, (route) =>
      route.fulfill(forbidden('system::permissions')),
    )

    await page.goto('/user-permissions')
    await page.waitForLoadState('load')

    await page.getByRole('tab', { name: 'Roles' }).click()

    const alert = permissionAlert(page)
    await expect(alert).toBeVisible({ timeout: 10000 })

    const alertText = (await alert.textContent()) ?? ''
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: system::permissions')

    await expect(alert.locator('a[href="/permissions/access-requests"]')).toBeVisible()
  })

  // Tag definitions (GET) are not permission-gated on the backend — any
  // authenticated user may list them, so no denial surface appears.
  test('Tags tab is readable without the permissions module', async ({ page }) => {
    await page.goto('/user-permissions')
    await page.waitForLoadState('load')

    await expect(page.getByRole('tab', { name: 'Tags' })).toBeVisible()
    await expect(permissionAlert(page)).toHaveCount(0)
  })

  // Group listing (GET) is likewise open to any authenticated user.
  test('Groups tab is readable without the permissions module', async ({ page }) => {
    await page.goto('/user-permissions')
    await page.waitForLoadState('load')

    await page.getByRole('tab', { name: 'Groups' }).click()

    await expect(page.getByRole('tab', { name: 'Groups' })).toBeVisible()
    await expect(permissionAlert(page)).toHaveCount(0)
  })

  test('Users tab shows structured permission error', async ({ page }) => {
    await page.route(/\/api\/v1\/platform-users(\?.*)?$/, (route) =>
      route.fulfill(forbidden('system::permissions')),
    )

    await page.goto('/user-permissions')
    await page.waitForLoadState('load')

    await page.getByRole('tab', { name: 'Users' }).click()

    const alert = permissionAlert(page)
    await expect(alert).toBeVisible({ timeout: 10000 })

    const alertText = (await alert.textContent()) ?? ''
    expect(alertText).toContain('Permission Denied')
    expect(alertText).toContain('Action: read')
    expect(alertText).toContain('Resource: system::permissions')

    await expect(alert.locator('a[href="/permissions/access-requests"]')).toBeVisible()
  })

  test('Dialog permission errors show structured message (MCP register server)', async ({
    page,
  }) => {
    // Server list loads (200), the create mutation is denied (403).
    await page.route(/\/api\/v1\/mcp\/servers(\?.*)?$/, (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill(forbidden('integration::mcp_hub', 'create'))
      }
      return route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify([]) })
    })

    await page.goto('/mcp')
    await page.waitForLoadState('load')

    await page.getByRole('button', { name: 'Register Server' }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()

    // Fill the minimal valid form and submit
    await dialog.getByLabel('Slug').fill('e2e-denied-server')
    await dialog.getByLabel('Base URL').fill('http://127.0.0.1:9999')
    await dialog.getByRole('button', { name: /^save$/i }).click()

    // Dialog Error Handling Standard: PermissionDeniedAlert inside DialogContent
    const dialogAlert = dialog.locator('[role="alert"]').filter({ hasText: /Permission Denied:/ })
    await expect(dialogAlert).toBeVisible({ timeout: 10000 })

    const alertText = (await dialogAlert.textContent()) ?? ''
    expect(alertText).toContain('Action: create')
    expect(alertText).toContain('Resource: integration::mcp_hub')

    await expect(
      dialogAlert.locator('a[href="/permissions/access-requests"]'),
    ).toBeVisible()

    // The dialog stays open so the user can correct / retry
    await expect(dialog).toBeVisible()
  })

  test('Access Requests page is accessible without permissions', async ({ page }) => {
    // Access Requests page must be readable by every authenticated user
    await page.goto('/permissions/access-requests')
    await page.waitForLoadState('load')

    // No permission surface
    await expect(permissionAlert(page)).toHaveCount(0)

    // Both tabs are present
    await expect(page.getByRole('tab', { name: 'Pending Requests' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'My Requests' })).toBeVisible()
  })

  test('Request Access link navigation works', async ({ page }) => {
    await page.route(/\/api\/v1\/agents\/types(\?.*)?$/, (route) => route.fulfill(forbidden('agent')))

    await page.goto('/agents')
    await page.waitForLoadState('load')

    const alert = permissionAlert(page)
    await expect(alert).toBeVisible({ timeout: 10000 })

    await alert.locator('a[href="/permissions/access-requests"]').click()

    await expect(page).toHaveURL(/\/permissions\/access-requests/)
    await expect(page.getByRole('tab', { name: 'Pending Requests' })).toBeVisible()
    await expect(page.getByRole('tab', { name: 'My Requests' })).toBeVisible()
  })
})
