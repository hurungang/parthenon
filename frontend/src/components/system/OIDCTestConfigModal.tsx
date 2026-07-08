import { useState } from 'react'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { testOidcConnection, type OIDCTestStep, type OIDCTestResponse } from '../../api/systemConfigApi'

interface OIDCTestConfigModalProps {
  open: boolean
  onClose: () => void
  issuerUrl: string
  clientId: string
}

export function OIDCTestConfigModal({
  open,
  onClose,
  issuerUrl,
  clientId,
}: OIDCTestConfigModalProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<OIDCTestResponse | null>(null)

  const handleClose = () => {
    clearDialogError()
    setResult(null)
    onClose()
  }

  const handleRunTest = async () => {
    try {
      clearDialogError()
      setTesting(true)
      setResult(null)
      const res = await testOidcConnection({
        issuer_url: issuerUrl,
        client_id: clientId || undefined,
      })
      setResult(res)
    } catch (err) {
      setDialogError(err)
    } finally {
      setTesting(false)
    }
  }

  const steps: OIDCTestStep[] = result?.steps ?? []
  const activeStep = testing
    ? steps.length
    : result
      ? steps.filter((s) => s.status === 'passed').length
      : 0

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>{t('systemConfig.oidcTest.testConfigTitle')}</DialogTitle>
      <DialogContent>
        {dialogError && (
          <Box mb={2}>
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          </Box>
        )}

        {!testing && !result && (
          <>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('systemConfig.oidcTest.preTestState')}
            </Typography>
            <Box display="grid" gridTemplateColumns="1fr 1fr" gap={1} mb={2}>
              <Typography variant="caption" color="text.secondary">
                {t('systemConfig.oidcTest.issuerUrlLabel')}:
              </Typography>
              <Typography variant="caption">{issuerUrl}</Typography>
              {clientId && (
                <>
                  <Typography variant="caption" color="text.secondary">
                    {t('systemConfig.oidcTest.clientIdLabel')}:
                  </Typography>
                  <Typography variant="caption">{clientId}</Typography>
                </>
              )}
            </Box>
          </>
        )}

        {testing && (
          <Box textAlign="center" py={3}>
            <CircularProgress size={40} />
            <Typography mt={1}>{t('systemConfig.oidcTest.testing')}</Typography>
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
                bgcolor: result.success ? 'success.light' : 'error.light',
                color: result.success ? 'success.contrastText' : 'error.contrastText',
              }}
            >
              <Typography fontWeight={600}>
                {result.success
                  ? t('systemConfig.oidcTest.success')
                  : t('systemConfig.oidcTest.failed')}
              </Typography>
            </Box>

            <Stepper activeStep={activeStep} orientation="vertical">
              {steps.map((step) => (
                <Step key={step.step} completed={step.status === 'passed'}>
                  <StepLabel
                    error={step.status === 'failed'}
                    optional={
                      <Typography variant="caption" color="text.secondary">
                        {step.detail}
                      </Typography>
                    }
                  >
                    {t(`systemConfig.oidcTest.steps.${step.step}`, step.step)}
                  </StepLabel>
                </Step>
              ))}
            </Stepper>

            {result.discovery_doc && (
              <Box mt={2}>
                <Typography variant="subtitle2" gutterBottom>
                  {t('systemConfig.oidcTest.discoveryDoc')}
                </Typography>
                <Box
                  component="pre"
                  sx={{
                    p: 2,
                    bgcolor: 'grey.100',
                    borderRadius: 1,
                    fontSize: '0.75rem',
                    overflow: 'auto',
                    maxHeight: 200,
                  }}
                >
                  {JSON.stringify(result.discovery_doc, null, 2)}
                </Box>
              </Box>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        {!testing && !result && (
          <Button
            variant="contained"
            onClick={() => { void handleRunTest(); }}
            disabled={!issuerUrl}
          >
            {t('systemConfig.oidcTest.runTest')}
          </Button>
        )}
        {result && (
          <Button onClick={handleRunTest} disabled={testing}>
            {t('systemConfig.oidcTest.retry')}
          </Button>
        )}
        <Button onClick={handleClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
