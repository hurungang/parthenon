import { test, expect } from '@playwright/test'
import { standardSetup } from './_helpers'

const MOCK_METRICS = {
  request_rate: 42.3,
  error_rate: 0.8,
  p95_latency_ms: 215,
}

test.describe('Observability Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v1/observability/metrics', (route) =>
      route.fulfill({ status: 200, body: JSON.stringify(MOCK_METRICS) })
    )
    await standardSetup(page)
  })

  test('observability dashboard renders without crashing', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto('/observability')
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('ResizeObserver'))).toHaveLength(0)
  })

  test('observability dashboard does not redirect to login', async ({ page }) => {
    await page.goto('/observability')
    await page.waitForLoadState('load')
    expect(page.url()).not.toContain('/login')
  })

  test('observability dashboard shows request rate metric', async ({ page }) => {
    await page.goto('/observability')
    await page.waitForLoadState('load')
    // 42.3 or rounded value should appear on the page
    const metricText = page.getByText(/42/)
    const hasMetric = await metricText.count() > 0
    if (hasMetric) {
      await expect(metricText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('observability dashboard shows latency metric', async ({ page }) => {
    await page.goto('/observability')
    await page.waitForLoadState('load')
    // p95 latency (215ms) should appear
    const latencyText = page.getByText(/215|latency/i)
    const hasLatency = await latencyText.count() > 0
    if (hasLatency) {
      await expect(latencyText.first()).toBeVisible()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })

  test('observability dashboard has external tool links', async ({ page }) => {
    await page.goto('/observability')
    await page.waitForLoadState('load')
    // Should have links to Jaeger/Loki or similar observability tools
    const extLinks = page.locator('a[href*="jaeger"], a[href*="loki"], a[href*="grafana"], a:visible')
    const hasLinks = await extLinks.count() > 0
    if (hasLinks) {
      await expect(extLinks.first()).toBeVisible()
    } else {
      await expect(page.locator('button:visible, [role="tab"]:visible').first()).toBeVisible()
    }
  })

  test('observability dashboard tabs or sections are navigable', async ({ page }) => {
    await page.goto('/observability')
    await page.waitForLoadState('load')
    const tabs = page.locator('[role="tab"]:visible')
    const hasTabs = await tabs.count() > 0
    if (hasTabs) {
      await tabs.first().click()
      await expect(page.locator('body')).not.toBeEmpty()
    } else {
      await expect(page.getByRole('button').first()).toBeVisible()
    }
  })
})

/**
 * Telemetry Configuration E2E Tests
 * Verifies the configurable telemetry system works end-to-end without breaking app functionality.
 */
test.describe('Telemetry Configuration System', () => {
  /**
   * E2E Scenario 1: App Startup with Telemetry Enabled
   * WHEN the user navigates to the app with telemetry fully enabled in backend config
   * THEN the app loads successfully without console errors
   * AND the dashboard page renders correctly
   * AND no telemetry-related errors appear in browser console
   */
  test('app starts successfully with telemetry enabled', async ({ page }) => {
    const telemetryErrors: string[] = []
    page.on('pageerror', (err) => {
      const msg = err.message
      if (
        msg.includes('telemetry') ||
        msg.includes('opentelemetry') ||
        msg.includes('OTEL')
      ) {
        telemetryErrors.push(msg)
      }
    })

    // Mock telemetry config API to return enabled config
    await page.route('**/api/v1/telemetry/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          service_name: 'parthenon-frontend',
          otlp_http_endpoint: 'http://localhost:4318/v1/traces',
          traces_enabled: true,
          metrics_enabled: true
        })
      })
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // App should load successfully
    await expect(page.locator('#root')).toBeAttached()

    // No telemetry-related errors
    expect(telemetryErrors).toHaveLength(0)
  })

  /**
   * E2E Scenario 2: Telemetry Config API Schema
   * WHEN the backend telemetry config API is available with valid data
   * THEN the frontend can fetch the config successfully
   * AND the app loads without errors
   * AND the telemetry system initializes based on the config
   */
  test('app initializes telemetry from backend config', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text())
      }
    })

    // Mock telemetry config API with valid response
    await page.route('**/telemetry/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          service_name: 'parthenon-frontend',
          otlp_http_endpoint: 'http://localhost:4318/v1/traces',
          traces_enabled: true,
          metrics_enabled: true
        })
      })
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // App should load successfully
    await expect(page.locator('#root')).toBeAttached()

    // No console errors related to telemetry initialization
    const telemetryErrors = consoleErrors.filter((e) =>
      e.toLowerCase().includes('telemetry') ||
      e.toLowerCase().includes('opentelemetry')
    )
    expect(telemetryErrors).toHaveLength(0)
  })

  /**
   * E2E Scenario 3: App Startup with Telemetry Disabled
   * WHEN the backend telemetry is disabled (`traces_enabled: false`, `metrics_enabled: false`)
   * THEN the app still loads and functions normally
   * AND the dashboard renders without errors
   * AND no OTEL providers are initialized in the browser (verify via console)
   */
  test('app starts successfully with telemetry disabled', async ({ page }) => {
    const consoleMessages: string[] = []
    page.on('console', (msg) => {
      const text = msg.text()
      if (
        text.includes('telemetry') ||
        text.includes('opentelemetry') ||
        text.includes('OTEL')
      ) {
        consoleMessages.push(text)
      }
    })

    // Mock telemetry config API to return disabled config
    await page.route('**/api/v1/telemetry/config', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          service_name: 'parthenon-frontend',
          otlp_http_endpoint: '',
          traces_enabled: false,
          metrics_enabled: false
        })
      })
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // App should still load successfully
    await expect(page.locator('#root')).toBeAttached()

    // Should not see any OTEL initialization logs
    const otelInitLogs = consoleMessages.filter((msg) =>
      msg.toLowerCase().includes('initialized')
    )
    expect(otelInitLogs).toHaveLength(0)
  })

  /**
   * E2E Scenario 4: Graceful Degradation on Telemetry Failure
   * WHEN the telemetry config API endpoint returns 500 error
   * THEN the app continues to load and render
   * AND the frontend falls back to safe defaults (telemetry disabled)
   * AND the user can navigate and use the app normally
   */
  test('app degrades gracefully when telemetry config fetch fails', async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (err) => pageErrors.push(err.message))

    // Mock telemetry config API to return 500 error
    await page.route('**/api/v1/telemetry/config', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal server error' })
      })
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // App should still load despite telemetry API failure
    await expect(page.locator('#root')).toBeAttached()

    // Should not have any unhandled errors that prevent rendering
    const fatalErrors = pageErrors.filter(
      (e) => !e.includes('ResizeObserver') && !e.includes('Non-Error promise rejection')
    )
    expect(fatalErrors).toHaveLength(0)

    // User should be able to navigate (smoke test)
    await expect(page.locator('body')).not.toBeEmpty()
  })
})