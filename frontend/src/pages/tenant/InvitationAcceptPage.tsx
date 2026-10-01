/**
 * InvitationAcceptPage — public token-based invitation acceptance.
 * The invitee signs in first (JWT required by the API), then pastes (or
 * follows a link carrying) the one-time invitation token.  On success
 * they land in their new organization's workspace.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Button,
  Card,
  CardContent,
  CircularProgress,
  TextField,
  Typography,
  Alert,
  Container,
} from '@mui/material'
import BusinessIcon from '@mui/icons-material/Business'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import { acceptInvitation } from '../../api/tenantApi'
import { setResolvedTenantSlug } from '../../api/tenantAuthApi'
import { useAuthStore } from '../../stores/authStore'

export function InvitationAcceptPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { isAuthenticated } = useAuthStore()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [token, setToken] = useState(searchParams.get('token') ?? '')
  const [joined, setJoined] = useState<{ name: string; slug: string } | null>(null)

  const acceptMutation = useMutation({
    mutationFn: () => acceptInvitation(token.trim()),
    onSuccess: (settings) => {
      setResolvedTenantSlug(settings.slug)
      setJoined({ name: settings.name, slug: settings.slug })
    },
    onError: (err) => setDialogError(err),
  })

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ mt: 12 }}>
        <Alert severity="info">{t('tenant.accept.signInFirst')}</Alert>
      </Container>
    )
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 12 }}>
      <Card>
        <CardContent sx={{ textAlign: 'center' }}>
          <BusinessIcon color="primary" sx={{ fontSize: 48, mb: 1 }} />
          <Typography variant="h5" gutterBottom>
            {t('tenant.accept.title')}
          </Typography>

          {joined ? (
            <>
              <Alert severity="success" sx={{ mb: 2 }}>
                {t('tenant.accept.joined', { name: joined.name })}
              </Alert>
              <Button
                variant="contained"
                onClick={() => navigate('/dashboard', { replace: true })}
              >
                {t('tenant.accept.enter')}
              </Button>
            </>
          ) : (
            <>
              {dialogError != null && (
                <PermissionDeniedAlert
                  error={dialogError}
                  fallbackMessage={t('app.error')}
                />
              )}
              <Typography variant="body2" color="text.secondary" mb={2}>
                {t('tenant.accept.help')}
              </Typography>
              <TextField
                label={t('tenant.accept.tokenLabel')}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                fullWidth
                margin="normal"
                data-testid="accept-token-input"
              />
              <Button
                variant="contained"
                fullWidth
                disabled={acceptMutation.isPending || token.trim().length < 8}
                onClick={() => {
                  clearDialogError()
                  acceptMutation.mutate()
                }}
                sx={{ mt: 1 }}
              >
                {acceptMutation.isPending ? <CircularProgress size={18} /> : t('tenant.accept.join')}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </Container>
  )
}
