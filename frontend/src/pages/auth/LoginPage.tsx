import { useState, useEffect } from 'react'
import {
  Button,
  Container,
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
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getIdentityProviders, getSuperAdminStatus, superAdminLogin } from '../../api/systemConfigApi'
import { useAuthStore } from '../../stores/authStore'

type LoginState = 'loading' | 'super_admin_only' | 'oidc_only' | 'both' | 'setup_wizard'

export function LoginPage() {
  const { t } = useTranslation()
  const { login, isAuthenticated, setToken } = useAuthStore()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState<string | null>(null)
  const [loggingIn, setLoggingIn] = useState(false)
  const [showSuperAdminForm, setShowSuperAdminForm] = useState(false)

  // Discover active providers and super admin status on load
  const { data: providersData, isLoading: providersLoading } = useQuery({
    queryKey: ['system', 'identity-providers'],
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

  // Determine login state
  const providers = providersData?.items ?? []
  const hasOidcProvider = providers.some((p) => p.is_enabled)
  const superAdminEnabled = superAdminStatus?.is_enabled ?? false

  let loginState: LoginState = 'loading'
  if (!isLoading) {
    if (!hasOidcProvider && !superAdminEnabled) {
      loginState = 'setup_wizard'
    } else if (!hasOidcProvider && superAdminEnabled) {
      loginState = 'super_admin_only'
    } else if (hasOidcProvider && !superAdminEnabled) {
      loginState = 'oidc_only'
    } else if (hasOidcProvider && superAdminEnabled) {
      loginState = 'both'
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
      const message = err instanceof Error
        ? err.message
        : (typeof err === 'object' && err !== null && 'response' in err
            ? String((err as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? 'Login failed')
            : 'Login failed')
      setLoginError(message)
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
        <Typography variant="h4" fontWeight={700} gutterBottom>
          {t('app.title')}
        </Typography>

        {/* Setup wizard redirect */}
        {loginState === 'setup_wizard' && (
          <Box>
            <Alert severity="warning" sx={{ mb: 3, textAlign: 'left' }}>
              {t('auth.setupWizard')}
            </Alert>
            <Button
              variant="contained"
              size="large"
              onClick={() => navigate('/setup')}
            >
              {t('auth.goToSetup')}
            </Button>
          </Box>
        )}

        {/* Super admin only */}
        {loginState === 'super_admin_only' && (
          <Box>
            <Alert severity="info" sx={{ mb: 3, textAlign: 'left' }}>
              {t('auth.superAdminInfo')}
            </Alert>
            {renderSuperAdminForm()}
          </Box>
        )}

        {/* OIDC only */}
        {loginState === 'oidc_only' && (
          <Box>
            <Typography variant="body1" color="text.secondary" mb={4}>
              {t('auth.loginWith')}
            </Typography>
            <Button variant="contained" size="large" fullWidth onClick={login}>
              {t('auth.loginWithOidc')}
            </Button>
          </Box>
        )}

        {/* Both */}
        {loginState === 'both' && (
          <Box>
            <Typography variant="body1" color="text.secondary" mb={3}>
              {t('auth.loginWith')}
            </Typography>
            <Button variant="contained" size="large" fullWidth onClick={login} sx={{ mb: 2 }}>
              {t('auth.loginWithOidc')}
            </Button>

            <Divider sx={{ my: 2 }}>{t('auth.or')}</Divider>

            {!showSuperAdminForm ? (
              <Button
                variant="outlined"
                onClick={() => setShowSuperAdminForm(true)}
              >
                {t('auth.loginAsSuperAdmin')}
              </Button>
            ) : (
              renderSuperAdminForm()
            )}
          </Box>
        )}
      </Paper>
    </Container>
  )

  function renderSuperAdminForm() {
    return (
      <Box>
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
        {loginState === 'both' && (
          <Button
            fullWidth
            onClick={() => setShowSuperAdminForm(false)}
            sx={{ mt: 1 }}
            size="small"
          >
            {t('app.back')}
          </Button>
        )}
      </Box>
    )
  }
}
