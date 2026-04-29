import { defineConfig, devices } from '@playwright/test'

const slowMoMap: Record<string, number> = {
  fast: 1000,
  normal: 5000,
  slow: 10000,
}

const speed = process.env.DEMO_SPEED ?? 'normal'
const slowMo = slowMoMap[speed] ?? 800

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    launchOptions: {
      slowMo,
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
