import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function DashboardPage() {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('nav.dashboard')}
      </Typography>
      <Typography variant="body1" color="text.secondary">
        {t('app.tagline')}
      </Typography>
    </Box>
  )
}
