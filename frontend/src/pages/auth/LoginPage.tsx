import { Button, Container, Typography, Paper } from '@mui/material'
import LockOutlinedIcon from '@mui/icons-material/LockOutlined'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

/**
 * Login page — initiates OIDC redirect flow for user authentication.
 */
export function LoginPage() {
  const { t } = useTranslation()
  const { login, isAuthenticated } = useAuthStore()
  const navigate = useNavigate()

  useEffect(() => {
    if (isAuthenticated) navigate('/dashboard', { replace: true })
  }, [isAuthenticated, navigate])

  return (
    <Container maxWidth="sm" sx={{ mt: 12 }}>
      <Paper elevation={3} sx={{ p: 6, textAlign: 'center' }}>
        <LockOutlinedIcon color="primary" sx={{ fontSize: 56, mb: 2 }} />
        <Typography variant="h4" fontWeight={700} gutterBottom>
          {t('app.title')}
        </Typography>
        <Typography variant="body1" color="text.secondary" mb={4}>
          {t('auth.loginWith')}
        </Typography>
        <Button variant="contained" size="large" fullWidth onClick={login}>
          {t('auth.login')}
        </Button>
      </Paper>
    </Container>
  )
}
