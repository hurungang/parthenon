import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import React from 'react'

/**
 * FIX-20260929-043443 reproduction — OIDC workspace round-trip drops the
 * tenant binding.
 *
 * User story: a visitor on /login?workspace=test-com resolves the
 * workspace card (sessionStorage['parthenon_tenant_slug'] = 'test-com'),
 * clicks the SSO button, authenticates at the provider, and lands back on
 * /callback?code=…. After the exchange completes the user must arrive on
 * /dashboard with the workspace tenant binding INTACT and RE-ASSERTED for
 * the new session — every other auth flow does exactly this
 * (LoginPage.handlePasswordSignIn → setResolvedTenantSlug(result.tenant_slug),
 * SignUpPage → setResolvedTenantSlug(result.slug)).
 *
 * Break point under test: OidcCallback.tsx (L62-77 completion handler)
 * NEVER binds the tenant — it does not import anything from tenantAuthApi.
 * The pre-redirect binding survives only PASSIVELY (sessionStorage is not
 * touched on the same-tab round-trip), so:
 *   - the passive-survival controls below PASS today, and
 *   - the two contract tests FAIL: the callback neither re-binds the
 *     workspace authoritatively nor restores it when the tab lost the
 *     binding during the provider round-trip (new-tab restore / storage
 *     eviction) — in that state the dashboard session binds to NO tenant
 *     and the backend rejects the workspace API calls.
 */

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

// Mock MUI icons
vi.mock('@mui/icons-material', () => ({
  default: {},
  __esModule: true,
}))

// Mock react-router-dom navigate
const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock authStore — OidcCallback only consumes setToken
const mockSetToken = vi.fn()
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    setToken: mockSetToken,
  }),
}))

// Mock tenant auth API — FULL surface so the fixed component can import
// anything the module exports without touching this mock. The spy
// `mockSetResolvedTenantSlug` is the assertion target: a sign-in
// completion that binds the workspace MUST call it.
const mockSetResolvedTenantSlug = vi.fn()
const mockGetResolvedTenantSlug = vi.fn()
const mockSetRememberedTenantSlug = vi.fn()
const mockGetRememberedTenantSlug = vi.fn()
vi.mock('../api/tenantAuthApi', () => ({
  setResolvedTenantSlug: (slug: string | null) => mockSetResolvedTenantSlug(slug),
  getResolvedTenantSlug: () => mockGetResolvedTenantSlug(),
  setRememberedTenantSlug: (slug: string | null) => mockSetRememberedTenantSlug(slug),
  getRememberedTenantSlug: () => mockGetRememberedTenantSlug(),
  discoverTenant: vi.fn(),
  loginPassword: vi.fn(),
  registerAccount: vi.fn(),
  getMyTenantMemberships: vi.fn(),
}))

import { OidcCallback } from '../pages/auth/OidcCallback'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const TENANT_SLUG = 'test-com'

/**
 * A realistic OIDC access token: a well-formed JWT whose payload carries
 * standard identity claims and — exactly as the platform's OIDC path
 * yields today — NO `tenant` claim (nothing provisions it; see
 * backend/app/middleware/auth.py::_check_tenant_claim expectations).
 */
function oidcTokenWithoutTenantClaim(): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=/g, '')
  const exp = Math.floor(Date.now() / 1000) + 3600
  return [
    b64({ alg: 'RS256', typ: 'JWT', kid: 'test-key' }),
    b64({
      sub: 'alice-from-external-idp',
      email: 'alice@example.com',
      name: 'Alice',
      preferred_username: 'alice',
      exp,
      iat: Math.floor(Date.now() / 1000),
    }),
    'fake-sig',
  ].join('.')
}

const TOKEN_EXCHANGE_RESPONSE = {
  access_token: oidcTokenWithoutTenantClaim(),
  refresh_token: 'refresh-abc',
  id_token: 'id-token-abc',
}

/** Simulate the provider round-trip landing on /callback?code=… */
function landOnCallbackWithCode() {
  window.history.replaceState({}, '', '/callback?code=e2e-auth-code&state=x')
  // The workspace card stored the PKCE verifier before the redirect
  sessionStorage.setItem('pkce_code_verifier', 'pkce-verifier-123')
}

function mountCallback() {
  render(
    React.createElement(MemoryRouter, null, React.createElement(OidcCallback)),
  )
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('OidcCallback — workspace tenant binding across the provider round-trip (FIX-20260929-043443)', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    localStorage.clear()
    landOnCallbackWithCode()

    fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(TOKEN_EXCHANGE_RESPONSE), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // ── Controls (document the passive survival that masked the bug) ──────────

  it('CONTROL: completes the exchange and navigates to /dashboard', async () => {
    mountCallback()
    await waitFor(() => {
      expect(mockSetToken).toHaveBeenCalledWith(TOKEN_EXCHANGE_RESPONSE.access_token)
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('CONTROL: the pre-redirect binding survives passively (sessionStorage untouched)', async () => {
    sessionStorage.setItem('parthenon_tenant_slug', TENANT_SLUG)
    mountCallback()
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })
    // Passive survival — the component never touches the key either way.
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe(TENANT_SLUG)
  })

  // ── Failing contract tests (the actual repro) ─────────────────────────────

  it('re-binds the workspace tenant authoritatively on sign-in completion (parity with password login / sign-up)', async () => {
    sessionStorage.setItem('parthenon_tenant_slug', TENANT_SLUG)
    mountCallback()
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })

    // The sign-in completion must RE-ASSERT the workspace binding for the
    // freshly authenticated session — exactly what the password flow does
    // (LoginPage.handlePasswordSignIn) and what sign-up does (SignUpPage).
    // OidcCallback never calls setResolvedTenantSlug → the binding is not
    // bound to the authenticated session, only carried by storage luck.
    expect(mockSetResolvedTenantSlug).toHaveBeenCalledWith(TENANT_SLUG)
  })

  it('restores the workspace tenant binding when the tab lost it during the provider round-trip', async () => {
    // The workspace card bound the slug before the redirect…
    sessionStorage.setItem('parthenon_tenant_slug', TENANT_SLUG)
    // …but the binding is gone when the provider returns (new-tab restore,
    // browser storage eviction). The callback is the LAST chance to
    // recover the workspace for this authenticated session.
    sessionStorage.removeItem('parthenon_tenant_slug')

    mountCallback()
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })

    // User-visible contract: the post-callback dashboard session is bound
    // to the workspace the sign-in was started from — API calls must carry
    // X-Tenant: test-com (apiClient reads this key per request).
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe(TENANT_SLUG)
    expect(mockSetResolvedTenantSlug).toHaveBeenCalledWith(TENANT_SLUG)
  })
})
