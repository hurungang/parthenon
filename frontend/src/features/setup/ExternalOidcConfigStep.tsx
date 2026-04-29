import { useTranslation } from 'react-i18next'
import { Box, TextField, Typography } from '@mui/material'
import type { ProviderSetupRequest } from '../../types/setup'

interface ExternalOidcConfigStepProps {
  formData: Partial<ProviderSetupRequest>
  onChange: (updates: Partial<ProviderSetupRequest>) => void
}

/**
 * Step 2 (External OIDC) — Configuration form for external OIDC / Azure EntraID.
 */
export function ExternalOidcConfigStep({ formData, onChange }: ExternalOidcConfigStepProps) {
  const { t } = useTranslation()

  return (
    <Box display="flex" flexDirection="column" gap={2}>
      <Typography variant="subtitle1" fontWeight={600}>
        {t('setup.step.externalOidc.label')}
      </Typography>

      <TextField
        fullWidth
        required
        label={t('setup.field.oidcDiscoveryUrl')}
        value={formData.oidc_discovery_url ?? ''}
        onChange={(e) => onChange({ oidc_discovery_url: e.target.value })}
        placeholder="https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
        helperText={t('setup.field.oidcDiscoveryUrl')}
      />

      <TextField
        fullWidth
        required
        label={t('setup.field.clientId')}
        value={formData.client_id ?? ''}
        onChange={(e) => onChange({ client_id: e.target.value })}
        placeholder="your-client-id"
      />

      <TextField
        fullWidth
        type="password"
        label={t('setup.field.clientSecret')}
        value={formData.client_secret ?? ''}
        onChange={(e) => onChange({ client_secret: e.target.value })}
      />
    </Box>
  )
}
