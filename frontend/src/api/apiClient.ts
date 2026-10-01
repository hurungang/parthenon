import axios, { AxiosError, AxiosHeaders, type AxiosInstance } from 'axios'
import { API_CONFIG } from './API_CONFIG'
import { parsePermissionError, dispatchPermissionDeniedEvent } from '../utils/permissionError'

/**
 * Configured axios instance with auth header injection and error interceptors.
 * All frontend API calls should use this client.
 */
const apiClient: AxiosInstance = axios.create({
  baseURL: API_CONFIG.BASE_URL,
  timeout: API_CONFIG.TIMEOUT_MS,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── Storage keys (FIX-20260929-121120) ────────────────────────────────────────
// Mirror of tenantAuthApi's keys. Declared locally (NOT imported) because
// tenantAuthApi imports THIS module — an import here would be circular.
const TENANT_SLUG_KEY = 'parthenon_tenant_slug'
const REMEMBERED_TENANT_KEY = 'parthenon_login_tenant'

/**
 * The exact fail-closed wire shape of TenantResolutionMiddleware
 * (backend/app/middleware/tenant_resolution.py): `403 {"detail": "Tenant
 * could not be resolved"}` — both its rejection branches return this
 * payload, and it carries NO `required_permission`, which distinguishes it
 * from permission 403s. Only recognized when the rejected request actually
 * addressed a tenant (carried the `X-Tenant` header) — narrowly scoped to
 * the resolution rejection of a tenant-scoped API call.
 */
function isTenantResolutionRejection(error: AxiosError): boolean {
  if (error.response?.status !== 403) return false
  const data: unknown = error.response.data
  if (!data || typeof data !== 'object') return false
  const body = data as { detail?: unknown; required_permission?: unknown }
  // A permission 403 (required_permission body) is NEVER a resolution rejection.
  if (body.required_permission !== undefined) return false
  if (body.detail !== 'Tenant could not be resolved') return false
  const headers = error.config?.headers
  if (!headers) return false
  const tenantHeader = AxiosHeaders.from(headers).get('X-Tenant')
  return typeof tenantHeader === 'string' && tenantHeader.trim() !== ''
}

/**
 * Self-heal an invalid tenant binding (FIX-20260929-121120 / B2): the
 * backend rejected the bound slug fail-closed, so the binding is provably
 * stale/unknown — clear it (and the remembered-workspace hint that may
 * have led there) and return the user to the login page, where the
 * find-workspace step renders once no binding remains. Never a /login
 * bounce loop: when already on /login (or mid-OIDC-callback) only the
 * storage is cleared, no navigation happens.
 */
function selfHealTenantBinding(): void {
  sessionStorage.removeItem(TENANT_SLUG_KEY)
  localStorage.removeItem(REMEMBERED_TENANT_KEY)
  if (
    !window.location.pathname.includes('/login') &&
    !window.location.pathname.includes('/callback')
  ) {
    window.location.href = '/login'
  }
}

// Request interceptor: inject Authorization header from stored token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // Multi-tenancy: attach the resolved tenant slug (per-tab session) so
    // API clients address their tenant without subdomain routing.  Absent
    // in single-tenant mode — header added only when a tenant is resolved.
    const tenantSlug = sessionStorage.getItem(TENANT_SLUG_KEY)
    if (tenantSlug) {
      config.headers['X-Tenant'] = tenantSlug
    }
    return config
  },
  (error: AxiosError) => Promise.reject(error),
)

// Response interceptor: handle 401 by redirecting to login; 403 with
// structured permission data dispatches a targeted error event; a
// fail-closed tenant-resolution rejection self-heals the invalid binding.
// Super admin sessions are preserved — 401s during super admin sessions
// only clear the access_token and let the caller handle the error,
// preventing the session from being destroyed by a single failed request.
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      const isSuperAdminSession = !!localStorage.getItem('super_admin_token')
      if (isSuperAdminSession) {
        // Don't redirect super admin — let error propagate to caller
        return Promise.reject(error)
      }
      // Clear stored tokens for regular OIDC users
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      // Redirect to login
      if (!window.location.pathname.includes('/login') && !window.location.pathname.includes('/callback')) {
        window.location.href = '/login'
      }
    } else if (error.response?.status === 403) {
      if (isTenantResolutionRejection(error)) {
        // Unknown-slug rejection — clear the invalid binding and land the
        // user on find-workspace (never a /login redirect loop).
        selfHealTenantBinding()
      } else {
        const permDetail = parsePermissionError(error)
        if (permDetail) {
          dispatchPermissionDeniedEvent(permDetail)
        }
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
