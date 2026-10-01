/**
 * TenantSessionGate — enforces "one session = one tenant" for multi-org
 * users.  Rendered inside the authenticated shell: when the signed-in
 * user holds more than one active tenant membership and this token has
 * not yet been bound to a tenant, the organization picker is shown.
 *
 * - Continue with the current tenant: binds the token's session.
 * - Select another organization: re-runs the OIDC sign-in against that
 *   organization's identity provider (a fresh token with the matching
 *   tenant claim is required — switching is a fresh sign-in by design).
 *
 * Fully inert when multi-tenancy is off, for super admins, and for
 * single-org users.
 */
import { useMemo, useState } from 'react'
import { useAuthStore } from '../../stores/authStore'
import { TenantPicker } from './TenantPicker'
import { setResolvedTenantSlug } from '../../api/tenantAuthApi'

const CONFIRM_KEY = 'parthenon_tenant_confirmed'

function tokenSessionKey(claims: { sub?: string; jti?: string; iat?: number } | null): string {
  if (!claims) return ''
  return claims.jti ?? `${claims.sub ?? ''}:${claims.iat ?? ''}`
}

export function TenantSessionGate() {
  const {
    isAuthenticated,
    isSuperAdmin,
    claims,
    multiTenancyEnabled,
    availableTenants,
    login,
  } = useAuthStore()
  const [dismissError] = useState<string | null>(null)
  // Reactive dismissal: sessionStorage writes are not observable by React,
  // so "Continue" must also flip local state or the picker stays mounted
  // until an unrelated re-render.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)

  const sessionKey = useMemo(() => tokenSessionKey(claims), [claims])

  // Defensive against partial auth-store consumers (tests/mock contexts):
  // every field is treated as optional.
  const showPicker =
    multiTenancyEnabled === true &&
    isAuthenticated === true &&
    isSuperAdmin !== true &&
    (availableTenants?.length ?? 0) > 1 &&
    sessionKey !== '' &&
    dismissedFor !== sessionKey &&
    sessionStorage.getItem(CONFIRM_KEY) !== sessionKey

  const currentTenantSlug =
    availableTenants?.find((m) => m.tenant_slug === claims?.tenant)?.tenant_slug ??
    claims?.tenant ??
    null

  const handleContinue = () => {
    sessionStorage.setItem(CONFIRM_KEY, sessionKey)
    setDismissedFor(sessionKey)
  }

  const handleSelect = (membership: { tenant_slug: string }) => {
    // One session = one tenant: binding to a DIFFERENT organization
    // requires a fresh sign-in against that organization's provider.
    setResolvedTenantSlug(membership.tenant_slug)
    void login()
  }

  if (!showPicker) return null

  return (
    <TenantPicker
      open
      memberships={availableTenants}
      currentTenantSlug={currentTenantSlug}
      onSelect={handleSelect}
      onContinue={handleContinue}
      error={dismissError}
    />
  )
}
