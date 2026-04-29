import { useTranslation } from 'react-i18next'
import { Alert, Box, Button, Typography } from '@mui/material'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'

interface CompletionStepProps {
  onGoToLogin: () => void
}

/**
 * Step 4 — Success confirmation and "Go to Login" button.
 */
export function CompletionStep({ onGoToLogin }: CompletionStepProps) {
  const { t } = useTranslation()

  return (
    <Box display="flex" flexDirection="column" alignItems="center" gap={3} py={4}>
      <CheckCircleOutlineIcon color="success" sx={{ fontSize: 64 }} />
      <Alert severity="success" sx={{ width: '100%' }}>
        <Typography variant="body1">{t('setup.status.success')}</Typography>
      </Alert>
      <Button variant="contained" size="large" onClick={onGoToLogin}>
        {t('setup.action.goToLogin')}
      </Button>
    </Box>
  )
}
