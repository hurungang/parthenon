import { useTranslation } from 'react-i18next'
import { Alert, Box, CircularProgress, Typography } from '@mui/material'
import type { ProviderSetupResult } from '../../types/setup'

interface VerificationStepProps {
  isLoading: boolean
  result: ProviderSetupResult | null
  error: string | null
}

/**
 * Step 3 — Spinner while the API call runs; success or error state with retry hint.
 */
export function VerificationStep({ isLoading, result, error }: VerificationStepProps) {
  const { t } = useTranslation()

  if (isLoading) {
    return (
      <Box display="flex" flexDirection="column" alignItems="center" gap={2} py={4}>
        <CircularProgress size={48} />
        <Typography variant="body1" color="text.secondary">
          {t('setup.status.configuring')}
        </Typography>
      </Box>
    )
  }

  if (error || (result && !result.success)) {
    const errorMessage = error ?? result?.detail ?? t('setup.status.error')
    return (
      <Box py={2}>
        <Alert severity="error">
          <Typography variant="subtitle2" fontWeight={700}>
            {t('setup.status.error')}
          </Typography>
          <Typography variant="body2" mt={0.5}>
            {errorMessage}
          </Typography>
        </Alert>
      </Box>
    )
  }

  return null
}
