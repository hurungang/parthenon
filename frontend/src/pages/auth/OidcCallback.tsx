import { useEffect, useRef } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { CircularProgress, Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import {
  discoverTenant,
  getRememberedTenantSlug,
  setResolvedTenantSlug,
} from '../../api/tenantAuthApi'

const OIDC_AUTHORITY_FALLBACK = import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8082/realms/parthenon'
const OIDC_CLIENT_ID_FALLBACK = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'parthenon-api-ui'

// sessionStorage keys written by AuthContext.login() at the authorize
// redirect (fix #3 of FIX-20260929-043443): the callback must exchange the
// code against the SAME authority/client the login start used — a
// tenant-scoped provider with a non-default issuer fails the exchange at
// the platform default. Consumed + cleared here; the fallbacks keep legacy
// flows (no login()-started state) working.
const OIDC_AUTHORITY_KEY = 'oidc_authority'
const OIDC_CLIENT_ID_KEY = 'oidc_client_id'

// Best-effort in-memory memo of the workspace the sign-in was started from
// (fix #2 of FIX-20260929-043443). It is the LAST link of the restoration
// chain (token claim → sessionStorage → remembered workspace → this memo)
// and only helps within a single SPA load — the authoritative restore
// sources are the token's tenant claim and the storage keys.
let lastBoundTenantSlug: string | null = null

/**
 * Decode a JWT payload (id_token / access_token) without verification —
 * read-only claim inspection for the tenant binding; the backend remains
 * the sole authority on claim validity.
 */
function parseJwtPayload(token: string | null | undefined): Record<string, unknown> | null {
  if (!token) return null
  try {
    const base64Url = token.split('.')[1]
    if (!base64Url) return null
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64)) as Record<string, unknown>
  } catch {
    return null
  }
}

function tenantClaimFrom(data: { access_token: string; id_token?: string }): string | null {
  for (const token of [data.access_token, data.id_token]) {
    const claims = parseJwtPayload(token)
    const slug = (claims as Record<string, unknown> | null)?.tenant
    if (typeof slug === 'string' && slug.trim() !== '') return slug
  }
  return null
}

/**
 * Resolve the workspace the sign-in was started from (fix #2 of
 * FIX-20260929-043443). First non-empty source wins:
 * 1. the token's ``tenant`` claim — authoritative when present (the claim
 *    wins over storage when they conflict),
 * 2. the pre-redirect binding (sessionStorage),
 * 3. the remembered workspace (localStorage),
 * 4. the in-session memo (best-effort, same SPA load only).
 *
 * FIX-20260929-121120: the result is a CANDIDATE only — it is verified
 * through public discovery (verifyIntendedTenantSlug) before anything is
 * bound to the session.
 */
function resolveIntendedTenantSlug(data: { access_token: string; id_token?: string }): string | null {
  const candidates: Array<string | null | undefined> = [
    tenantClaimFrom(data),
    sessionStorage.getItem('parthenon_tenant_slug'),
    getRememberedTenantSlug(),
    lastBoundTenantSlug,
  ]
  for (const candidate of candidates) {
    if (typeof candidate === 'string' && candidate.trim() !== '') return candidate
  }
  return null
}

/**
 * Verify a candidate workspace slug through public discovery BEFORE it may
 * be bound (FIX-20260929-121120). `resolveIntendedTenantSlug` sources are
 * only CANDIDATES — a stale/never-verified slug (`org-a`) in any of them
 * must never reach the session binding, or every dashboard call carries it
 * as `X-Tenant` and is rejected fail-closed.
 *
 * - Discovery confirms the tenant (`tenant` non-null) → bindable.
 * - Discovery definitively answers `tenant: null` (unknown/deleted —
 *   uniform response, no enumeration) → NOT bindable: bind nothing and let
 *   the user land unbound; the login page's find-workspace step re-resolves.
 * - Discovery UNAVAILABLE (network error, or a response object that could
 *   not be read at all) → fail-open: bind the candidate — the sign-in was
 *   started from that workspace, and an unreachable discovery must not
 *   strand an otherwise valid sign-in. apiClient's fail-closed self-heal
 *   recovers later if the slug is in fact stale. Fail-open ONLY on
 *   unavailability — never on a definitive null answer.
 */
async function verifyIntendedTenantSlug(slug: string): Promise<boolean> {
  try {
    const discovery: unknown = await discoverTenant(slug)
    if (discovery === null || typeof discovery !== 'object') {
      console.warn(
        `OidcCallback: tenant discovery returned no usable response; binding candidate '${slug}' fail-open (discovery unavailable)`,
      )
      return true
    }
    return Boolean((discovery as { tenant?: unknown }).tenant)
  } catch (error) {
    console.warn(
      `OidcCallback: tenant discovery unavailable; binding candidate '${slug}' fail-open`,
      error,
    )
    return true
  }
}

/**
 * OIDC callback handler — exchanges authorization code for tokens.
 */
export function OidcCallback() {
  const { t } = useTranslation()
  const { setToken } = useAuthStore()
  const navigate = useNavigate()
  const exchanged = useRef(false)

  useEffect(() => {
    if (exchanged.current) return
    exchanged.current = true

    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')

    if (!code) {
      navigate('/login', { replace: true })
      return
    }

    // Retrieve PKCE code verifier from sessionStorage
    const codeVerifier = sessionStorage.getItem('pkce_code_verifier')
    if (!codeVerifier) {
      console.error('PKCE code verifier not found in session storage')
      navigate('/login', { replace: true })
      return
    }

    // FIX-20260929-043443 #3: exchange against the SAME authority (and
    // client) the login() start used — persisted at the authorize redirect.
    // Falls back to the platform default for legacy flows.
    const authority = (
      sessionStorage.getItem(OIDC_AUTHORITY_KEY) ?? OIDC_AUTHORITY_FALLBACK
    ).replace(/\/+$/, '')
    const clientId = sessionStorage.getItem(OIDC_CLIENT_ID_KEY) ?? OIDC_CLIENT_ID_FALLBACK
    sessionStorage.removeItem(OIDC_AUTHORITY_KEY)
    sessionStorage.removeItem(OIDC_CLIENT_ID_KEY)

    const redirectUri = `${window.location.origin}/callback`

    fetch(`${authority}/protocol/openid-connect/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: clientId,
        code,
        redirect_uri: redirectUri,
        code_verifier: codeVerifier,
      }),
    })
      .then((res) => {
        if (!res.ok) {
          return res.text().then(text => {
            console.error('Token exchange failed:', res.status, text)
            throw new Error('Token exchange failed')
          })
        }
        return res.json() as Promise<{ access_token: string; refresh_token: string; id_token?: string }>
      })
      .then(async (data) => {
        // Clear the PKCE verifier after successful exchange
        sessionStorage.removeItem('pkce_code_verifier')

        // FIX-20260929-043443 #2: re-bind the workspace tenant on sign-in
        // completion (parity with password login / sign-up, which call
        // setResolvedTenantSlug). Claim wins over storage when they
        // conflict — see resolveIntendedTenantSlug for the source order.
        // FIX-20260929-121120: the resolved source is only a CANDIDATE —
        // it is verified through public discovery before anything is
        // bound. On a definitive "unknown" answer nothing is bound and the
        // user lands unbound to re-resolve (fail-closed, never bind an
        // unverified slug); fail-open applies only when discovery itself
        // is unavailable (see verifyIntendedTenantSlug).
        const slug = resolveIntendedTenantSlug(data)
        const verified = slug !== null && (await verifyIntendedTenantSlug(slug))
        if (slug !== null && verified) {
          lastBoundTenantSlug = slug
          // Bind the per-tab session for the dashboard's X-Tenant header.
          sessionStorage.setItem('parthenon_tenant_slug', slug)
          setResolvedTenantSlug(slug)
        }

        // flushSync forces AuthContext state to update synchronously before
        // navigate() renders ProtectedRoute, preventing an isAuthenticated=false flash.
        flushSync(() => {
          setToken(data.access_token)
        })
        localStorage.setItem('refresh_token', data.refresh_token)
        // Store id_token for proper Keycloak logout
        if (data.id_token) {
          localStorage.setItem('id_token', data.id_token)
        }
        navigate('/dashboard', { replace: true })
      })
      .catch(() => navigate('/login', { replace: true }))
  }, [navigate, setToken])

  return (
    <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" height="100vh">
      <CircularProgress size={48} />
      <Typography variant="body1" mt={2}>
        {t('app.loading')}
      </Typography>
    </Box>
  )
}
