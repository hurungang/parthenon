import { useTranslation } from 'react-i18next'
import {
  FormControl,
  FormControlLabel,
  FormLabel,
  Radio,
  RadioGroup,
  Typography,
} from '@mui/material'
import { ProviderType } from '../../types/setup'

interface ProviderSelectionStepProps {
  selectedProvider: ProviderType
  onChange: (provider: ProviderType) => void
}

/**
 * Step 1 — Select the identity provider type.
 */
export function ProviderSelectionStep({
  selectedProvider,
  onChange,
}: ProviderSelectionStepProps) {
  const { t } = useTranslation()

  return (
    <FormControl component="fieldset" fullWidth>
      <FormLabel component="legend">
        <Typography variant="subtitle1" fontWeight={600} mb={1}>
          {t('setup.step.providerSelection.label')}
        </Typography>
      </FormLabel>
      <RadioGroup
        value={selectedProvider}
        onChange={(e) => onChange(e.target.value as ProviderType)}
      >
        <FormControlLabel
          value={ProviderType.KEYCLOAK_BUNDLED}
          control={<Radio />}
          label={t('setup.provider.bundledKeycloak')}
        />
        <FormControlLabel
          value={ProviderType.KEYCLOAK_EXTERNAL}
          control={<Radio />}
          label={t('setup.provider.externalKeycloak')}
        />
        <FormControlLabel
          value={ProviderType.AZURE_ENTRAID}
          control={<Radio />}
          label={t('setup.provider.azureEntraId')}
        />
      </RadioGroup>
    </FormControl>
  )
}
