/**
 * PlatformAdminRoute — guard for the /platform/* console (Phase 6.2).
 *
 * - Unauthenticated → redirect to /login
 * - multiTenancyEnabled resolved false → redirect to /dashboard (routes
 *   absent entirely when the switch is off); null (discovery in flight)
 *   renders nothing instead of bouncing deep-links prematurely
 * - Super admin → children render (bootstrap platform administrator)
 * - Non-platform-admin (probe 403) → access-denied card, no children
 * - Probe success → children render
 * - Probe network error → defensively blocked
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

const authState = {
  isAuthenticated: true,
  isLoading: false,
  isSuperAdmin: false,
  multiTenancyEnabled: true,
}

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => authState,
}))

const getPlatformSettings = vi.fn()
vi.mock('../api/platformAdminApi', () => ({
  getPlatformSettings: (...args: unknown[]) => getPlatformSettings(...args),
}))

import { PlatformAdminRoute } from '../app/PlatformAdminRoute'

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{location.pathname}</div>
}

function renderRoute() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/platform/tenants']}>
        <Routes>
          <Route
            path="/platform/tenants"
            element={
              <PlatformAdminRoute>
                <div data-testid="platform-console">CONSOLE</div>
              </PlatformAdminRoute>
            }
          />
          <Route path="/login" element={<LocationProbe />} />
          <Route path="/dashboard" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PlatformAdminRoute', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.isAuthenticated = true
    authState.isLoading = false
    authState.isSuperAdmin = false
    authState.multiTenancyEnabled = true
  })

  it('renders children for the super admin without probing', async () => {
    authState.isSuperAdmin = true
    renderRoute()
    await waitFor(() => {
      expect(screen.getByTestId('platform-console')).toBeDefined()
    })
    expect(getPlatformSettings).not.toHaveBeenCalled()
  })

  it('renders children when the probe succeeds (platform admin)', async () => {
    getPlatformSettings.mockResolvedValue({ items: [] })
    renderRoute()
    await waitFor(() => {
      expect(screen.getByTestId('platform-console')).toBeDefined()
    })
    expect(getPlatformSettings).toHaveBeenCalled()
  })

  it('redirects to /dashboard when multi-tenancy is off', async () => {
    authState.multiTenancyEnabled = false
    renderRoute()
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/dashboard')
    })
    expect(screen.queryByTestId('platform-console')).toBeNull()
    expect(getPlatformSettings).not.toHaveBeenCalled()
  })

  it('redirects unauthenticated users to /login', async () => {
    authState.isAuthenticated = false
    renderRoute()
    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/login')
    })
    expect(screen.queryByTestId('platform-console')).toBeNull()
  })

  it('shows access denied (not children) when the probe is 403', async () => {
    const axiosError = Object.assign(new Error('denied'), {
      isAxiosError: true,
      response: { status: 403 },
    })
    getPlatformSettings.mockRejectedValue(axiosError)
    renderRoute()
    await waitFor(() => {
      expect(screen.getByText('platform.accessDenied.title')).toBeDefined()
    })
    expect(screen.queryByTestId('platform-console')).toBeNull()
  })

  it('blocks defensively on non-403 probe errors', async () => {
    getPlatformSettings.mockRejectedValue(new Error('network down'))
    renderRoute()
    await waitFor(() => {
      expect(screen.getByText('platform.accessDenied.message')).toBeDefined()
    })
    expect(screen.queryByTestId('platform-console')).toBeNull()
  })
})
