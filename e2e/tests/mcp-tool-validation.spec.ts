import { test, expect } from '@playwright/test'

/**
 * Live-stack only: this spec signs in through the real OIDC provider and runs
 * an agent execution against the real MCP hub. The canonical E2E environment
 * is fully mocked (backend services + Keycloak stopped, static preview on
 * :4173), so the test skips cleanly with a reason when the stack is down and
 * keeps its end-to-end assertions for live runs.
 */
const BACKEND_URL = process.env.E2E_BACKEND_URL ?? 'http://localhost:8000/api/v1'
const LIVE_APP_URL = process.env.E2E_LIVE_APP_URL ?? 'http://localhost:5173'

test.describe('MCP Tool Call Validation', () => {
  test('agent can successfully call MCP tools (supabase and hello-world)', async ({ page, request }) => {
    let stackIsLive = false
    try {
      const [health, app] = await Promise.all([
        request.get(`${BACKEND_URL}/health`, { timeout: 3000, failOnStatusCode: false }),
        request.get(LIVE_APP_URL, { timeout: 3000, failOnStatusCode: false }),
      ])
      stackIsLive = health.ok() && app.ok()
    } catch {
      stackIsLive = false
    }
    test.skip(
      !stackIsLive,
      'Live stack is not running (canonical mocked E2E): needs the Control Center on :8000, Keycloak on :8082 and the dev app on :5173.'
    )

    // Login first — the app login page starts the OIDC flow.
    await page.goto(LIVE_APP_URL)
    await page.waitForLoadState('load')

    const signInButton = page.getByRole('button', { name: /sign in/i })
    if (await signInButton.first().isVisible().catch(() => false)) {
      await signInButton.first().click()
    }

    // OIDC provider (Keycloak) login form
    await page.locator('input[name="username"]').fill(process.env.E2E_TEST_USERNAME ?? 'admin')
    await page.locator('input[name="password"]').fill(process.env.E2E_TEST_PASSWORD ?? 'admin')
    await page.locator('button[type="submit"]').click()

    const appOrigin = new URL(LIVE_APP_URL).origin
    await page.waitForURL((url) => url.origin === appOrigin, { timeout: 30000 })

    // Navigate to the agent types page
    await page.goto(`${LIVE_APP_URL}/agent-types`)
    await page.waitForLoadState('load')

    // Find and click on support_agent
    const agentCard = page.getByText('support_agent').first()
    await expect(agentCard).toBeVisible({ timeout: 10000 })
    await agentCard.click()

    // Launch agent with test input
    const launchButton = page.getByRole('button', { name: /launch|execute/i }).first()
    if (await launchButton.isVisible().catch(() => false)) {
      await launchButton.click()
    }

    // Provide input if needed
    const inputBox = page.locator('textarea, input[type="text"]').first()
    if (await inputBox.isVisible().catch(() => false)) {
      await inputBox.fill('Get project info for iyzwnsvoiqfsgkhjnsyl and call hello world')

      const submitButton = page.getByRole('button', { name: /submit|send/i }).first()
      if (await submitButton.isVisible().catch(() => false)) {
        await submitButton.click()
      }
    }

    // Wait for execution to complete
    await page.waitForTimeout(5000)

    // Check logs or output for MCP tool call success
    const pageContent = await page.content()

    // Look for success indicators or absence of 401 errors
    const has401Error = pageContent.includes('401') && pageContent.includes('Unauthorized')
    const hasMcpError = pageContent.includes('MCP tool call failed')

    // If we see these errors, the test fails
    expect(has401Error).toBe(false)
    expect(hasMcpError).toBe(false)
  })
})
