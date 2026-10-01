import { defineConfig, devices } from '@playwright/test'
import path from 'path'

export default defineConfig({
  testDir: './tests',
  // auth-required/ specs need a live Keycloak + provisioned users (see
  // tests/auth-required/README.md) — excluded from the default run.
  testIgnore: '**/auth-required/**',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run build:e2e && npm run preview',
    cwd: path.resolve(__dirname, '../frontend'),
    url: 'http://localhost:4173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
