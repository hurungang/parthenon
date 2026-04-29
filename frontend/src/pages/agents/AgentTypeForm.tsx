import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function AgentTypeForm() {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="h5">{t('agents.createType')}</Typography>
    </Box>
  )
}
