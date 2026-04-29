import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function SopEditor() {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="h5">{t('sops.editSop')}</Typography>
      <Typography variant="body2" color="text.secondary">{t('sops.reorderHint')}</Typography>
    </Box>
  )
}
