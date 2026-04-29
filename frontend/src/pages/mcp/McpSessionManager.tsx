import { Box, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

export function McpSessionManager() {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="h6">{t('mcp.sessions')}</Typography>
    </Box>
  )
}
