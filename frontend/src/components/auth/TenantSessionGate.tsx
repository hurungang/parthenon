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
 * The authoritative "is this session tenant-bound" signal is the bound
 * workspace slug (the per-tab sessionStorage binding the user chose before
 * the sign-in and OidcCallback re-binds) matching one of the active
 * memberships fetched for the current token.  The token's ``tenant`` claim
 * (injected by the backend per-request, never present in the raw
 * Keycloak JWT) is kept as an additional OR signal.
 *
 * Fully inert when multi-tenancy is off, for super admins, and for
 * single-org users.
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import { TenantPicker } from './TenantPicker'
import { getResolvedTenantSlug, setResolvedTenantSlug } from '../../api/tenantAuthApi'

const CONFIRM_KEY = 'parthenon_tenant_confirmed'

function tokenSessionKey(claims: { sub?: string; jti?: string; iat?: number } | null): string {
  if (!claims) return ''
  return claims.jti ?? `${claims.sub ?? ''}:${claims.iat ?? ''}`
}

export function TenantSessionGate() {
  const { t } = useTranslation()
  const {
    isAuthenticated,
    isSuperAdmin,
    claims,
    multiTenancyEnabled,
    availableTenants,
    login,
    refreshProviders,
  } = useAuthStore()
  const [dismissError, setDismissError] = useState<string | null>(null)
  const [dismissedFor, setDismissedFor] = useState<string | null>(null)

  const sessionKey = useMemo(() => tokenSessionKey(claims), [claims])

  // Reactive mirror of the per-tab workspace binding (sessionStorage is
  // not observable): re-read whenever the token session or the membership
  // list changes so a stale binding from a previous login is not kept.
  const [boundSlug, setBoundSlug] = useState<string | null>(() => getResolvedTenantSlug())
  useEffect(() => {
    setBoundSlug(getResolvedTenantSlug())
  }, [sessionKey, availableTenants])

  // One session = one workspace: the session is tenant-bound when EITHER
  // the bound workspace slug (sessionStorage binding, re-established by
  // OidcCallback for the current token) OR the token's tenant claim
  // matches an active membership.  The bound slug is the authoritative
  // signal — the claim is never present in the raw Keycloak JWT.
  const memberships = availableTenants ?? []
  const boundIsMembership =
    boundSlug !== null && memberships.some((m) => m.tenant_slug === boundSlug)
  const claimsTenantSlug =
    typeof claims?.tenant === 'string' && claims.tenant !== '' ? claims.tenant : null
  const claimsTenantIsMembership =
    claimsTenantSlug !== null &&
    memberships.some((m) => m.tenant_slug === claimsTenantSlug)
  const sessionIsBound = boundIsMembership || claimsTenantIsMembership

  // Guard: a binding that does not belong to the CURRENT token's
  // memberships is stale (e.g. the user signed into a workspace they are
  // not a member of).  Clear it so the picker can decide fresh — that is
  // the legitimate case for showing it.
  useEffect(() => {
    if (boundSlug !== null && !boundIsMembership && memberships.length > 0) {
      setResolvedTenantSlug(null)
      setBoundSlug(null)
    }
  }, [boundSlug, boundIsMembership, memberships])

  useEffect(() => {
    if (sessionIsBound && sessionKey !== '') {
      sessionStorage.setItem(CONFIRM_KEY, sessionKey)
      setDismissedFor(sessionKey)
    }
  }, [sessionIsBound, sessionKey])

  // Defensive against partial auth-store consumers (tests/mock contexts):
  // every field is treated as optional.
  const showPicker =
    multiTenancyEnabled === true &&
    isAuthenticated === true &&
    isSuperAdmin !== true &&
    (availableTenants?.length ?? 0) > 1 &&
    sessionKey !== '' &&
    dismissedFor !== sessionKey &&
    sessionStorage.getItem(CONFIRM_KEY) !== sessionKey &&
    !sessionIsBound

  const currentTenantSlug =
    memberships.find((m) => m.tenant_slug === (boundSlug ?? claimsTenantSlug))
      ?.tenant_slug ??
    boundSlug ??
    claimsTenantSlug ??
    null

  const handleContinue = () => {
    sessionStorage.setItem(CONFIRM_KEY, sessionKey)
    setDismissedFor(sessionKey)
  }

  const handleSelect = async (membership: { tenant_slug: string }) => {
    // One session = one tenant: binding to a DIFFERENT organization
    // requires a fresh sign-in against that organization's provider.
    setResolvedTenantSlug(membership.tenant_slug)
    // Refresh provider discovery for the newly bound slug BEFORE the
    // redirect — login() must target the selected tenant's own issuer,
    // not the authority resolved for the previous (or root) context.
    try {
      await refreshProviders?.()
    } catch {
      // Best-effort; login() re-checks the authority defensively.
    }
    const started = await login()
    if (started === false) {
      setDismissError(t('auth.tenantPicker.switchFailed'))
    }
  }

  if (!showPicker) return null

  return (
    <TenantPicker
      open
      memberships={availableTenants}
      currentTenantSlug={currentTenantSlug}
      onSelect={(membership) => { void handleSelect(membership) }}
      onContinue={handleContinue}
      error={dismissError}
    />
  )
}
