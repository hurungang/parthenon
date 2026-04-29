import { useTranslation } from 'react-i18next'
import { Box, TextField, Typography } from '@mui/material'
import type { ProviderSetupRequest } from '../../types/setup'

interface KeycloakConfigStepProps {
  formData: Partial<ProviderSetupRequest>
  onChange: (updates: Partial<ProviderSetupRequest>) => void
}

/**
 * Step 2 (Keycloak) — Configuration form for bundled or external Keycloak.
 */
export function KeycloakConfigStep({ formData, onChange }: KeycloakConfigStepProps) {
  const { t } = useTranslation()

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <Typography variant="subtitle1" fontWeight={600}>
        {t('setup.step.keycloakConfig.label')}
      </Typography>

      <TextField
        fullWidth
        required
        label={t('setup.field.keycloakUrl')}
        value={formData.keycloak_url ?? ''}
        onChange={(e) => onChange({ keycloak_url: e.target.value })}
        placeholder="http://localhost:8080"
      />

      <TextField
        fullWidth
        required
        label={t('setup.field.realm')}
        value={formData.realm_name ?? ''}
        onChange={(e) => onChange({ realm_name: e.target.value })}
        placeholder="parthenon"
      />

      <TextField
        fullWidth
        required
        label={t('setup.field.clientId')}
        value={formData.client_id ?? ''}
        onChange={(e) => onChange({ client_id: e.target.value })}
        placeholder="parthenon-api"
      />

      <TextField
        fullWidth
        required
        label={t('setup.field.adminUser')}
        value={formData.admin_user ?? ''}
        onChange={(e) => onChange({ admin_user: e.target.value })}
        placeholder="admin"
      />

      <TextField
        fullWidth
        required
        type="password"
        label={t('setup.field.adminPassword')}
        value={formData.admin_password ?? ''}
        onChange={(e) => onChange({ admin_password: e.target.value })}
      />

      <TextField
        fullWidth
        required
        type="password"
        label={t('setup.field.initialAdminPassword')}
        value={formData.initial_admin_password ?? ''}
        onChange={(e) => onChange({ initial_admin_password: e.target.value })}
        helperText={t('setup.field.initialAdminPassword')}
      />
    </Box>
  )
}
