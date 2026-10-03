import { useState, useEffect, useRef } from 'react'
import {
  Button,
  Checkbox,
  Container,
  FormControlLabel,
  Link,
  TextField,
  Typography,
  Paper,
  Box,
  Divider,
  Alert,
  CircularProgress,
} from '@mui/material'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getIdentityProviders, getSuperAdminStatus, superAdminLogin } from '../../api/systemConfigApi'
import {
  discoverTenant,
  getRememberedTenantSlug,
  loginPassword,
  setRememberedTenantSlug,
  setResolvedTenantSlug,
} from '../../api/tenantAuthApi'
import type { PublicTenantInfo } from '../../types'
import { useAuthStore } from '../../stores/authStore'

/**
 * Derive a workspace slug candidate from raw user input.
 *
 * Accepts a bare slug (`acme`, `test-com`) and tolerates a pasted host or
 * URL (`acme.example.com`, `https://acme.example.com/login`) by taking the
 * first DNS label — the tenant slug IS the first label of a workspace
 * address.  Workspace slugs are stored lowercase.
 */
export function extractSlugCandidate(input: string): string {
  let value = input.trim().toLowerCase()
  if (value === '') return ''
  // Tolerate a pasted full address: scheme, path, query and port.
  value = value.replace(/^https?:\/\//, '')
  value = value.split('/')[0] ?? value
  value = value.split('?')[0] ?? value
  value = value.split(':')[0] ?? value
  if (value.includes('.')) {
    value = value.split('.')[0] ?? value
  }
  return value
}

/**
 * Which stage of the workspace-address sign-in flow the page is in.
 * Only meaningful when the tenancy switch is ON and no tenant was derived
 * from the host — every other situation stays `idle` (legacy behaviour).
 */
type WorkspacePhase =
  | 'idle'      // tenancy off / unknown, or a host-derived tenant — legacy page
  | 'resolving' // tenancy on, no host tenant: checking ?workspace= / remembered workspace
  | 'find'      // nothing bound yet — show the "find your workspace" card
  | 'card'      // workspace resolved via its address — tenant-branded sign-in card

/**
 * Tenancy-aware sign-in page.
 *
 * - Multi-tenancy ON: primary email + password card (`loginPassword` — the
 *   self-registered platform account flow), the OIDC button when a
 *   user-scope provider is configured (never a gate), the "create your
 *   organization" link and a discreet platform-admin entry.
 * - No tenant in context (no host-derived tenant, nothing bound): a
 *   workspace-address step FIRST (AWS-style) — the visitor enters their
 *   workspace address/slug, the public discovery endpoint resolves it and
 *   the page re-renders as that tenant's branded, tenant-scoped sign-in
 *   card.  `?workspace=<slug>` deep-links straight to a card; a
 *   remembered workspace (`parthenon_login_tenant`) skips the finder.
 * - Multi-tenancy OFF (default): unchanged single-tenant behaviour —
 *   OIDC button plus the discreet platform-admin entry (no setup wizard:
 *   OIDC is configured in System Config after signing in).
 * - Tenant-scoped guards preserved: suspended/deleted tenants show no
 *   sign-in flows at all; a HOST-derived tenant without sign-in
 *   configured shows a contact-administrator notice.  A tenant reached by
 *   its address always shows the password form — a fresh tenant has no
 *   OIDC yet, and its owner signs in with the account they created at
 *   registration (`sign_in_ready` only reflects OIDC configuration).
 */
export function LoginPage() {
  const { t } = useTranslation()
  const {
    login,
    isAuthenticated,
    setToken,
    multiTenancyEnabled,
    resolvedTenant,
    refreshProviders,
    clearResolvedTenant,
  } = useAuthStore()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Platform admin (super admin) form state
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)
  const [showSuperAdminForm, setShowSuperAdminForm] = useState(false)

  // Platform password sign-in (self-registered accounts) form state
  const [email, setEmail] = useState('')
  const [signInPassword, setSignInPassword] = useState('')
  const [signInError, setSignInError] = useState<string | null>(null)
  const [signingIn, setSigningIn] = useState(false)

  // Workspace-address sign-in state (multi-tenancy on only)
  const [phase, setPhase] = useState<WorkspacePhase>('idle')
  const [addressTenant, setAddressTenant] = useState<PublicTenantInfo | null>(null)
  const [workspaceInput, setWorkspaceInput] = useState('')
  const [rememberWorkspace, setRememberWorkspace] = useState(true)
  const [findError, setFindError] = useState<string | null>(null)
  const [lookingUp, setLookingUp] = useState(false)

  // Multi-tenancy: the tenant in branding/guard context — either derived
  // from the host by AuthProvider or resolved here by its address.
  const addressFlowActive = multiTenancyEnabled === true && resolvedTenant === null
  // While the tenancy flag is in flight the phase stays `idle`; the moment
  // the address flow activates it is treated as resolving until the
  // auto-resolve effect lands on the finder or a workspace card — so the
  // legacy (platform) sign-in flows never flash in between.
  const effectivePhase: WorkspacePhase = addressFlowActive
    ? (phase === 'idle' ? 'resolving' : phase)
    : 'idle'
  const brandedTenant =
    resolvedTenant ?? (effectivePhase === 'card' ? addressTenant : null)

  // Tenant-scoped guards (suspended/deleted tenants show no sign-in flows)
  const tenantBlocked = multiTenancyEnabled && brandedTenant !== null && brandedTenant.status !== 'active'
  // Sign-in readiness gate for HOST-derived tenants only (unchanged legacy
  // behaviour) — see the component doc comment for the address-flow choice.
  const tenantSignInUnavailable =
    multiTenancyEnabled &&
    resolvedTenant !== null &&
    resolvedTenant.status === 'active' &&
    !resolvedTenant.sign_in_ready

  // Discover active providers and super admin status on load.  Keyed by
  // the bound workspace so the list re-resolves for the tenant context
  // right after the address flow binds a slug (apiClient attaches
  // X-Tenant from sessionStorage at request time).
  const contextSlug =
    resolvedTenant?.slug ?? (effectivePhase === 'card' ? addressTenant?.slug ?? null : null)
  // Phase 11 (task 11.6): the super-admin break-glass entry is available
  // ONLY at the root workspace — the entered/resolved workspace slug is
  // `root`, or no workspace is bound at all (the tenancy-off deployment
  // IS the root workspace; legacy host-flow rendering keeps the entry so
  // first-run bootstrap keeps working).
  const isRootWorkspace =
    !multiTenancyEnabled || contextSlug === null || contextSlug === 'root'
  const { data: providersData, isLoading: providersLoading } = useQuery({
    queryKey: ['system', 'identity-providers', contextSlug],
    queryFn: async () => {
      try {
        return await getIdentityProviders()
      } catch {
        return { items: [], total: 0 }
      }
    },
  })

  const { data: superAdminStatus, isLoading: superAdminLoading } = useQuery({
    queryKey: ['system', 'super-admin-status'],
    queryFn: async () => {
      try {
        return await getSuperAdminStatus()
      } catch {
        return null
      }
    },
  })

  const isLoading = providersLoading || superAdminLoading

  useEffect(() => {
    if (isAuthenticated) navigate('/dashboard', { replace: true })
  }, [isAuthenticated, navigate])

  // ── Workspace-address flow: bind a resolved workspace to this tab ──────
  function bindWorkspace(tenant: PublicTenantInfo) {
    setAddressTenant(tenant)
    // Per-tab session binding — apiClient attaches X-Tenant on every
    // subsequent call (provider listing, password sign-in, ...).
    setResolvedTenantSlug(tenant.slug)
  }

  // Auto-resolve on entry (tenancy on, no host-derived tenant):
  // `?workspace=<slug>` wins, then the remembered workspace; anything else
  // lands on the find-workspace step.  The slug is ALWAYS re-verified
  // through public discovery before it is bound — a stale remembered slug
  // (tenant deleted, typo) degrades to the finder silently.
  useEffect(() => {
    if (!addressFlowActive) return
    let cancelled = false
    const resolveInitial = async () => {
      const paramSlug = extractSlugCandidate(searchParams.get('workspace') ?? '')
      const candidate = paramSlug || getRememberedTenantSlug() || ''
      if (candidate === '') {
        setPhase('find')
        return
      }
      // FIX-20260929-121120 / B1: the candidate is about to be re-verified
      // and is NOT yet confirmed — unbind it for the duration so it cannot
      // flow out on API calls (apiClient attaches X-Tenant from the
      // session binding on EVERY request). A verified discovery re-binds
      // below; an unknown one leaves the stale binding cleaned.
      setResolvedTenantSlug(null)
      try {
        const discovery = await discoverTenant(candidate)
        if (cancelled) return
        if (discovery.tenant) {
          bindWorkspace(discovery.tenant)
          // Deep links and returning visitors decide remembering through
          // the finder's checkbox only — never implicitly.
          setPhase('card')
        } else {
          // Unknown/deleted workspace (uniform null — no enumeration):
          // drop the stale hint AND the session binding when it matches
          // the rejected slug (FIX-20260929-121120 / B1) — never let an
          // unverified slug keep flowing out on API calls.
          setRememberedTenantSlug(null)
          if (sessionStorage.getItem('parthenon_tenant_slug') === candidate) {
            setResolvedTenantSlug(null)
          }
          setPhase('find')
        }
      } catch {
        // Discovery unreachable — stay on the finder rather than guessing.
        if (!cancelled) setPhase('find')
      }
    }
    void resolveInitial()
    return () => { cancelled = true }
  }, [addressFlowActive, searchParams])

  // FIX-20260929-121120 / B3: staleness guard for finder lookups — a late
  // discovery resolution must never bind after a newer lookup started or
  // the component unmounted (mirrors the mount effect's `cancelled` flag).
  // The ref survives re-renders; the unmount cleanup flips `alive` so an
  // abandoned lookup's continuation cannot clobber a workspace bound later
  // (possibly by a fresh mount of this page).
  const lookupStateRef = useRef({ sequence: 0, alive: true })
  useEffect(() => {
    // Re-arm on (re)mount — StrictMode's double effect invocation must not
    // leave a live page permanently marked unmounted.
    lookupStateRef.current.alive = true
    return () => { lookupStateRef.current.alive = false }
  }, [])

  /** Finder submit: resolve the entered address and bind the workspace. */
  const handleFindWorkspace = async () => {
    const candidate = extractSlugCandidate(workspaceInput)
    if (candidate === '' || lookingUp) return
    setFindError(null)
    setLookingUp(true)
    const lookupState = lookupStateRef.current
    const sequence = ++lookupState.sequence
    const isCurrent = () => lookupState.alive && sequence === lookupState.sequence
    try {
      const discovery = await discoverTenant(candidate)
      // Stale lookup (unmounted, or a newer lookup superseded this one):
      // never bind, never touch state.
      if (!isCurrent()) return
      if (!discovery.tenant) {
        // Unknown slugs are indistinguishable from deleted tenants —
        // neutral error, no workspace enumeration.
        setFindError(t('auth.findWorkspace.notFound'))
        return
      }
      bindWorkspace(discovery.tenant)
      setRememberedTenantSlug(rememberWorkspace ? discovery.tenant.slug : null)
      setPhase('card')
      // Re-resolve the OIDC start config (issuer/client) for the newly
      // bound tenant context before the visitor uses the SSO button.
      void refreshProviders?.()
    } catch {
      if (isCurrent()) setFindError(t('auth.findWorkspace.lookupFailed'))
    } finally {
      // Only the still-current lookup owns the spinner state — a stale
      // continuation must not reset a newer lookup's flag.
      if (isCurrent()) setLookingUp(false)
    }
  }

  /** "Not your workspace?" — unbind this tab and return to the finder. */
  const handleSwitchWorkspace = () => {
    setRememberedTenantSlug(null)
    setResolvedTenantSlug(null)
    // FIX-20261001-235247: also drop the HOST-derived store tenant —
    // without this the phase stays `idle` (addressFlowActive false) and
    // the finder never renders after switching away from a host-bound
    // workspace.
    clearResolvedTenant?.()
    setAddressTenant(null)
    setWorkspaceInput('')
    setFindError(null)
    setRememberWorkspace(true)
    setPhase('find')
    void refreshProviders?.()
  }

  // Provider / capability discovery
  const providers = providersData?.items ?? []
  const userProvider = providers.find((p) => p.provider_scope === 'user')
  const hasOidcProvider = !!userProvider?.is_enabled
  const providerName = userProvider?.display_name || t('auth.oidcProvider')
  const superAdminEnabled = superAdminStatus?.is_enabled ?? false

  // Multi-tenancy on → platform password sign-in is always available
  // (independent of OIDC/super-admin state).  `null` = discovery still in
  // flight — hold off, mirroring the sign-up entry link behaviour.
  const passwordSignInAvailable = multiTenancyEnabled === true
  const signInFlowsAvailable = !tenantBlocked && !tenantSignInUnavailable
  // Legacy flows render exactly as before on the idle phase (tenancy off,
  // host-derived tenant).  The address-resolved card reuses them under the
  // same guards; the resolving/find phases replace them entirely.
  const showSignInFlows =
    signInFlowsAvailable && (effectivePhase === 'idle' || effectivePhase === 'card')
  const noSignInAvailable =
    showSignInFlows && !passwordSignInAvailable && !hasOidcProvider && !superAdminEnabled

  // FIX-20261001-235247 (Defect 1): the "Use a different workspace" escape
  // hatch must be reachable in EVERY tenant-bound sign-in state — the
  // address-resolved card (root workspace included) AND the host-derived
  // legacy page (resolvedTenant set by AuthProvider — the phase stays
  // `idle` there, which previously hid the link entirely).  The finder
  // phase already IS the switch affordance; `resolving` is transient.
  // Tenancy OFF is excluded: that deployment IS the root workspace and no
  // other workspace exists (the finder itself requires tenancy on).
  const canSwitchWorkspace =
    multiTenancyEnabled === true &&
    (effectivePhase === 'card' || resolvedTenant !== null)

  const handlePasswordSignIn = async () => {
    try {
      setSignInError(null)
      setSigningIn(true)
      const result = await loginPassword(email.trim().toLowerCase(), signInPassword)

      // Store the tenant-bound token exactly like the other auth flows
      // (SignUpPage / super admin / OidcCallback) and bind this per-tab
      // session to the signed-in tenant.
      localStorage.setItem('access_token', result.access_token)
      setToken(result.access_token)
      setResolvedTenantSlug(result.tenant_slug)

      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSignInError(extractLoginErrorMessage(err, t('auth.loginFailed')))
    } finally {
      setSigningIn(false)
    }
  }

  const handleSuperAdminLogin = async () => {
    try {
      setLoginError(null)
      setLoggingIn(true)
      const result = await superAdminLogin(username, password)

      // Store the super admin token
      localStorage.setItem('access_token', result.access_token)
      localStorage.setItem('super_admin_token', result.access_token)
      setToken(result.access_token)

      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setLoginError(extractLoginErrorMessage(err, t('auth.loginFailed')))
    } finally {
      setLoggingIn(false)
    }
  }

  if (isLoading) {
    return (
      <Container maxWidth="sm" sx={{ mt: 12, textAlign: 'center' }}>
        <CircularProgress />
      </Container>
    )
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 12 }}>
      <Paper elevation={3} sx={{ p: 6, textAlign: 'center' }}>
        <LockOutlinedIcon color="primary" sx={{ fontSize: 56, mb: 2 }} />
        {multiTenancyEnabled && brandedTenant !== null && brandedTenant.status === 'active' && (
          <Typography variant="subtitle1" color="text.secondary" gutterBottom>
            {t('auth.tenantWorkspaceOf', { name: brandedTenant.name })}
          </Typography>
        )}
        <Typography variant="h4" fontWeight={700} gutterBottom>
          {t('app.title')}
        </Typography>

        {/* Tenant blocked (suspended/deleted) — no sign-in flows at all */}
        {tenantBlocked && (
          <Box>
            <Alert severity="error" sx={{ mb: 3, textAlign: 'left' }}>
              {t('auth.tenantBlocked', { status: brandedTenant?.status ?? '' })}
            </Alert>
          </Box>
        )}

        {/* Host-derived tenant active but sign-in not configured */}
        {!tenantBlocked && tenantSignInUnavailable && (
          <Box>
            <Alert severity="warning" sx={{ mb: 3, textAlign: 'left' }}>
              {t('auth.tenantSignInUnavailable')}
            </Alert>
          </Box>
        )}

        {/* Workspace-address step: resolving the entry slug, or the
            "find your workspace" card when nothing is bound yet */}
        {effectivePhase === 'resolving' && (
          <Box mt={4}>
            <CircularProgress />
          </Box>
        )}
        {effectivePhase === 'find' && renderFindWorkspaceForm()}

        {showSignInFlows && (
          <>
            {/* Primary: email + password (platform accounts, tenancy on) */}
            {passwordSignInAvailable && (
              <Box>
                {renderPasswordForm()}
                {hasOidcProvider && (
                  <Divider sx={{ my: 2 }}>{t('auth.or')}</Divider>
                )}
              </Box>
            )}

            {/* OIDC sign-in — shown whenever a user-scope provider is
                configured, never a gate (password sign-in works without it) */}
            {hasOidcProvider && (
              <Box>
                {!passwordSignInAvailable && (
                  <Typography variant="body1" color="text.secondary" mb={4}>
                    {t('auth.loginWith')}
                  </Typography>
                )}
                <Button
                  variant={passwordSignInAvailable ? 'outlined' : 'contained'}
                  size="large"
                  fullWidth
                  onClick={login}
                >
                  {t('auth.loginWithProvider', { provider: providerName })}
                </Button>
              </Box>
            )}

            {/* Nothing configured on this deployment (tenancy off) — the
                setup wizard is gone; OIDC is configured post-sign-in via
                System Config, so explain the dead end instead */}
            {noSignInAvailable && (
              <Alert severity="info" sx={{ mb: 3, textAlign: 'left' }}>
                {t('auth.noSignInAvailable')}
              </Alert>
            )}
          </>
        )}

        {/* Switch-workspace escape hatch (FIX-20261001-235247): shown on
            every bound-workspace sign-in state — address-resolved card
            (root included) and host-derived tenants alike.  Clears the
            remembered workspace, the tab binding AND the host-derived
            store tenant, then lands on the finder. */}
        {canSwitchWorkspace && (
          <Box mt={3}>
            <Link
              component="button"
              variant="body2"
              color="text.secondary"
              underline="hover"
              onClick={handleSwitchWorkspace}
              data-testid="switch-workspace-link"
            >
              {t('auth.findWorkspace.notYourWorkspace')}
            </Link>
          </Box>
        )}

        {/* Sign-up entry (multi-tenancy on; hidden when the tenant is blocked) */}
        {multiTenancyEnabled && !tenantBlocked && (
          <Box mt={3}>
            <Typography variant="body2" color="text.secondary" component="span">
              {t('auth.noWorkspaceYet')}{' '}
            </Typography>
            <Link
              component={RouterLink}
              to="/signup"
              variant="body2"
              data-testid="signup-entry-link"
            >
              {t('auth.createWorkspace')}
            </Link>
          </Box>
        )}

        {/* Super admin break-glass entry (Phase 11 task 11.6) — the
            discreet platform-admin expansion was REMOVED from tenant and
            legacy workspaces: the break-glass account is available ONLY
            at the ROOT workspace (the entered/resolved workspace is
            `root`, or the tenancy-off deployment which IS the root
            workspace).  First-run bootstrap and disaster recovery path
            only; the workspace-address flow is otherwise identical. */}
        {superAdminEnabled && isRootWorkspace && (
          <Box mt={3}>
            {!showSuperAdminForm ? (
              <Link
                component="button"
                variant="body2"
                color="text.secondary"
                underline="hover"
                onClick={() => setShowSuperAdminForm(true)}
                data-testid="super-admin-entry"
              >
                {t('auth.platformAdminSignIn')}
              </Link>
            ) : (
              renderSuperAdminForm()
            )}
          </Box>
        )}
      </Paper>
    </Container>
  )

  /** AWS-style workspace finder: enter a workspace address to sign in to. */
  function renderFindWorkspaceForm() {
    const candidate = extractSlugCandidate(workspaceInput)
    return (
      <Box data-testid="workspace-finder-form" sx={{ textAlign: 'left' }}>
        <Typography variant="body1" color="text.secondary" mb={2}>
          {t('auth.findWorkspace.subtitle')}
        </Typography>
        {findError && (
          <Alert severity="error" sx={{ mb: 2, textAlign: 'left' }} data-testid="workspace-find-error">
            {findError}
          </Alert>
        )}
        <TextField
          label={t('auth.findWorkspace.addressLabel')}
          placeholder={t('auth.findWorkspace.addressPlaceholder')}
          value={workspaceInput}
          onChange={(e) => setWorkspaceInput(e.target.value)}
          fullWidth
          margin="normal"
          autoComplete="off"
          autoFocus
          helperText={
            workspaceInput.includes('.')
              ? t('auth.findWorkspace.slugHint', { slug: candidate })
              : undefined
          }
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleFindWorkspace()
          }}
          data-testid="workspace-address-input"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={rememberWorkspace}
              onChange={(e) => setRememberWorkspace(e.target.checked)}
              data-testid="remember-workspace-checkbox"
            />
          }
          label={t('auth.findWorkspace.remember')}
        />
        <Button
          variant="contained"
          fullWidth
          disabled={lookingUp || candidate === ''}
          onClick={() => { void handleFindWorkspace(); }}
          sx={{ mt: 1 }}
          data-testid="find-workspace-submit"
        >
          {lookingUp ? t('auth.findWorkspace.lookup') : t('auth.findWorkspace.continue')}
        </Button>
      </Box>
    )
  }

  function renderPasswordForm() {
    return (
      <Box data-testid="password-signin-form">
        {signInError && (
          <Alert severity="error" sx={{ mb: 2, textAlign: 'left' }}>
            {signInError}
          </Alert>
        )}
        <TextField
          label={t('auth.email')}
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          fullWidth
          margin="normal"
          autoComplete="email"
          data-testid="login-email-input"
        />
        <TextField
          label={t('auth.password')}
          type="password"
          value={signInPassword}
          onChange={(e) => setSignInPassword(e.target.value)}
          fullWidth
          margin="normal"
          autoComplete="current-password"
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handlePasswordSignIn()
          }}
        />
        <Button
          variant="contained"
          fullWidth
          disabled={signingIn || !email || !signInPassword}
          onClick={() => { void handlePasswordSignIn(); }}
          sx={{ mt: 2 }}
          data-testid="login-password-submit"
        >
          {signingIn ? t('auth.loggingIn') : t('auth.login')}
        </Button>
      </Box>
    )
  }

  function renderSuperAdminForm() {
    return (
      <Box data-testid="super-admin-form">
        {!hasOidcProvider && (
          <Alert severity="info" sx={{ mb: 2, textAlign: 'left' }}>
            {t('auth.superAdminInfo')}
          </Alert>
        )}
        {loginError && (
          <Alert severity="error" sx={{ mb: 2, textAlign: 'left' }}>
            {loginError}
          </Alert>
        )}
        <TextField
          label={t('auth.username')}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          fullWidth
          margin="normal"
          autoComplete="username"
        />
        <TextField
          label={t('auth.password')}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          fullWidth
          margin="normal"
          autoComplete="current-password"
          onKeyDown={(e) => {
            if (e.key === 'Enter') void handleSuperAdminLogin()
          }}
        />
        <Button
          variant="contained"
          fullWidth
          disabled={loggingIn || !username || !password}
          onClick={() => { void handleSuperAdminLogin(); }}
          sx={{ mt: 2 }}
        >
          {loggingIn ? t('auth.loggingIn') : t('auth.login')}
        </Button>
        <Button
          fullWidth
          onClick={() => { setShowSuperAdminForm(false); setLoginError(null) }}
          sx={{ mt: 1 }}
          size="small"
        >
          {t('app.back')}
        </Button>
      </Box>
    )
  }
}

/** Extract a human-readable message from a login API failure. */
function extractLoginErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error) return err.message
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
    if (typeof detail === 'string' && detail !== '') return detail
  }
  return fallback
}
