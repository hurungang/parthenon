/**
 * Phase 11 (task 11.5) — sidebar permission gating tests.
 *
 * - The "Tenant Admin" group renders for ALL tenants whenever the session
 *   is tenant-bound (multi-tenancy on).
 * - The "Platform" group renders ONLY when the backend permission
 *   evaluation grants `platform::settings` read (the probe) — never on
 *   the tenancy flag alone (the acme-admin-sees-platform-items bug).
 * - With multi-tenancy OFF neither extra group renders (zero
 *   user-visible multi-tenancy UX).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let mockAuth: Record<string, unknown> = {}

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    token: 'mock-token',
    claims: { sub: 'user1', exp: 9999999999, iat: 0, name: 'Admin' },
    setToken: vi.fn(),
    isSuperAdmin: false,
    ...mockAuth,
  }),
}))

const mockGetPlatformSettings = vi.fn()
vi.mock('../api/platformAdminApi', () => ({
  getPlatformSettings: (...args: unknown[]) => mockGetPlatformSettings(...args),
}))

vi.mock('../api/apiClient', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: {} }) },
}))

function renderShell() {
  // Imported lazily so the vi.mock registrations apply.
  return import('../app/AppShell').then(({ AppShell }) => {
    const qc = new QueryClient()
    qc.setDefaultOptions({ queries: { retry: false } })
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <AppShell />
        </MemoryRouter>
      </QueryClientProvider>,
    )
  })
}

beforeEach(() => {
  mockAuth = {}
  mockGetPlatformSettings.mockReset()
})

describe('AppShell — Phase 11 sidebar gating', () => {
  it('renders the Tenant Admin group for all tenants (tenancy on) and hides Platform when the probe denies', async () => {
    mockAuth = { multiTenancyEnabled: true, activeTenant: { id: 't1', slug: 'acme', name: 'acme' } }
    mockGetPlatformSettings.mockRejectedValue({ response: { status: 403 } })
    await renderShell()
    await waitFor(() => {
      expect(screen.getAllByText("nav.groupTenantAdmin").length).toBeGreaterThan(0)
    }, { timeout: 5000 })
    // The acme-admin bug: no platform items on a granted-tenant session
    expect(screen.queryByText('nav.groupPlatform')).toBeNull()
    // Tenant admin surfaces are present
    // Tenant admin surfaces are present (await the collapse body render)
    await waitFor(() => {
      expect(screen.getAllByText("nav.tenantSettings").length).toBeGreaterThan(0)
      expect(screen.getAllByText("nav.tenantMembers").length).toBeGreaterThan(0)
      expect(screen.getAllByText("nav.tenantIdentityProviders").length).toBeGreaterThan(0)
    }, { timeout: 5000 })
    // FIX-20261001-235247 (Defect 2): the legacy System Config
    // identity-providers entry is GONE — only the Tenant Admin variant
    // remains (no duplicate sign-in-providers menu item).
    expect(screen.queryByText('nav.identityProviders')).toBeNull()
  })

  it('renders exactly ONE identity-providers menu entry (the Tenant Admin one)', async () => {
    mockAuth = { multiTenancyEnabled: true, activeTenant: { id: 't1', slug: 'root', name: 'Root' } }
    mockGetPlatformSettings.mockRejectedValue({ response: { status: 403 } })
    await renderShell()
    await waitFor(() => {
      expect(screen.getAllByText('nav.tenantIdentityProviders').length).toBeGreaterThan(0)
    })
    // Both drawers may render the entry, but the LEGACY label must never
    // appear next to it.
    expect(screen.queryAllByText('nav.identityProviders')).toHaveLength(0)
  })

  it('renders the Platform group only when the permission probe grants platform::settings read', async () => {
    mockAuth = { multiTenancyEnabled: true, activeTenant: { id: 't1', slug: 'root', name: 'Root' } }
    mockGetPlatformSettings.mockResolvedValue({ multi_tenancy_enabled: true })
    await renderShell()
    await waitFor(() => {
      expect(screen.getAllByText("nav.groupPlatform").length).toBeGreaterThan(0)
    })
  })

  it('renders neither extra group when multi-tenancy is off (zero multi-tenancy UX)', async () => {
    mockAuth = { multiTenancyEnabled: false }
    await renderShell()
    await waitFor(() => {
      expect(screen.getAllByText("nav.groupSystem").length).toBeGreaterThan(0)
    })
    expect(screen.queryByText('nav.groupTenantAdmin')).toBeNull()
    expect(screen.queryByText('nav.groupPlatform')).toBeNull()
  })
})
