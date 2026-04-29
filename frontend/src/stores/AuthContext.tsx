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

// ── Context definition ─────────────────────────────────────────────────────────

interface AuthContextValue extends AuthState {
  login: () => void
  logout: () => void
  setToken: (token: string) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ───────────────────────────────────────────────────────────────────

const OIDC_AUTHORITY = import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8082/realms/parthenon'
const OIDC_CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'parthenon-api-ui'
const OIDC_REDIRECT_URI = `${window.location.origin}/callback`

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(
    () => localStorage.getItem('access_token'),
  )
  const [isLoading] = useState(false)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const claims = useMemo<AuthClaims | null>(() => {
    if (!token) return null
    return parseJwt(token)
  }, [token])

  const isAuthenticated = !!token && !!claims && !isTokenExpired(claims)

  const setToken = useCallback((newToken: string) => {
    localStorage.setItem('access_token', newToken)
    setTokenState(newToken)
  }, [])

  const login = useCallback(async () => {
    // Generate PKCE code verifier and challenge
    const codeVerifier = await generateCodeVerifier()
    const codeChallenge = await generateCodeChallenge(codeVerifier)
    
    // Store verifier in sessionStorage for callback handler
    sessionStorage.setItem('pkce_code_verifier', codeVerifier)
    
    const params = new URLSearchParams({
      response_type: 'code',
      client_id: OIDC_CLIENT_ID,
      redirect_uri: OIDC_REDIRECT_URI,
      scope: 'openid profile email',
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    })
    window.location.href = `${OIDC_AUTHORITY}/protocol/openid-connect/auth?${params}`
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setTokenState(null)
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    window.location.href = '/login'
  }, [])

  // Silent token refresh: schedule refresh 60s before expiry
  useEffect(() => {
    if (!claims) return
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
          `${OIDC_AUTHORITY}/protocol/openid-connect/token`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({
              grant_type: 'refresh_token',
              client_id: OIDC_CLIENT_ID,
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
  }, [claims, logout, setToken])

  const value = useMemo<AuthContextValue>(
    () => ({ isAuthenticated, isLoading, token, claims, login, logout, setToken }),
    [isAuthenticated, isLoading, token, claims, login, logout, setToken],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export { AuthContext }
