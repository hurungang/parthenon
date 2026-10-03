import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { ActiveTenant, AuthClaims, AuthState, TenantMembership, TenantDiscovery } from '../types'
import {
  discoverTenant,
  getMyTenantMemberships,
  setResolvedTenantSlug,
  getResolvedTenantSlug,
} from '../api/tenantAuthApi'

// ── Token utilities ────────────────────────────────────────────────────────────

function parseJwt(token: string): AuthClaims | null {
  try {
    const base64Url = token.split('.')[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(base64))
    return payload as AuthClaims
  } catch {
    return null
  }
}

function isTokenExpired(claims: AuthClaims): boolean {
  return Date.now() / 1000 >= claims.exp
}

// ── PKCE utilities ─────────────────────────────────────────────────────────────

function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
}

async function generateCodeVerifier(): Promise<string> {
  const array = new Uint8Array(32)
  crypto.getRandomValues(array)
  return base64UrlEncode(array.buffer)
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(verifier)
  const hash = await crypto.subtle.digest('SHA-256', data)
  return base64UrlEncode(hash)
}

// ── Provider type ──────────────────────────────────────────────────────────────

export interface AvailableProvider {
  scope: string
  providerType: string
  displayName: string
  isEnabled: boolean
}

interface AuthContextValue extends AuthState {
  login: () => void
  logout: () => void
  setToken: (token: string) => void
  availableProviders: AvailableProvider[] | null
  superAdminEnabled: boolean
  isSuperAdmin: boolean
  /**
   * Multi-tenancy: whether the platform tenancy switch is on.
   * `null` = discovery still in flight (callers must stay inert — never
   * treat "unknown" as "off", or deep-links into /platform/* would bounce
   * before the switch state resolves).
   */
  multiTenancyEnabled: boolean | null
  /** Multi-tenancy: tenant resolved from the host at sign-in (null = platform surface) */
  resolvedTenant: TenantDiscovery['tenant'] | null
  /** Multi-tenancy: the authenticated user's active tenant memberships */
  availableTenants: TenantMembership[]
  refreshAvailableTenants: () => Promise<void>
  /**
   * Multi-tenancy: the tenant bound to this session (derived from the
   * token's tenant claim — immutable until sign-out).  Null on the
   * platform surface or when the tenancy switch is off.
   */
  activeTenant: ActiveTenant | null
  /**
   * Re-run provider / super-admin discovery with the CURRENT context.
   * The workspace-address sign-in flow calls this right after binding a
   * tenant slug so the OIDC start config (issuer / client) is resolved
   * for the tenant's provider, not the platform default (the fetch picks
   * up X-Tenant from the per-tab resolved slug).
   */
  refreshProviders: () => Promise<void>
  /**
   * FIX-20261001-235247: drop the host-derived tenant (store state AND the
   * per-tab sessionStorage binding) so the login page's workspace finder
   * becomes reachable after "Use a different workspace" on a host-bound
   * workspace.  Inert when no tenant is resolved.
   */
  clearResolvedTenant: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ───────────────────────────────────────────────────────────────────

const OIDC_AUTHORITY_FALLBACK = import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8082/realms/parthenon'
const OIDC_CLIENT_ID_FALLBACK = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'parthenon-api-ui'
const OIDC_REDIRECT_URI = `${window.location.origin}/callback`

// sessionStorage keys for the OIDC round-trip state (FIX-20260929-043443
// #3): login() persists the CHOSEN authority/client so OidcCallback
// exchanges the code against the SAME tenant-resolved provider the
// authorize redirect started from (a tenant provider with a non-default
// issuer fails the exchange at the platform default). Consumed + cleared
// by the callback; legacy flows fall back to the env defaults.
const OIDC_AUTHORITY_KEY = 'oidc_authority'
const OIDC_CLIENT_ID_KEY = 'oidc_client_id'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(
    () => localStorage.getItem('access_token'),
  )
  const [isLoading] = useState(false)
  const [availableProviders, setAvailableProviders] = useState<AvailableProvider[] | null>(null)
  const [superAdminEnabled, setSuperAdminEnabled] = useState(false)
  const [oidcAuthority, setOidcAuthority] = useState<string>(OIDC_AUTHORITY_FALLBACK)
  const [oidcClientId, setOidcClientId] = useState<string>(OIDC_CLIENT_ID_FALLBACK)
  const [multiTenancyEnabled, setMultiTenancyEnabled] = useState<boolean | null>(null)
  const [resolvedTenant, setResolvedTenant] = useState<TenantDiscovery['tenant'] | null>(null)
  const [availableTenants, setAvailableTenants] = useState<TenantMembership[]>([])
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const claims = useMemo<AuthClaims | null>(() => {
    if (!token) return null
    return parseJwt(token)
  }, [token])

  const isSuperAdmin = useMemo(() => {
    return !!claims && !!(claims as unknown as Record<string, unknown>).is_super_admin
  }, [claims])

  // Active tenant: derived from the token's immutable tenant claim plus
  // the membership list (role).  Null when the claim is absent (platform
  // surface) — one session = one tenant.
  const activeTenant = useMemo<ActiveTenant | null>(() => {
    const slug = (claims as unknown as Record<string, unknown> | null)?.tenant
    if (typeof slug !== 'string' || slug === '') return null
    const membership = availableTenants.find((m) => m.tenant_slug === slug)
    return {
      id: membership?.tenant_id ?? slug,
      slug,
      name: membership?.tenant_name ?? slug,
      role: membership?.tenant_role ?? 'member',
    }
  }, [claims, availableTenants])

  const isAuthenticated = !!token && !!claims && !isTokenExpired(claims)

  const setToken = useCallback((newToken: string) => {
    localStorage.setItem('access_token', newToken)
    setTokenState(newToken)
  }, [])

  // Discover active providers and super admin status on app load.
  // Extracted so the workspace-address sign-in flow can re-run it after
  // binding a tenant (X-Tenant is read from storage at fetch time).
  const discoverProviders = useCallback(async () => {
    try {
      const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
      const headers: Record<string, string> = {}
      const storedToken = localStorage.getItem('access_token')
      if (storedToken) {
        headers.Authorization = `Bearer ${storedToken}`
      }
      // Multi-tenancy: attach the resolved tenant slug so per-tenant
      // provider resolution returns THIS tenant's provider config.
      const tenantSlug = getResolvedTenantSlug()
      if (tenantSlug) {
        headers['X-Tenant'] = tenantSlug
      }

      // Fetch identity providers
      try {
        const providersResp = await fetch(`${apiBase}/system/identity-providers`, { headers })
        if (providersResp.ok) {
          const data = await providersResp.json() as {
            items: Array<{
              provider_scope: string
              provider_type: string
              display_name: string
              is_enabled: boolean
              issuer_url: string
              client_id: string
              ui_client_id?: string
              public_client_id?: string
            }>
          }
          setAvailableProviders(
            data.items.map((p) => ({
              scope: p.provider_scope,
              providerType: p.provider_type,
              displayName: p.display_name,
              isEnabled: p.is_enabled,
            })),
          )
          // Update dynamic OIDC config from discovered user provider
          const userP = data.items.find((p) => p.provider_scope === 'user' && p.is_enabled)
          if (userP) {
            setOidcAuthority(userP.issuer_url)
            setOidcClientId(userP.public_client_id || userP.ui_client_id || userP.client_id || OIDC_CLIENT_ID_FALLBACK)
          }
        }
      } catch {
        // Silently fail; providers may not be configured
      }

      // Fetch super admin status
      try {
        const saResp = await fetch(`${apiBase}/system/super-admin/status`, { headers })
        if (saResp.ok) {
          const saData = await saResp.json() as { is_enabled: boolean }
          setSuperAdminEnabled(saData.is_enabled)
        }
      } catch {
        // Silently fail
      }
    } catch {
      // Silently fail; discovery is best-effort
    }
  }, [token])

  useEffect(() => {
    void discoverProviders()
  }, [discoverProviders])

  // Multi-tenancy: resolve the tenant from the current host on load.
  // Inert when the switch is off (discovery reports enabled=false) so the
  // single-tenant sign-in flow is untouched.
  useEffect(() => {
    const resolveTenant = async () => {
      try {
        const discovery = await discoverTenant()
        setMultiTenancyEnabled(discovery.multi_tenancy_enabled)
        setResolvedTenant(discovery.tenant)
        // FIX-20260929-043443 #2b: only an explicit echo (re)binds — a bare
        // discovery response (platform host, tenancy probe) must never
        // WIPE an existing explicit binding (it made the binding flicker
        // away whenever the echo was missing). Clearing remains the job of
        // the explicit flows (workspace switch, logout).
        if (discovery.tenant?.slug) {
          setResolvedTenantSlug(discovery.tenant.slug)
        }
        if (discovery.tenant && discovery.tenant.status !== 'active') {
          // Suspended/deleted tenant: no sign-in redirect should occur —
          // the LoginPage renders the blocked state instead.
          setAvailableProviders([])
        }
      } catch {
        // Discovery is best-effort; stay inert on failure.
        setMultiTenancyEnabled(false)
        setResolvedTenant(null)
      }
    }
    void resolveTenant()
  }, [])

  // Multi-tenancy: fetch the caller's memberships when authenticated
  // (powers the multi-org picker).  Inert when unauthenticated/off.
  const refreshAvailableTenants = useCallback(async () => {
    if (!isAuthenticated || isSuperAdmin || !multiTenancyEnabled) {
      setAvailableTenants([])
      return
    }
    try {
      setAvailableTenants(await getMyTenantMemberships())
    } catch {
      setAvailableTenants([])
    }
  }, [isAuthenticated, isSuperAdmin, multiTenancyEnabled])

  useEffect(() => {
    void refreshAvailableTenants()
  }, [refreshAvailableTenants])

  const login = useCallback(async () => {
    // Generate PKCE code verifier and challenge
    const codeVerifier = await generateCodeVerifier()
    const codeChallenge = await generateCodeChallenge(codeVerifier)

    // Store verifier in sessionStorage for callback handler
    sessionStorage.setItem('pkce_code_verifier', codeVerifier)
    // FIX-20260929-043443 #3: persist the resolved start config so the
    // callback exchanges the code against the SAME provider (issuer +
    // client) this authorize redirect was built for.
    sessionStorage.setItem(OIDC_AUTHORITY_KEY, oidcAuthority)
    sessionStorage.setItem(OIDC_CLIENT_ID_KEY, oidcClientId)

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: oidcClientId,
      redirect_uri: OIDC_REDIRECT_URI,
      scope: 'openid profile email',
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    })
    window.location.href = `${oidcAuthority}/protocol/openid-connect/auth?${params}`
  }, [oidcAuthority, oidcClientId])

  // FIX-20261001-235247 (Defect 1): drop the host-derived tenant (store
  // state AND the per-tab sessionStorage binding) so the login page's
  // workspace finder becomes reachable from a host-bound workspace.
  const clearResolvedTenant = useCallback(() => {
    setResolvedTenant(null)
    setResolvedTenantSlug(null)
  }, [])

  const logout = useCallback(() => {
    // Clear local tokens
    const idToken = localStorage.getItem('id_token')
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('id_token')
    localStorage.removeItem('super_admin_token')
    setTokenState(null)
    setAvailableProviders(null)
    setSuperAdminEnabled(false)
    setAvailableTenants([])
    setResolvedTenantSlug(null)
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)

    // For super admin sessions, just redirect to login
    if (isSuperAdmin) {
      window.location.href = '/login'
      return
    }

    // Redirect to Keycloak's logout endpoint to end the SSO session
    const postLogoutRedirectUri = `${window.location.origin}/login`
    const params = new URLSearchParams({
      client_id: oidcClientId,
      post_logout_redirect_uri: postLogoutRedirectUri,
    })

    // Include id_token_hint if available
    if (idToken) {
      params.append('id_token_hint', idToken)
    }

    window.location.href = `${oidcAuthority}/protocol/openid-connect/logout?${params}`
  }, [isSuperAdmin, oidcAuthority, oidcClientId])

  // Silent token refresh: schedule refresh 60s before expiry
  useEffect(() => {
    if (!claims) return
    // Don't auto-refresh super admin tokens
    if (isSuperAdmin) return

    const expiresIn = claims.exp * 1000 - Date.now()
    const refreshIn = expiresIn - 60_000
    if (refreshIn <= 0) {
      logout()
      return
    }
    const timer = setTimeout(async () => {
      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        logout()
        return
      }
      try {
        const response = await fetch(
          `${oidcAuthority}/protocol/openid-connect/token`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
              grant_type: 'refresh_token',
              client_id: oidcClientId,
              refresh_token: refreshToken,
            }),
          },
        )
        if (response.ok) {
          const data = await response.json() as { access_token: string; refresh_token: string }
          localStorage.setItem('refresh_token', data.refresh_token)
          setToken(data.access_token)
        } else {
          logout()
        }
      } catch {
        logout()
      }
    }, refreshIn)

    refreshTimerRef.current = timer
    return () => clearTimeout(timer)
  }, [claims, logout, setToken, isSuperAdmin, oidcAuthority, oidcClientId])

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      isLoading,
      token,
      claims,
      login,
      logout,
      setToken,
      availableProviders,
      superAdminEnabled,
      isSuperAdmin,
      multiTenancyEnabled,
      resolvedTenant,
      availableTenants,
      refreshAvailableTenants,
      activeTenant,
      refreshProviders: discoverProviders,
      // FIX-20261001-235247 (Defect 1): "Use a different workspace" must
      // also unbind a host-derived tenant so the finder can render.
      clearResolvedTenant,
    }),
    [isAuthenticated, isLoading, token, claims, login, logout, setToken, availableProviders, superAdminEnabled, isSuperAdmin, multiTenancyEnabled, resolvedTenant, availableTenants, refreshAvailableTenants, activeTenant, discoverProviders, clearResolvedTenant],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export { AuthContext }
