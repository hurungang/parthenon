import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { AuthClaims, AuthState } from '../types'

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
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ───────────────────────────────────────────────────────────────────

const OIDC_AUTHORITY_FALLBACK = import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8082/realms/parthenon'
const OIDC_CLIENT_ID_FALLBACK = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'parthenon-api-ui'
const OIDC_REDIRECT_URI = `${window.location.origin}/callback`

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(
    () => localStorage.getItem('access_token'),
  )
  const [isLoading] = useState(false)
  const [availableProviders, setAvailableProviders] = useState<AvailableProvider[] | null>(null)
  const [superAdminEnabled, setSuperAdminEnabled] = useState(false)
  const [oidcAuthority, setOidcAuthority] = useState<string>(OIDC_AUTHORITY_FALLBACK)
  const [oidcClientId, setOidcClientId] = useState<string>(OIDC_CLIENT_ID_FALLBACK)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const claims = useMemo<AuthClaims | null>(() => {
    if (!token) return null
    return parseJwt(token)
  }, [token])

  const isSuperAdmin = useMemo(() => {
    return !!claims && !!(claims as unknown as Record<string, unknown>).is_super_admin
  }, [claims])

  const isAuthenticated = !!token && !!claims && !isTokenExpired(claims)

  const setToken = useCallback((newToken: string) => {
    localStorage.setItem('access_token', newToken)
    setTokenState(newToken)
  }, [])

  // Discover active providers and super admin status on app load
  useEffect(() => {
    const discoverProviders = async () => {
      try {
        const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1'
        const headers: Record<string, string> = {}
        const storedToken = localStorage.getItem('access_token')
        if (storedToken) {
          headers.Authorization = `Bearer ${storedToken}`
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
    }

    void discoverProviders()
  }, [token])

  const login = useCallback(async () => {
    // Generate PKCE code verifier and challenge
    const codeVerifier = await generateCodeVerifier()
    const codeChallenge = await generateCodeChallenge(codeVerifier)

    // Store verifier in sessionStorage for callback handler
    sessionStorage.setItem('pkce_code_verifier', codeVerifier)

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
    }),
    [isAuthenticated, isLoading, token, claims, login, logout, setToken, availableProviders, superAdminEnabled, isSuperAdmin],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export { AuthContext }
