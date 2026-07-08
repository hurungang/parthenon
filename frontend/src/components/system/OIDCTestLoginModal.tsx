import { useState, useEffect, useRef } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { initiateTestLogin, getTestLoginStatus } from '../../api/systemConfigApi'

interface OIDCTestLoginModalProps {
  open: boolean
  onClose: () => void
  issuerUrl: string
  clientId: string
  clientSecret?: string
}

export function OIDCTestLoginModal({
  open,
  onClose,
  issuerUrl,
  clientId,
  clientSecret,
}: OIDCTestLoginModalProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [testId, setTestId] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const handleClose = () => {
    clearDialogError()
    setResult(null)
    setTestId(null)
    setTesting(false)
    setPolling(false)
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    onClose()
  }

  const handleInitiate = async () => {
    try {
      clearDialogError()
      setTesting(true)
      setResult(null)

      const res = await initiateTestLogin({
        issuer_url: issuerUrl,
        client_id: clientId,
        client_secret: clientSecret || undefined,
        redirect_uri: window.location.origin + '/callback',
      })

      setTestId(res.test_id)
      setPolling(true)

      // Open the redirect in a new window
      const popup = window.open(res.redirect_url, 'oidc-test-login', 'width=600,height=700')

      // Poll for results
      pollRef.current = setInterval(async () => {
        try {
          const status = await getTestLoginStatus(res.test_id)
          if (status.status === 'completed' || status.status === 'failed') {
            if (pollRef.current) clearInterval(pollRef.current)
            setPolling(false)
            setTesting(false)
            setResult(status)
            if (popup && !popup.closed) {
              popup.close()
            }
          }
        } catch {
          // Poll failed, but keep trying
        }
      }, 2000)
    } catch (err) {
      setDialogError(err)
      setTesting(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>{t('systemConfig.oidcTest.testLoginTitle')}</DialogTitle>
      <DialogContent>
        {dialogError && (
          <Box mb={2}>
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          </Box>
        )}

        {!testing && !result && !polling && (
          <>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('systemConfig.oidcTest.testLoginWarning')}
            </Typography>
            <Box display="grid" gridTemplateColumns="1fr 1fr" gap={1} mb={2}>
              <Typography variant="caption" color="text.secondary">
                {t('systemConfig.oidcTest.issuerUrlLabel')}:
              </Typography>
              <Typography variant="caption">{issuerUrl}</Typography>
              <Typography variant="caption" color="text.secondary">
                {t('systemConfig.oidcTest.clientIdLabel')}:
              </Typography>
              <Typography variant="caption">{clientId}</Typography>
            </Box>
          </>
        )}

        {(testing || polling) && (
          <Box textAlign="center" py={3}>
            <CircularProgress size={40} />
            <Typography mt={1}>
              {polling
                ? t('systemConfig.oidcTest.polling')
                : t('systemConfig.oidcTest.testing')}
            </Typography>
            <LinearProgress sx={{ mt: 2 }} />
          </Box>
        )}

        {result && (
          <>
            <Box
              sx={{
                mb: 2,
                p: 2,
                borderRadius: 1,
                bgcolor: result.status === 'completed' ? 'success.light' : 'error.light',
                color: result.status === 'completed' ? 'success.contrastText' : 'error.contrastText',
              }}
            >
              <Typography fontWeight={600}>
                {result.status === 'completed'
                  ? t('systemConfig.oidcTest.success')
                  : t('systemConfig.oidcTest.failed')}
              </Typography>
            </Box>

            {result.status === 'completed' && (
              <>
                <Typography variant="subtitle2" gutterBottom>
                  {t('systemConfig.oidcTest.claims')}
                </Typography>
                {result.claims || result.id_token_claims ? (
                  <Box
                    component="pre"
                    sx={{
                      p: 2,
                      bgcolor: 'grey.100',
                      borderRadius: 1,
                      fontSize: '0.75rem',
                      overflow: 'auto',
                      maxHeight: 300,
                    }}
                  >
                    {JSON.stringify(result.claims || result.id_token_claims, null, 2)}
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    {t('systemConfig.oidcTest.noClaims')}
                  </Typography>
                )}
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        {result && (
          <Button onClick={handleInitiate} disabled={testing || polling}>
            {t('systemConfig.oidcTest.retry')}
          </Button>
        )}
        {!result && !testing && !polling && (
          <Button onClick={() => void handleInitiate()} variant="contained">
            {t('systemConfig.oidcTest.initiateLogin')}
          </Button>
        )}
        <Button onClick={handleClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
