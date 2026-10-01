/**
 * Tenant self-service API — the caller's tenant settings, onboarding,
 * members, invitations, and license & usage.  Mirrors backend/app/api/v1/tenant.py.
 * Requests are tenant-scoped by the X-Tenant header injected by the
 * shared apiClient (resolved tenant slug in sessionStorage).
 */
import apiClient from './apiClient'
import type { TenantUsageRead } from '../types'

export type TenantRole = 'platform_admin' | 'tenant_admin' | 'member'
export type MembershipStatus = 'active' | 'suspended' | 'removed'

export interface TenantSettings {
  tenant_id: string
  slug: string
  name: string
  admin_contact_name: string | null
  admin_contact_email: string | null
  is_onboarded: boolean
  your_role: TenantRole
  /** True when the caller holds the immutable root (owner) membership */
  is_root: boolean
}

export interface TenantSettingsUpdate {
  name?: string | null
  admin_contact_name?: string | null
  admin_contact_email?: string | null
}

export interface OnboardingStatus {
  tenant_id: string
  is_onboarded: boolean
}

export interface TenantMember {
  membership_id: string
  user_id: string
  display_name: string | null
  email: string | null
  tenant_role: TenantRole
  status: MembershipStatus
  is_default: boolean
  /** Root (owner) membership — immutable; UI disables mutating actions */
  is_root: boolean
}

export interface TenantMemberUpdate {
  tenant_role?: TenantRole | null
  status?: MembershipStatus | null
}

export interface TenantInvitation {
  invitation_id: string
  email: string
  tenant_role: TenantRole
  status: 'pending' | 'accepted' | 'expired' | 'revoked'
  expires_at: string | null
  /** Shown ONCE at creation — never returned by listings */
  accept_token: string | null
}

export interface TenantInvitationCreate {
  email: string
  tenant_role: TenantRole
  expires_in_days?: number
}

// ── Settings ────────────────────────────────────────────────────────────────

export async function getTenantSettings(): Promise<TenantSettings> {
  const resp = await apiClient.get<TenantSettings>('/tenant/settings')
  return resp.data
}

export async function updateTenantSettings(
  body: TenantSettingsUpdate,
): Promise<TenantSettings> {
  const resp = await apiClient.patch<TenantSettings>('/tenant/settings', body)
  return resp.data
}

// ── License & usage (Phase 10) ──────────────────────────────────────────────

/**
 * The caller's tenant tier, effective limits and current usage
 * (free-tier defaults when unlicensed).
 */
export async function getTenantUsage(): Promise<TenantUsageRead> {
  const resp = await apiClient.get<TenantUsageRead>('/tenant/usage')
  return resp.data
}

// ── Onboarding ──────────────────────────────────────────────────────────────

export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  const resp = await apiClient.get<OnboardingStatus>('/tenant/onboarding')
  return resp.data
}

export async function completeOnboarding(): Promise<OnboardingStatus> {
  const resp = await apiClient.post<OnboardingStatus>('/tenant/onboarding/complete')
  return resp.data
}

// ── Members ─────────────────────────────────────────────────────────────────

export async function listMembers(): Promise<TenantMember[]> {
  const resp = await apiClient.get<{ items: TenantMember[] }>('/tenant/members')
  return resp.data.items
}

export async function updateMember(
  membershipId: string,
  body: TenantMemberUpdate,
): Promise<TenantMember> {
  const resp = await apiClient.patch<TenantMember>(
    `/tenant/members/${membershipId}`,
    body,
  )
  return resp.data
}

// ── Invitations ─────────────────────────────────────────────────────────────

export async function listInvitations(): Promise<TenantInvitation[]> {
  const resp = await apiClient.get<TenantInvitation[]>('/tenant/invitations')
  return resp.data
}

export async function createInvitation(
  body: TenantInvitationCreate,
): Promise<TenantInvitation> {
  const resp = await apiClient.post<TenantInvitation>('/tenant/invitations', body)
  return resp.data
}

export async function revokeInvitation(invitationId: string): Promise<TenantInvitation> {
  const resp = await apiClient.post<TenantInvitation>(
    `/tenant/invitations/${invitationId}/revoke`,
  )
  return resp.data
}

export async function acceptInvitation(token: string): Promise<TenantSettings> {
  const resp = await apiClient.post<TenantSettings>('/invitations/accept', { token })
  return resp.data
}
