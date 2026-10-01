/**
 * Platform Admin API — typed client for tenant management, platform
 * settings, cross-tenant security audit, and license assignment.
 * Mirrors the backend routers in app/api/v1/platform/.  All surfaces
 * expose tenant METADATA only — never tenant business data.
 */
import apiClient from './apiClient'
import type { LicenseRead, LicenseTier, TenantUsageRead } from '../types'

// ── Types ──────────────────────────────────────────────────────────────────

export type TenantStatus = 'active' | 'suspended' | 'deleted'
export type TenantRole = 'platform_admin' | 'tenant_admin' | 'member'

export interface Tenant {
  id: string
  name: string
  slug: string
  status: TenantStatus
  is_system_tenant: boolean
  is_onboarded: boolean
  admin_contact_name: string | null
  admin_contact_email: string | null
  created_at: string | null
  updated_at: string | null
  /** Phase 10: active license (null → free-tier defaults) */
  license: LicenseRead | null
  /** Phase 10: tier + effective limits + current usage */
  usage: TenantUsageRead | null
}

export interface TenantDetail extends Tenant {
  user_count: number
  agent_count: number
  role_count: number
}

export interface TenantListResponse {
  items: Tenant[]
  total: number
}

export interface TenantCreate {
  name: string
  slug: string
  admin_contact_name?: string | null
  admin_contact_email?: string | null
  admin_contact_role?: TenantRole
}

export interface TenantUpdate {
  name?: string | null
  admin_contact_name?: string | null
  admin_contact_email?: string | null
}

export interface PlatformSetting {
  key: string
  value: Record<string, unknown> | null
  description: string | null
  category: string
  updated_at: string | null
}

export interface PlatformSettingsListResponse {
  items: PlatformSetting[]
  multi_tenancy_enabled: boolean
}

export interface PlatformSettingUpdateResponse {
  key: string
  value: Record<string, unknown> | null
  multi_tenancy_enabled: boolean
  adoption?: {
    action?: string
    created?: boolean
    slug?: string
    tenant_id?: string
    backfilled_tables?: number
    memberships_granted?: number
    system_tenant_present?: boolean
    tenants_remaining?: number
    data_loss?: boolean
  } | null
}

export type TenantAuditEventType =
  | 'tenant_created'
  | 'tenant_updated'
  | 'tenant_suspended'
  | 'tenant_resumed'
  | 'tenant_deleted'
  | 'cross_tenant_access_denied'
  | 'tenant_boundary_violation'
  | 'platform_setting_updated'

export interface TenantAuditEvent {
  id: string
  tenant_id: string | null
  tenant_slug: string | null
  event_type: TenantAuditEventType
  actor_type: string
  actor_id: string | null
  actor_ip: string | null
  target_resource: string | null
  detail: Record<string, unknown> | null
  is_security_relevant: boolean
  created_at: string | null
}

export interface TenantAuditEventListResponse {
  items: TenantAuditEvent[]
  total: number
}

export interface TenantAuditEventFilters {
  tenant_id?: string
  event_type?: TenantAuditEventType
  security_only?: boolean
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

// ── Tenants ────────────────────────────────────────────────────────────────

export async function listTenants(status?: TenantStatus): Promise<TenantListResponse> {
  const params = status ? { status } : undefined
  const resp = await apiClient.get<TenantListResponse>('/platform/tenants', { params })
  return resp.data
}

export async function getTenant(id: string): Promise<TenantDetail> {
  const resp = await apiClient.get<TenantDetail>(`/platform/tenants/${id}`)
  return resp.data
}

export async function createTenant(body: TenantCreate): Promise<Tenant> {
  const resp = await apiClient.post<Tenant>('/platform/tenants', body)
  return resp.data
}

export async function updateTenant(id: string, body: TenantUpdate): Promise<Tenant> {
  const resp = await apiClient.patch<Tenant>(`/platform/tenants/${id}`, body)
  return resp.data
}

export async function suspendTenant(id: string): Promise<Tenant> {
  const resp = await apiClient.post<Tenant>(`/platform/tenants/${id}/suspend`)
  return resp.data
}

export async function resumeTenant(id: string): Promise<Tenant> {
  const resp = await apiClient.post<Tenant>(`/platform/tenants/${id}/resume`)
  return resp.data
}

export async function deleteTenant(id: string, confirmSlug: string): Promise<void> {
  await apiClient.delete(`/platform/tenants/${id}`, {
    params: { confirm_slug: confirmSlug },
  })
}

// ── Licensing (Phase 10) ───────────────────────────────────────────────────

export interface TenantLicenseWrite {
  tier: LicenseTier
  max_users: number
  max_agent_types: number
  monthly_agent_executions: number
}

/** Assign or change the tenant license (supersedes the previous active). */
export async function assignTenantLicense(
  id: string,
  body: TenantLicenseWrite,
): Promise<LicenseRead> {
  const resp = await apiClient.put<LicenseRead>(`/platform/tenants/${id}/license`, body)
  return resp.data
}

/** Remove the active license — the tenant falls back to the free tier. */
export async function removeTenantLicense(id: string): Promise<void> {
  await apiClient.delete(`/platform/tenants/${id}/license`)
}

// ── Platform settings ──────────────────────────────────────────────────────

export async function getPlatformSettings(): Promise<PlatformSettingsListResponse> {
  const resp = await apiClient.get<PlatformSettingsListResponse>('/platform/settings')
  return resp.data
}

export async function getPlatformSetting(key: string): Promise<PlatformSetting> {
  const resp = await apiClient.get<PlatformSetting>(`/platform/settings/${key}`)
  return resp.data
}

export async function updatePlatformSetting(
  key: string,
  value: unknown,
): Promise<PlatformSettingUpdateResponse> {
  const resp = await apiClient.put<PlatformSettingUpdateResponse>(
    `/platform/settings/${key}`,
    { value },
  )
  return resp.data
}

// ── Platform audit ─────────────────────────────────────────────────────────

export async function listAuditEvents(
  filters: TenantAuditEventFilters = {},
): Promise<TenantAuditEventListResponse> {
  const resp = await apiClient.get<TenantAuditEventListResponse>(
    '/platform/audit-events',
    { params: filters },
  )
  return resp.data
}
