import { defineConfig, devices } from '@playwright/test'

/**
 * Dev-server config — runs tests against the already-running Vite dev server
 * instead of vite preview (localhost:4173).
 * 
 * NOTE: Tests in tests/auth-required/ are excluded by default because they
 * require real Keycloak authentication with test users. Run them separately with:
 *   npm run test:e2e:auth-required
 * Or:
 *   npx playwright test tests/auth-required --config=playwright.dev.config.ts
 */
export default defineConfig({
  testDir: './tests',
  testIgnore: '**/auth-required/**', // Exclude auth-required tests from default run
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
