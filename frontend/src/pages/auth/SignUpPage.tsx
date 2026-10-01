/**
 * SignUpPage — PUBLIC account-first self-serve registration (Phase 10).
 *
 * Two steps: account (email + password) → organization (name + unique
 * address).  Client- and server-side validation; duplicate-email,
 * one-tenant-per-user and address-conflict errors surface clearly.
 * Successful registration stores the returned tenant-bound session and
 * routes the new root user into guided onboarding.  The page only
 * renders the form when the tenancy switch is on (probed via the same
 * public discovery the LoginPage uses); all strings via i18next t().
 */
import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Paper,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material'
import PersonAddIcon from '@mui/icons-material/PersonAdd'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import {
  registerAccount,
  setResolvedTenantSlug,
} from '../../api/tenantAuthApi'

const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$/
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

export function SignUpPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { setToken, multiTenancyEnabled } = useAuthStore()

  const [step, setStep] = useState<0 | 1>(0)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [organizationName, setOrganizationName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [signupError, setSignupError] = useState<string | null>(null)

  const switchResolved = multiTenancyEnabled !== null
  const tenancyOff = multiTenancyEnabled === false

  // Address auto-derived from the organization name until edited
  const handleOrganizationName = (value: string) => {
    setOrganizationName(value)
    if (!slugTouched) {
      setSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, '')
          .slice(0, 63),
      )
    }
  }

  const step0Error = useMemo(() => {
    if (!EMAIL_PATTERN.test(email.trim())) return t('signup.error.email')
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/[0-9]/.test(password))
      return t('signup.error.password')
    if (password !== confirmPassword) return t('signup.error.passwordMismatch')
    return null
  }, [email, password, confirmPassword, t])

  const step1Error = useMemo(() => {
    if (!organizationName.trim()) return t('signup.error.orgName')
    if (!SLUG_PATTERN.test(slug.trim()))
      return t('signup.error.slug')
    return null
  }, [organizationName, slug, t])

  const handleContinue = () => {
    setSignupError(null)
    if (step0Error) {
      setSignupError(step0Error)
      return
    }
    setStep(1)
  }

  const handleSubmit = async () => {
    setSignupError(null)
    const clientError = step0Error ?? step1Error
    if (clientError) {
      setSignupError(clientError)
      return
    }
    try {
      setSubmitting(true)
      const result = await registerAccount({
        email: email.trim().toLowerCase(),
        password,
        organization_name: organizationName.trim(),
        slug: slug.trim().toLowerCase(),
      })
      // Land the new root user in guided onboarding, tenant-bound
      localStorage.setItem('access_token', result.access_token)
      setToken(result.access_token)
      setResolvedTenantSlug(result.slug)
      navigate('/tenant/onboarding', { replace: true })
    } catch (err: unknown) {
      const detail = (
        err as { response?: { data?: { detail?: unknown } } }
      )?.response?.data?.detail
      const message =
        typeof detail === 'string'
          ? detail
          : typeof err === 'object' && err !== null && 'message' in err
            ? String((err as Error).message)
            : t('signup.error.generic')
      setSignupError(translateServerError(message, t))
    } finally {
      setSubmitting(false)
    }
  }

  if (!switchResolved) {
    return (
      <Container maxWidth="sm" sx={{ mt: 12, textAlign: 'center' }}>
        <CircularProgress />
      </Container>
    )
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 6, mb: 8 }}>
      <Paper elevation={3} sx={{ p: 5 }}>
        <Box textAlign="center" mb={3}>
          <PersonAddIcon color="primary" sx={{ fontSize: 44, mb: 1 }} />
          <Typography variant="h4" fontWeight={700} gutterBottom>
            {t('signup.title')}
          </Typography>
          <Typography variant="body1" color="text.secondary">
            {t('signup.subtitle')}
          </Typography>
        </Box>

        {tenancyOff && (
          <Alert severity="info" sx={{ mb: 3 }}>
            {t('signup.unavailable')}
          </Alert>
        )}

        {!tenancyOff && (
          <>
            <Stepper activeStep={step} sx={{ mb: 3 }}>
              <Step>
                <StepLabel>{t('signup.stepAccount')}</StepLabel>
              </Step>
              <Step>
                <StepLabel>{t('signup.stepOrganization')}</StepLabel>
              </Step>
            </Stepper>

            {signupError && (
              <Alert severity="error" sx={{ mb: 2 }} data-testid="signup-error">
                {signupError}
              </Alert>
            )}

            {step === 0 ? (
              <Box data-testid="signup-step-account">
                <TextField
                  label={t('signup.email')}
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  fullWidth
                  margin="normal"
                  autoComplete="email"
                  data-testid="signup-email-input"
                />
                <TextField
                  label={t('signup.password')}
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  fullWidth
                  margin="normal"
                  autoComplete="new-password"
                  helperText={t('signup.passwordHint')}
                  data-testid="signup-password-input"
                />
                <TextField
                  label={t('signup.confirmPassword')}
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  fullWidth
                  margin="normal"
                  autoComplete="new-password"
                />
                <Button
                  variant="contained"
                  fullWidth
                  size="large"
                  disabled={!email || !password || !confirmPassword}
                  onClick={handleContinue}
                  sx={{ mt: 2 }}
                >
                  {t('signup.continue')}
                </Button>
              </Box>
            ) : (
              <Box data-testid="signup-step-organization">
                <TextField
                  label={t('signup.orgName')}
                  value={organizationName}
                  onChange={(e) => handleOrganizationName(e.target.value)}
                  fullWidth
                  margin="normal"
                  data-testid="signup-org-name-input"
                />
                <TextField
                  label={t('signup.orgAddress')}
                  value={slug}
                  onChange={(e) => {
                    setSlugTouched(true)
                    setSlug(e.target.value.toLowerCase())
                  }}
                  fullWidth
                  margin="normal"
                  helperText={t('signup.orgAddressHint')}
                  InputProps={{ startAdornment: <Typography sx={{ mr: 0.5 }}>/</Typography> }}
                  data-testid="signup-slug-input"
                />
                <Box display="flex" gap={1} mt={2}>
                  <Button fullWidth onClick={() => setStep(0)}>
                    {t('app.back')}
                  </Button>
                  <Button
                    variant="contained"
                    fullWidth
                    disabled={submitting || !organizationName.trim() || !slug.trim()}
                    onClick={() => void handleSubmit()}
                    data-testid="signup-submit"
                  >
                    {submitting ? <CircularProgress size={20} /> : t('signup.createWorkspace')}
                  </Button>
                </Box>
              </Box>
            )}
          </>
        )}

        <Box textAlign="center" mt={3}>
          <Typography variant="body2" color="text.secondary" component="span">
            {t('signup.haveAccount')}{' '}
          </Typography>
          <Button component={RouterLink} to="/login" size="small">
            {t('signup.signIn')}
          </Button>
        </Box>
      </Paper>
    </Container>
  )
}

/** Map known server rejection messages to i18n keys where possible. */
function translateServerError(
  message: string,
  t: (key: string) => string,
): string {
  const lowered = message.toLowerCase()
  if (lowered.includes('email already exists'))
    return t('signup.error.emailExists')
  if (lowered.includes('already taken')) return t('signup.error.slugTaken')
  if (lowered.includes('only one organization') || lowered.includes('one organization'))
    return t('signup.error.oneTenantPerUser')
  if (lowered.includes('not available'))
    return t('signup.unavailable')
  return message
}
