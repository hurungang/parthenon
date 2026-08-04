import { defineConfig, devices } from '@playwright/test'

/**
 * Demo config — runs tests in headed mode with configurable speed.
 * Extends the dev-server config (uses localhost:5173).
 *
 * Speed is controlled via DEMO_SPEED env var:
 *   fast   → 1000ms slowMo
 *   normal → 5000ms slowMo (default)
 *   slow   → 10000ms slowMo
 *
 * Usage:
 *   $env:DEMO_SPEED="normal"; npx playwright test --config=playwright.demo.config.ts --project=chromium --grep "..."
 */
const speedMap: Record<string, number> = {
  fast: 1000,
  normal: 5000,
  slow: 10000,
}

const speed = process.env.DEMO_SPEED || 'normal'
const slowMo = speedMap[speed] ?? 5000

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/auth-required/**',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    launchOptions: {
      slowMo,
    },
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
      },
    },
  ],
})
