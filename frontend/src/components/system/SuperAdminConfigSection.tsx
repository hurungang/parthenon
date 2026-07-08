import { Alert, Box, Chip, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { SuperAdminStatusResponse } from '../../api/systemConfigApi'

interface SuperAdminConfigSectionProps {
  status: SuperAdminStatusResponse | null
}

export function SuperAdminConfigSection({
  status,
}: SuperAdminConfigSectionProps) {
  const { t } = useTranslation()

  const isEnabled = status?.is_enabled ?? false
  const envControlled = status?.env_controlled ?? false

  return (
    <Box>
      <Typography variant="h6" mb={2}>
        {t('systemConfig.superAdmin.title')}
      </Typography>

      <Box mb={2} p={2} bgcolor="grey.50" borderRadius={1}>
        <Box display="flex" alignItems="center" gap={1} mb={1}>
          <Typography variant="body2" color="text.secondary">
            {t('systemConfig.superAdmin.statusLabel')}:
          </Typography>
          <Chip
            size="small"
            label={isEnabled ? 'Enabled' : 'Disabled'}
            color={isEnabled ? 'success' : 'error'}
          />
        </Box>
        {!!status && (
          <Typography variant="body2">
            {t('auth.username')}
            {': '}
            <strong>{status.username ?? t('app.noData')}</strong>
          </Typography>
        )}
      </Box>

      {envControlled ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('systemConfig.superAdmin.envControlled')}
        </Alert>
      ) : isEnabled ? (
        <Alert severity="info" sx={{ mb: 2 }}>
          {t('systemConfig.superAdmin.enableDescription')}
        </Alert>
      ) : (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t('systemConfig.superAdmin.disabledByEnv', { envVar: 'PARTHENON_SUPER_ADMIN_ENABLED' })}
        </Alert>
      )}
    </Box>
  )
}
