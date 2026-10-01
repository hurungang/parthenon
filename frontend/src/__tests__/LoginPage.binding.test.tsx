/**
 * LoginPage — workspace-binding safety contract (FIX-20260929-121120, Defect B).
 *
 * Production observed a dashboard request carrying `X-Tenant: org-a` for a
 * tenant that does not exist. The binding-safety contract under test:
 *
 * 1. A slug may ONLY be bound to the session (sessionStorage
 *    `parthenon_tenant_slug`, which apiClient's request interceptor turns
 *    into the `X-Tenant` header on EVERY call) after a SUCCESSFUL discovery
 *    (`GET /auth/tenant?slug=` returned an active tenant).
 * 2. When a stale/never-verified binding is discovered to be unknown, it
 *    must be CLEANED and the user must land on the find-workspace step —
 *    never left bound, and never bounced to /login.
 * 3. A fail-closed 403 unknown-slug rejection (wire shape
 *    `403 {"detail": "Tenant could not be resolved"}` from
 *    TenantResolutionMiddleware) must self-heal: clear the invalid binding
 *    and return the user to find-workspace — not a /login redirect loop.
 * 4. An abandoned slow lookup must never bind its slug after the user has
 *    moved on (late-continuation race).
 *
 * Mechanics: the GLOBAL setup file (`setup.ts`) replaces `../api/apiClient`
 * with inert fns, so this file restores the REAL module and drives it
 * through a recording axios adapter — the real request pipeline
 * (sessionStorage binding → request interceptor → X-Tenant header → route)
 * is observed, with only the network boundary faked.
 *
 * Break-point notes for the developer (where an unverified slug binds):
 * - `OidcCallback.tsx` `resolveIntendedTenantSlug()` (L67-78) takes the
 *   FIRST non-empty of token claim → sessionStorage binding → remembered
 *   localStorage hint → in-memory memo and the completion handler (L149-155)
 *   binds it UNCONDITIONALLY — no discovery verification. A stale
 *   `org-a` in either storage key is re-bound and sent to the dashboard.
 * - `LoginPage.tsx` mount auto-resolve (L202-207) on a null discovery
 *   clears ONLY the remembered hint (`parthenon_login_tenant`), NEVER the
 *   session binding (`parthenon_tenant_slug`) — the stale binding keeps
 *   flowing out via the apiClient interceptor.
 * - `apiClient.ts` response interceptor (L41-64) does nothing for the
 *   fail-closed unknown-slug 403 (no `required_permission` body) — the
 *   error is swallowed by query callers and the binding survives.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import React from 'react'

// ── Network boundary ──────────────────────────────────────────────────────────
// The global setup.ts mocks `../api/apiClient` with inert fns; this file
// restores the REAL module AND routes axios through a recording adapter so
// the REAL pipeline is exercised: sessionStorage binding → apiClient request
// interceptor → X-Tenant header → routed fake response.
//
// IMPORTANT: `apiClient`'s transitive `import axios from 'axios'` must
// resolve to the SAME module instance this file patches — that only holds if
// 'axios' itself is mocked here (mocking the apiClient module alone left two
// axios instances and real network calls in a probe). The thunk indirection
// lets beforeEach install a fresh recording adapter per test.
const adapterHolder = vi.hoisted(() => ({
  fn: null as null | ((config: InternalAxiosRequestConfig) => Promise<AxiosResponse>),
}))

vi.mock('axios', async (importOriginal) => {
  const actual = await importOriginal<typeof import('axios')>()
  actual.default.defaults.adapter = (async (config: InternalAxiosRequestConfig) => {
    if (!adapterHolder.fn) throw new Error('axios recording adapter not installed for this test')
    return adapterHolder.fn(config)
  }) as typeof actual.default.defaults.adapter
  return actual
})

vi.mock('../api/apiClient', async (importOriginal) => {
  return await importOriginal<typeof import('../api/apiClient')>()
})

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

vi.mock('@mui/icons-material/LockOutlined', () => ({ default: () => null }))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

// Mock authStore — LoginPage is rendered without AuthProvider; tenancy ON,
// no host-derived tenant (the workspace-address flow is active).
let mockMultiTenancyEnabled: boolean | null = true
const mockRefreshProviders = vi.fn()
vi.mock('../stores/authStore', () => ({
  useAuthStore: () => ({
    login: vi.fn(),
    isAuthenticated: false,
    token: null,
    claims: null,
    logout: vi.fn(),
    setToken: vi.fn(),
    multiTenancyEnabled: mockMultiTenancyEnabled,
    resolvedTenant: null,
    refreshProviders: mockRefreshProviders,
  }),
}))

import { LoginPage } from '../pages/auth/LoginPage'

// ── Recording axios adapter (network boundary) ────────────────────────────────

interface RecordedCall {
  method: string
  url: string
  tenantHeader: string | null
}

let calls: RecordedCall[] = []
type RouteHandler = (config: InternalAxiosRequestConfig) => Promise<AxiosResponse> | AxiosResponse
const routes = new Map<string, RouteHandler>()

const ACME_ACTIVE = { slug: 'acme', name: 'Acme Corp', status: 'active', sign_in_ready: true }
const SLOW_ORG_ACTIVE = { slug: 'slow-org', name: 'Slow Org', status: 'active', sign_in_ready: true }

function tenantHeaderOf(config: InternalAxiosRequestConfig): string | null {
  const raw =
    ((config.headers as { toJSON?: () => Record<string, unknown> } | undefined)?.toJSON?.() ??
      (config.headers as unknown as Record<string, unknown>)) ??
    {}
  for (const [key, value] of Object.entries(raw)) {
    if (key.toLowerCase() === 'x-tenant') return String(value)
  }
  return null
}

function respond(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  return {
    data,
    status,
    statusText: status === 200 ? 'OK' : 'Forbidden',
    headers: {},
    config,
  } as AxiosResponse
}

/** The real fail-closed rejection wire shape of TenantResolutionMiddleware. */
function failClosedUnknownSlug(config: InternalAxiosRequestConfig): never {
  throw new AxiosError(
    'Request failed with status code 403',
    AxiosError.ERR_BAD_REQUEST,
    config,
    undefined,
    {
      data: { detail: 'Tenant could not be resolved' },
      status: 403,
      statusText: 'Forbidden',
      headers: {},
      config,
    } as AxiosResponse,
  )
}

function discoverySlug(config: InternalAxiosRequestConfig): string | undefined {
  return (config.params as { slug?: string } | undefined)?.slug
}

function defaultRoutes(): void {
  routes.clear()
  routes.set('get /auth/tenant', (config) => {
    const slug = discoverySlug(config)
    return respond(config, {
      multi_tenancy_enabled: true,
      tenant: slug === 'acme' ? ACME_ACTIVE : null,
    })
  })
  routes.set('get /system/identity-providers', (config) =>
    respond(config, { items: [], total: 0 }),
  )
  routes.set('get /system/super-admin/status', (config) =>
    respond(config, { is_enabled: false, username: null, last_login_at: null, env_controlled: false }),
  )
}

// ── window.location stub (records /login bounces without real navigation) ────

const realLocation = window.location
let locationStub: {
  href: string
  pathname: string
  origin: string
  assign: ReturnType<typeof vi.fn>
  replace: ReturnType<typeof vi.fn>
}

// The recording adapter is installed through `adapterHolder` (see the
// 'axios' mock above): beforeEach swaps in a fresh per-test instance.
beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  calls = []
  mockNavigate.mockClear()
  mockRefreshProviders.mockClear()
  mockMultiTenancyEnabled = true
  defaultRoutes()

  adapterHolder.fn = async (config) => {
    const method = (config.method ?? 'get').toLowerCase()
    const url = config.url ?? ''
    calls.push({ method, url, tenantHeader: tenantHeaderOf(config) })
    const handler = routes.get(`${method} ${url}`)
    if (!handler) throw new Error(`Unexpected ${method.toUpperCase()} ${url} in test — add a route`)
    return await handler(config)
  }

  locationStub = {
    href: 'http://localhost/login',
    pathname: '/login',
    origin: 'http://localhost',
    assign: vi.fn(),
    replace: vi.fn(),
  }
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: locationStub,
  })
})

afterEach(() => {
  adapterHolder.fn = null
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: realLocation,
  })
})

// ── Helpers ───────────────────────────────────────────────────────────────────

function Wrapper({ children, initialEntries }: { children?: React.ReactNode; initialEntries?: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(
    QueryClientProvider,
    { client: qc },
    React.createElement(MemoryRouter, { initialEntries }, children),
  )
}

function renderLogin(initialEntries?: string[]) {
  return render(React.createElement(LoginPage), {
    wrapper: (props: { children?: React.ReactNode }) =>
      React.createElement(Wrapper, { initialEntries }, props.children),
  })
}

async function findAndSubmitWorkspace(slug: string): Promise<void> {
  await waitFor(() => expect(screen.getByTestId('workspace-finder-form')).toBeDefined())
  fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), {
    target: { value: slug },
  })
  fireEvent.click(screen.getByTestId('find-workspace-submit'))
}

function expectNoCallCarriedSlug(slug: string): void {
  const leaked = calls.filter((c) => c.tenantHeader === slug).map((c) => `${c.method} ${c.url}`)
  expect(
    leaked,
    `UNVERIFIED SLUG LEAKED ON API CALLS (FIX-20260929-121120 / Defect B): requests went out with ` +
      `X-Tenant: ${slug} although discovery never verified that slug — an unverified binding reached ` +
      `apiClient's request interceptor. Expected end state: a slug is bound only after a successful ` +
      `discovery, so no call may carry it.`,
  ).toEqual([])
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('LoginPage — workspace binding safety (FIX-20260929-121120, Defect B)', () => {
  it('B1: cleans a stale session binding that discovery reports unknown and never leaks it on an API call', async () => {
    // Stale production state: a bound slug that does not exist + the
    // remembered hint that led to it.
    sessionStorage.setItem('parthenon_tenant_slug', 'org-a')
    localStorage.setItem('parthenon_login_tenant', 'org-a')

    renderLogin(['/login'])

    // Discovery for org-a returns null (unknown/deleted, uniform response)
    // → the page must fall back to the finder AND clean the stale binding.
    await waitFor(() => expect(screen.getByTestId('workspace-finder-form')).toBeDefined())
    expect(
      sessionStorage.getItem('parthenon_tenant_slug'),
      'STALE BINDING NOT CLEANED (FIX-20260929-121120 / B1): discovery reported the bound slug ' +
        'unknown, but the session binding parthenon_tenant_slug was left in place — the apiClient ' +
        'interceptor keeps attaching X-Tenant: org-a to every subsequent call. The binding must be ' +
        'cleared together with the remembered hint.',
    ).toBeNull()

    // Positive control: the bootstrap calls really flowed through the
    // recording adapter (guards against a silently-dead harness).
    expect(calls.map((c) => c.url)).toEqual(
      expect.arrayContaining(['/auth/tenant', '/system/identity-providers']),
    )

    // Recovery: the visitor finds their real workspace; a VERIFIED bind works.
    await findAndSubmitWorkspace('acme')
    await waitFor(() => expect(screen.getByTestId('password-signin-form')).toBeDefined())
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe('acme')

    // SAFETY: no request may ever have carried the unverified slug.
    expectNoCallCarriedSlug('org-a')
  })

  it('B2: a fail-closed 403 unknown-slug rejection clears the binding and lands on find-workspace — never a /login bounce', async () => {
    // The discovered failure mode: a slug is bound (as OidcCallback's
    // unverified storage bind does), the login page's own bootstrap calls
    // go out with X-Tenant: org-a and the backend rejects them fail-closed.
    sessionStorage.setItem('parthenon_tenant_slug', 'org-a')
    routes.set('get /system/identity-providers', (config) => {
      if (tenantHeaderOf(config) === 'org-a') failClosedUnknownSlug(config)
      return respond(config, { items: [], total: 0 })
    })
    routes.set('get /system/super-admin/status', (config) => {
      if (tenantHeaderOf(config) === 'org-a') failClosedUnknownSlug(config)
      return respond(config, {
        is_enabled: false,
        username: null,
        last_login_at: null,
        env_controlled: false,
      })
    })

    renderLogin(['/login'])

    // The user must land on the find-workspace step (the page degrades to
    // the finder) — NOT be bounced to /login.
    await waitFor(() => expect(screen.getByTestId('workspace-finder-form')).toBeDefined())

    // Positive control: the fail-closed rejection really happened on the wire
    // (guards against a silently-dead harness).
    expect(calls.map((c) => c.url)).toEqual(
      expect.arrayContaining(['/system/identity-providers', '/system/super-admin/status']),
    )

    expect(
      locationStub.href,
      'WRONG RECOVERY (FIX-20260929-121120 / B2): an unknown-slug 403 must NOT trigger a redirect ' +
        'to /login — that reproduces the bounce loop. The user must land on find-workspace.',
    ).toBe('http://localhost/login')

    // SELF-HEAL: the fail-closed rejection must clear the invalid binding.
    expect(
      sessionStorage.getItem('parthenon_tenant_slug'),
      'FAIL-CLOSED REJECTION NOT SELF-HEALED (FIX-20260929-121120 / B2): the backend rejected the ' +
        'bound slug with 403 {"detail": "Tenant could not be resolved"}, but the invalid binding ' +
        'parthenon_tenant_slug=org-a survived — nothing clears an unknown-slug binding after a ' +
        'fail-closed rejection.',
    ).toBeNull()

    // Recovery: the visitor can then bind their real workspace.
    await findAndSubmitWorkspace('acme')
    await waitFor(() => expect(screen.getByTestId('password-signin-form')).toBeDefined())
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe('acme')
  })

  it('B3: a slow Continue lookup never binds its slug after the user navigated away and bound another workspace', async () => {
    // Race pin. Within one mount, re-submitting while a lookup is in flight
    // is blocked by construction (the Continue button disables + the
    // `lookingUp` guard), so the REAL hole is the lookup promise outliving
    // the component: navigating away mid-lookup (Back, signup link) leaves
    // the in-flight discovery running with no cancellation, and its
    // continuation binds whenever it resolves — clobbering a later binding.
    let releaseSlow!: () => void
    const slowGate = new Promise<void>((resolve) => {
      releaseSlow = resolve
    })
    routes.set('get /auth/tenant', async (config) => {
      const slug = discoverySlug(config)
      if (slug === 'slow-org') {
        await slowGate
        return respond(config, { multi_tenancy_enabled: true, tenant: SLOW_ORG_ACTIVE })
      }
      return respond(config, {
        multi_tenancy_enabled: true,
        tenant: slug === 'acme' ? ACME_ACTIVE : null,
      })
    })

    // Attempt 1: slow discovery in flight, then the visitor navigates away.
    const first = renderLogin(['/login'])
    await waitFor(() => expect(screen.getByTestId('workspace-finder-form')).toBeDefined())
    fireEvent.change(screen.getByLabelText('auth.findWorkspace.addressLabel'), {
      target: { value: 'slow-org' },
    })
    fireEvent.click(screen.getByTestId('find-workspace-submit'))
    await waitFor(() =>
      expect(screen.getByTestId('find-workspace-submit').textContent).toContain(
        'auth.findWorkspace.lookup',
      ),
    )
    first.unmount()

    // Attempt 2: a different workspace is found and VERIFIED-bound.
    renderLogin(['/login'])
    await findAndSubmitWorkspace('acme')
    await waitFor(() => expect(screen.getByTestId('password-signin-form')).toBeDefined())
    expect(sessionStorage.getItem('parthenon_tenant_slug')).toBe('acme')
    expect(localStorage.getItem('parthenon_login_tenant')).toBe('acme')
    // Positive control: the acme discovery really resolved through the adapter.
    const acmeDiscoveries = calls.filter(
      (c) => c.url === '/auth/tenant' && c.tenantHeader !== 'slow-org',
    )
    expect(acmeDiscoveries.length).toBeGreaterThanOrEqual(1)

    // The abandoned slow lookup resolves late — it must NOT re-bind.
    releaseSlow()
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(
      sessionStorage.getItem('parthenon_tenant_slug'),
      'LATE BIND RACE (FIX-20260929-121120 / B3): the abandoned slow discovery for slow-org resolved ' +
        'after the user had navigated away and bound acme — its continuation still bound slow-org, ' +
        'clobbering the verified binding. The lookup continuation must be cancelled/stale-guarded ' +
        '(like the mount auto-resolve effect) before binding.',
    ).toBe('acme')
    expect(
      localStorage.getItem('parthenon_login_tenant'),
      'LATE BIND RACE (FIX-20260929-121120 / B3): the abandoned slow lookup also overwrote the ' +
        'remembered-workspace hint with slow-org.',
    ).toBe('acme')
  })
})
