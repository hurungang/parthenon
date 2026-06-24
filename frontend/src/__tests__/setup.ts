import '@testing-library/jest-dom'
import { configure } from '@testing-library/react'
import { vi, afterEach } from 'vitest'

// Mark that we're running in tests so components can disable polling intervals
if (typeof window !== 'undefined') {
  ;(window as any).__VITEST__ = true
}

// Increase async timeout so first-render initialization in jsdom doesn't
// cause false failures (React + MUI warmup on first test in each file).
// 1.5s is sufficient; per-test overrides can be applied where genuinely needed.
configure({ asyncUtilTimeout: 1500 })

// Mock apiClient globally to prevent real network calls from polling intervals.
// Many components (AppShell, useInterveneRequests, etc.) make HTTP calls via apiClient.
// In tests, these should resolve instantly with mock data.
// Individual tests can override this mock if they need different behavior.
vi.mock('../api/apiClient', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ data: null }),
    post: vi.fn().mockResolvedValue({ data: null }),
    put: vi.fn().mockResolvedValue({ data: null }),
    patch: vi.fn().mockResolvedValue({ data: null }),
    delete: vi.fn().mockResolvedValue({ data: null }),
  },
}))

// DO NOT enable fake timers globally - it breaks waitFor() and other async operations.
// Instead, tests with polling intervals should either:
// 1. Mock the polling hook/function entirely: vi.mock('../hooks/useInterveneRequests', ...)
// 2. Use vi.useFakeTimers() in a specific test + restore real timers before waitFor()
// 3. Mock the API functions that the hook calls: vi.mock('../api/interveneApi', ...)
// 4. Increase test timeout if the interval is legitimate

// Clean up any pending timers after each test to prevent test pollution
afterEach(() => {
  vi.clearAllTimers()
  // Restore real timers in case a test enabled fake timers
  if (vi.isFakeTimers()) {
    vi.useRealTimers()
  }
})
