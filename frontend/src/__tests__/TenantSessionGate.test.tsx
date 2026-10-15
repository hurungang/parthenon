/**
 * TenantSessionGate — multi-tenant session binding contract.
 *
 * Pins the FIX for the multi-tenant login loop:
 * - Picker skipped entirely when the token's tenant claim already matches
 *   an active membership (one session = one tenant; auto-confirm).
 * - handleSelect re-runs provider discovery for the newly bound slug
 *   BEFORE calling login(), so the OIDC redirect targets the selected
 *   organization's own issuer.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// ── Controllable auth-store mock ──────────────────────────────────────────────

interface GateProps {
  isAuthenticated?: boolean
  isSuperAdmin?: boolean
  claims?: { sub?: string; jti?: string; iat?: number; tenant?: string } | null
  multiTenancyEnabled?: boolean | null
  availableTenants?: Array<{ tenant_id: string; tenant_slug: string; tenant_name: string; tenant_role: 'member' | 'tenant_admin' | 'platform_admin'; is_default?: boolean }>
  login?: ReturnType<typeof vi.fn>
  refreshProviders?: ReturnType<typeof vi.fn>
}

let gateProps: GateProps = {}
const mockLogin = vi.fn(async () => true)
const mockRefreshProviders = vi.fn(async () => undefined)

vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    isAuthenticated: gateProps.isAuthenticated ?? false,
    isSuperAdmin: gateProps.isSuperAdmin ?? false,
    claims: gateProps.claims ?? null,
    multiTenancyEnabled: gateProps.multiTenancyEnabled ?? true,
    availableTenants: gateProps.availableTenants ?? [],
    login: gateProps.login ?? mockLogin,
    refreshProviders: gateProps.refreshProviders ?? mockRefreshProviders,
  }),
}))

import { TenantSessionGate } from '../components/auth/TenantSessionGate'

const ORG_A = { tenant_id: 't-a', tenant_slug: 'org-a', tenant_name: 'Org A', tenant_role: 'member' as const }
const ORG_B = { tenant_id: 't-b', tenant_slug: 'org-b', tenant_name: 'Org B', tenant_role: 'member' as const }

describe('TenantSessionGate', () => {
  beforeEach(() => {
    sessionStorage.clear()
    gateProps = {}
    mockLogin.mockClear()
    mockLogin.mockImplementation(async () => true)
    mockRefreshProviders.mockClear()
    mockRefreshProviders.mockImplementation(async () => undefined)
  })

  it('auto-confirms (skips the picker) when the token tenant claim matches an active membership', () => {
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1, tenant: 'org-a' },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
    }
    render(React.createElement(TenantSessionGate))
    expect(screen.queryByTestId('tenant-picker')).toBeNull()
    // Auto-confirm persists for this session key.
    expect(sessionStorage.getItem('parthenon_tenant_confirmed')).toBe('jti-1')
  })

  it('shows the picker for multi-org users with an unbound token (no tenant claim)', () => {
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1 },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
    }
    render(React.createElement(TenantSessionGate))
    expect(screen.getByTestId('tenant-picker')).toBeDefined()
  })

  it('skips the picker when the BOUND workspace slug matches a membership (no tenant claim needed)', () => {
    // The backend injects the tenant claim per-request — it is NEVER in
    // the raw Keycloak JWT.  The bound slug (sessionStorage binding) is
    // the authoritative signal.
    sessionStorage.setItem('parthenon_tenant_slug', 'org-a')
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1 },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
    }
    render(React.createElement(TenantSessionGate))
    expect(screen.queryByTestId('tenant-picker')).toBeNull()
    expect(sessionStorage.getItem('parthenon_tenant_confirmed')).toBe('jti-1')
  })

  it('shows the picker AND clears a stale binding when the bound slug is NOT among memberships', () => {
    sessionStorage.setItem('parthenon_tenant_slug', 'org-gone')
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1 },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
    }
    render(React.createElement(TenantSessionGate))
    expect(screen.getByTestId('tenant-picker')).toBeDefined()
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBeNull()
  })

  it('does NOT reopen the picker after a tenant-claim-matching token supersedes a confirmed session', () => {
    sessionStorage.setItem('parthenon_tenant_confirmed', 'jti-0')
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 2, tenant: 'org-b' },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
    }
    render(React.createElement(TenantSessionGate))
    expect(screen.queryByTestId('tenant-picker')).toBeNull()
  })

  it('handleSelect binds the slug, refreshes providers, THEN calls login (order pinned)', async () => {
    const order: string[] = []
    mockRefreshProviders.mockImplementation(async () => { order.push('refreshProviders') })
    mockLogin.mockImplementation(async () => { order.push('login'); return true })
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1 },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
      refreshProviders: mockRefreshProviders,
      login: mockLogin,
    }
    render(React.createElement(TenantSessionGate))
    fireEvent.click(screen.getByText('Org B'))
    await waitFor(() => {
      expect(order).toEqual(['refreshProviders', 'login'])
    })
    // The slug was bound to this tab before discovery/login ran.
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe('org-b')
  })

  it('surfaces an error when login refuses to redirect (no provider for the selected org)', async () => {
    gateProps = {
      isAuthenticated: true,
      claims: { sub: 'u1', jti: 'jti-1', iat: 1 },
      multiTenancyEnabled: true,
      availableTenants: [ORG_A, ORG_B],
      refreshProviders: mockRefreshProviders,
      login: vi.fn(async () => false),
    }
    render(React.createElement(TenantSessionGate))
    fireEvent.click(screen.getByText('Org B'))
    await waitFor(() => {
      expect(screen.getByText('auth.tenantPicker.switchFailed')).toBeDefined()
    })
  })
})
