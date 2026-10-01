/**
 * Tenant auth API — public tenant discovery and membership listing for
 * multi-tenant sign-in.  All types mirror backend schemas in
 * app/api/v1/auth_tenant.py.
 */
import apiClient from './apiClient'
import type { TenantDiscovery, TenantMembership } from '../types'

/**
 * Resolve the tenant for the current host (or an explicit slug).
 * Public endpoint — safe to call before authentication.
 * Returns the tenancy switch state with no tenant when multi-tenancy is
 * off, so callers can stay inert.
 */
export async function discoverTenant(slug?: string): Promise<TenantDiscovery> {
  const params = slug ? { slug } : undefined
  const resp = await apiClient.get<TenantDiscovery>('/auth/tenant', { params })
  return resp.data
}

/**
 * List the authenticated caller's active tenant memberships (org picker).
 * Empty when multi-tenancy is off.
 */
export async function getMyTenantMemberships(): Promise<TenantMembership[]> {
  const resp = await apiClient.get<{
    multi_tenancy_enabled: boolean
    items: TenantMembership[]
  }>('/auth/tenant-memberships')
  return resp.data.items
}

/**
 * Storage helpers for the resolved tenant slug (per-tab, sessionStorage —
 * one session = one tenant; never persisted durably).
 */
const TENANT_SLUG_KEY = 'parthenon_tenant_slug'

export function setResolvedTenantSlug(slug: string | null): void {
  if (slug) {
    sessionStorage.setItem(TENANT_SLUG_KEY, slug)
  } else {
    sessionStorage.removeItem(TENANT_SLUG_KEY)
  }
}

export function getResolvedTenantSlug(): string | null {
  return sessionStorage.getItem(TENANT_SLUG_KEY)
}

/**
 * Convenience binding for returning visitors on the workspace-address
 * sign-in flow ("Remember this workspace"): a durable localStorage hint
 * that skips the find-workspace step on the next visit to /login.  Never
 * used for access decisions — the slug is always re-verified through the
 * public discovery endpoint before it is bound to the tab.
 */
const REMEMBERED_TENANT_KEY = 'parthenon_login_tenant'

export function setRememberedTenantSlug(slug: string | null): void {
  if (slug) {
    localStorage.setItem(REMEMBERED_TENANT_KEY, slug)
  } else {
    localStorage.removeItem(REMEMBERED_TENANT_KEY)
  }
}

export function getRememberedTenantSlug(): string | null {
  return localStorage.getItem(REMEMBERED_TENANT_KEY)
}

// ── Self-serve registration & platform-password sign-in (Phase 10) ─────────

export interface RegisterAccountInput {
  email: string
  password: string
  organization_name: string
  slug: string
}

export interface RegisterAccountResult {
  tenant_id: string
  name: string
  slug: string
  your_role: 'platform_admin' | 'tenant_admin' | 'member'
  is_root: boolean
  access_token: string
  token_type: 'bearer'
}

/**
 * PUBLIC account-first registration: creates the platform account, the
 * tenant and the owner's root membership atomically; returns an
 * authenticated session that lands the root user in guided onboarding.
 */
export async function registerAccount(
  input: RegisterAccountInput,
): Promise<RegisterAccountResult> {
  const resp = await apiClient.post<RegisterAccountResult>('/auth/register', input)
  return resp.data
}

export interface LoginPasswordResult {
  access_token: string
  token_type: 'bearer'
  tenant_id: string
  tenant_slug: string
  tenant_name: string
  your_role: 'platform_admin' | 'tenant_admin' | 'member'
}

/**
 * PUBLIC sign-in for platform-issued accounts; issues a tenant-bound
 * token validated by the existing tenant-claim machinery.
 */
export async function loginPassword(
  email: string,
  password: string,
): Promise<LoginPasswordResult> {
  const resp = await apiClient.post<LoginPasswordResult>('/auth/login-password', {
    email,
    password,
  })
  return resp.data
}
