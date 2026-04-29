import { Box, Button, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

/**
 * 404 Not Found page.
 */
export function NotFoundPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      height="100vh"
      gap={2}
    >
      <Typography variant="h2" fontWeight={700}>404</Typography>
      <Typography variant="h5">{t('errors.notFound')}</Typography>
      <Typography variant="body1" color="text.secondary">
        {t('errors.notFoundDesc')}
      </Typography>
      <Button variant="contained" onClick={() => navigate('/dashboard')}>
        {t('errors.goHome')}
      </Button>
    </Box>
  )
}
