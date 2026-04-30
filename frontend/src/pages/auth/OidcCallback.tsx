import { useEffect, useRef } from 'react'
import { flushSync } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { CircularProgress, Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../../stores/authStore'

const OIDC_AUTHORITY = import.meta.env.VITE_OIDC_AUTHORITY ?? 'http://localhost:8082/realms/parthenon'
const OIDC_CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID ?? 'parthenon-api-ui'

/**
 * OIDC callback handler — exchanges authorization code for tokens.
 */
export function OidcCallback() {
  const { t } = useTranslation()
  const { setToken } = useAuthStore()
  const navigate = useNavigate()
  const exchanged = useRef(false)

  useEffect(() => {
    if (exchanged.current) return
    exchanged.current = true

    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')

    if (!code) {
      navigate('/login', { replace: true })
      return
    }

    // Retrieve PKCE code verifier from sessionStorage
    const codeVerifier = sessionStorage.getItem('pkce_code_verifier')
    if (!codeVerifier) {
      console.error('PKCE code verifier not found in session storage')
      navigate('/login', { replace: true })
      return
    }

    const redirectUri = `${window.location.origin}/callback`

    fetch(`${OIDC_AUTHORITY}/protocol/openid-connect/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        client_id: OIDC_CLIENT_ID,
        code,
        redirect_uri: redirectUri,
        code_verifier: codeVerifier,
      }),
    })
      .then((res) => {
        if (!res.ok) {
          return res.text().then(text => {
            console.error('Token exchange failed:', res.status, text)
            throw new Error('Token exchange failed')
          })
        }
        return res.json() as Promise<{ access_token: string; refresh_token: string; id_token?: string }>
      })
      .then((data) => {
        // Clear the PKCE verifier after successful exchange
        sessionStorage.removeItem('pkce_code_verifier')
        
        // flushSync forces AuthContext state to update synchronously before
        // navigate() renders ProtectedRoute, preventing an isAuthenticated=false flash.
        flushSync(() => {
          setToken(data.access_token)
        })
        localStorage.setItem('refresh_token', data.refresh_token)
        // Store id_token for proper Keycloak logout
        if (data.id_token) {
          localStorage.setItem('id_token', data.id_token)
        }
        navigate('/dashboard', { replace: true })
      })
      .catch(() => navigate('/login', { replace: true }))
  }, [navigate, setToken])

  return (
    <Box display="flex" flexDirection="column" alignItems="center" justifyContent="center" height="100vh">
      <CircularProgress size={48} />
      <Typography variant="body1" mt={2}>
        {t('app.loading')}
      </Typography>
    </Box>
  )
}
