import { defineConfig, devices } from '@playwright/test'

/**
 * Dev-server config — runs tests against the already-running Vite dev server
 * instead of vite preview (localhost:4173).
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
