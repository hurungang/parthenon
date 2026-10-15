/**
 * Typed API client functions for System Config endpoints.
 */
import apiClient from './apiClient'

// ── Types ──────────────────────────────────────────────────────────────────

export interface IdentityProviderConfigItem {
  id: string
  provider_scope: string
  provider_type: string
  display_name: string
  issuer_url: string
  client_id: string
  encrypted_client_secret: string | null
  ui_client_id: string | null
  public_client_id: string | null
  scopes: string
  claim_mappings: Record<string, string> | null
  is_enabled: boolean
  default_tenant_role: string | null
  created_at: string
  updated_at: string
}

export interface IdentityProviderConfigListResponse {
  items: IdentityProviderConfigItem[]
  total: number
}

export interface IdentityProviderConfigCreate {
  provider_scope: string
  provider_type: string
  display_name: string
  issuer_url: string
  client_id: string
  client_secret?: string | null
  ui_client_id?: string | null
  public_client_id?: string | null
  scopes?: string
  claim_mappings?: Record<string, string> | null
  is_enabled?: boolean
  default_tenant_role?: string | null
}

export interface IdentityProviderConfigUpdate {
  provider_type?: string | null
  display_name?: string | null
  issuer_url?: string | null
  client_id?: string | null
  client_secret?: string | null
  ui_client_id?: string | null
  public_client_id?: string | null
  scopes?: string | null
  claim_mappings?: Record<string, string> | null
  is_enabled?: boolean | null
  default_tenant_role?: string | null
}

export interface OIDCTestStep {
  step: string
  status: string
  detail: string
}

export interface OIDCTestClientIdStatus {
  client_id: string | null
  status: 'missing' | 'invalid' | 'ok' | 'warning'
  detail: string
}

export interface OIDCTestResponse {
  success: boolean
  steps: OIDCTestStep[]
  discovery_doc: Record<string, unknown> | null
  client_id_status?: OIDCTestClientIdStatus | null
}

export interface OIDCTestRequest {
  issuer_url: string
  client_id?: string | null
  client_secret?: string | null
  redirect_uri?: string | null
}

export interface SuperAdminStatusResponse {
  is_enabled: boolean
  username: string | null
  last_login_at: string | null
  env_controlled: boolean
}

export interface SuperAdminLoginResponse {
  access_token: string
  token_type: string
  username: string
  is_super_admin: boolean
}

// ── API Functions ──────────────────────────────────────────────────────────

// FIX-20261001-010107: identity-provider WRITES are slot-addressed.
// With a workspace session bound to this tab (apiClient attaches
// X-Tenant), /system/* addresses the tenant's own slot.  Without a
// binding (platform context) /system/* writes are fail-closed 403 at the
// tenant-resolution middleware — the shared (NULL-tenant) config is
// managed via the platform surface /platform/identity-providers instead.
// Declared locally (NOT imported) because apiClient mirrors this key and
// importing it would be circular.
const TENANT_SLUG_KEY = 'parthenon_tenant_slug'

function identityProvidersWriteBase(): string {
  const tenantSlug = sessionStorage.getItem(TENANT_SLUG_KEY)
  return tenantSlug ? '/system/identity-providers' : '/platform/identity-providers'
}

/**
 * List all configured identity providers.
 * Public endpoint — accessible before auth. Returns the SHARED configs
 * only without a tenant context, shared + own-tenant with a workspace
 * session (never other tenants').
 */
export async function getIdentityProviders(): Promise<IdentityProviderConfigListResponse> {
  const { data } = await apiClient.get<IdentityProviderConfigListResponse>(
    '/system/identity-providers',
  )
  return data
}

/**
 * Get a single provider config by scope.
 */
export async function getIdentityProvider(scope: string): Promise<IdentityProviderConfigItem> {
  const { data } = await apiClient.get<IdentityProviderConfigItem>(
    `${identityProvidersWriteBase()}/${scope}`,
  )
  return data
}

/**
 * Create a new identity provider config.
 */
export async function createIdentityProvider(
  body: IdentityProviderConfigCreate,
): Promise<IdentityProviderConfigItem> {
  const { data } = await apiClient.post<IdentityProviderConfigItem>(
    identityProvidersWriteBase(),
    body,
  )
  return data
}

/**
 * Update an existing identity provider config.
 */
export async function updateIdentityProvider(
  scope: string,
  body: IdentityProviderConfigUpdate,
): Promise<IdentityProviderConfigItem> {
  const { data } = await apiClient.put<IdentityProviderConfigItem>(
    `${identityProvidersWriteBase()}/${scope}`,
    body,
  )
  return data
}

/**
 * Delete an identity provider config.
 */
export async function deleteIdentityProvider(scope: string): Promise<void> {
  await apiClient.delete(`${identityProvidersWriteBase()}/${scope}`)
}

/**
 * Toggle a provider's enabled state.
 */
export async function toggleIdentityProvider(
  scope: string,
  isEnabled: boolean,
): Promise<IdentityProviderConfigItem> {
  const { data } = await apiClient.patch<IdentityProviderConfigItem>(
    `${identityProvidersWriteBase()}/${scope}/toggle`,
    { is_enabled: isEnabled },
  )
  return data
}

/**
 * Test OIDC connectivity (not persisted).
 */
export async function testOidcConnection(
  body: OIDCTestRequest,
): Promise<OIDCTestResponse> {
  const { data } = await apiClient.post<OIDCTestResponse>(
    '/system/identity-providers/test',
    body,
  )
  return data
}

/**
 * Initiate a test OIDC login flow.
 */
export async function initiateTestLogin(
  body: OIDCTestRequest,
): Promise<{ test_id: string; redirect_url: string; status: string }> {
  const { data } = await apiClient.post<{
    test_id: string
    redirect_url: string
    status: string
  }>('/system/identity-providers/test-login', body)
  return data
}

/**
 * Poll test-login session status.
 */
export async function getTestLoginStatus(
  testId: string,
): Promise<Record<string, unknown>> {
  const { data } = await apiClient.get<Record<string, unknown>>(
    `/system/identity-providers/test-login/status/${testId}`,
  )
  return data
}

/**
 * Get super admin status.
 * Public endpoint — accessible before auth.
 */
export async function getSuperAdminStatus(): Promise<SuperAdminStatusResponse> {
  const { data } = await apiClient.get<SuperAdminStatusResponse>(
    '/system/super-admin/status',
  )
  return data
}

/**
 * Toggle super admin enabled state.
 */
export async function toggleSuperAdmin(isEnabled: boolean): Promise<SuperAdminStatusResponse> {
  const { data } = await apiClient.patch<SuperAdminStatusResponse>(
    '/system/super-admin/toggle',
    { is_enabled: isEnabled },
  )
  return data
}

/**
 * Update super admin password.
 */
export async function updateSuperAdminPassword(
  currentPassword: string,
  newPassword: string,
): Promise<SuperAdminStatusResponse> {
  const { data } = await apiClient.put<SuperAdminStatusResponse>(
    '/system/super-admin/password',
    { current_password: currentPassword, new_password: newPassword },
  )
  return data
}

/**
 * Super admin credential login.
 * Public endpoint — no prior auth required.
 */
export async function superAdminLogin(
  username: string,
  password: string,
): Promise<SuperAdminLoginResponse> {
  const { data } = await apiClient.post<SuperAdminLoginResponse>(
    '/auth/super-admin/login',
    { username, password },
  )
  return data
}
