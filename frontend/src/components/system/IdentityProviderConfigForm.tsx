import { useState } from 'react'
import {
  Box,
  Button,
  Collapse,
  FormControl,
  FormControlLabel,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { Visibility, VisibilityOff, ExpandMore, ExpandLess } from '@mui/icons-material'
import { useTranslation } from 'react-i18next'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import type { IdentityProviderConfigItem } from '../../api/systemConfigApi'
import { OIDCTestConfigModal } from './OIDCTestConfigModal'
import { OIDCTestLoginModal } from './OIDCTestLoginModal'

const PROVIDER_TYPES = [
  { value: 'oidc_generic', label: 'Generic OIDC' },
  { value: 'keycloak', label: 'Keycloak' },
  { value: 'azure_entraid', label: 'Azure EntraID' },
]

const DEFAULT_SCOPES: Record<string, string> = {
  user: 'openid profile email',
  agent: 'openid profile email offline_access',
}

interface IdentityProviderConfigFormProps {
  scope: 'user' | 'agent'
  currentConfig?: IdentityProviderConfigItem | null
  onSave: (data: {
    provider_type: string
    display_name: string
    issuer_url: string
    client_id: string
    client_secret?: string
    ui_client_id?: string
    public_client_id?: string
    scopes: string
    claim_mappings?: Record<string, string>
    is_enabled: boolean
  }) => Promise<void>
  disabled?: boolean
}

export function IdentityProviderConfigForm({
  scope,
  currentConfig,
  onSave,
  disabled = false,
}: IdentityProviderConfigFormProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [providerType, setProviderType] = useState(currentConfig?.provider_type ?? 'oidc_generic')
  const [displayName, setDisplayName] = useState(currentConfig?.display_name ?? '')
  const [issuerUrl, setIssuerUrl] = useState(currentConfig?.issuer_url ?? '')
  const [clientId, setClientId] = useState(currentConfig?.client_id ?? '')
  const [clientSecret, setClientSecret] = useState('')
  const [publicClientId, setPublicClientId] = useState(currentConfig?.public_client_id ?? currentConfig?.ui_client_id ?? '')
  const [scopes, _setScopes] = useState(currentConfig?.scopes ?? DEFAULT_SCOPES[scope])
  const [claimsMapping, setClaimsMapping] = useState(
    currentConfig?.claim_mappings
      ? Object.entries(currentConfig.claim_mappings)
          .map(([k, v]) => `${k}:${v}`)
          .join('\n')
      : '',
  )
  const [isEnabled, setIsEnabled] = useState(currentConfig?.is_enabled ?? true)
  const [showSecret, setShowSecret] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  // Test modals
  const [testConfigOpen, setTestConfigOpen] = useState(false)
  const [testLoginOpen, setTestLoginOpen] = useState(false)

  const handleSave = async () => {
    try {
      clearDialogError()
      setSaving(true)

      const claimMappings: Record<string, string> | undefined = claimsMapping.trim()
        ? Object.fromEntries(
            claimsMapping
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean)
              .map((line) => {
                const colonIdx = line.indexOf(':')
                if (colonIdx === -1) return [line.trim(), line.trim()]
                return [line.slice(0, colonIdx).trim(), line.slice(colonIdx + 1).trim()]
              }),
          )
        : undefined

      await onSave({
        provider_type: providerType,
        display_name: displayName || `${scope === 'user' ? 'User' : 'Agent'} Provider`,
        issuer_url: issuerUrl,
        client_id: clientId,
        client_secret: clientSecret || undefined,
        public_client_id: publicClientId || undefined,
        scopes,
        claim_mappings: claimMappings,
        is_enabled: isEnabled,
      })

      // Clear the secret field after save
      setClientSecret('')
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const isConfigured = !!currentConfig

  return (
    <Box>
      {dialogError != null && (
        <Box mb={2}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('systemConfig.identityProviders.saveError')} />
        </Box>
      )}

      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Box display="flex" alignItems="center" gap={1}>
          <Typography variant="h6">
            {t(`systemConfig.identityProviders.${scope === 'user' ? 'userProvider' : 'agentProvider'}`)}
          </Typography>
          <Box
            sx={{
              px: 1,
              py: 0.25,
              borderRadius: 1,
              fontSize: '0.75rem',
              fontWeight: 500,
              bgcolor: isConfigured ? 'success.light' : 'grey.300',
              color: isConfigured ? 'success.contrastText' : 'text.secondary',
            }}
          >
            {t(`systemConfig.identityProviders.${isConfigured ? 'configured' : 'notConfigured'}`)}
          </Box>
        </Box>
        <FormControlLabel
          control={
            <Switch
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
              disabled={disabled}
            />
          }
          label={t('systemConfig.identityProviders.enableToggle')}
        />
      </Box>

      <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={2}>
        <FormControl fullWidth disabled={disabled}>
          <InputLabel>{t('systemConfig.identityProviders.providerType')}</InputLabel>
          <Select
            value={providerType}
            label={t('systemConfig.identityProviders.providerType')}
            onChange={(e) => setProviderType(e.target.value)}
          >
            {PROVIDER_TYPES.map((pt) => (
              <MenuItem key={pt.value} value={pt.value}>
                {pt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField
          label={t('app.name')}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          disabled={disabled}
          placeholder={scope === 'user' ? 'User Provider' : 'Agent Provider'}
        />

        <TextField
          label={t('systemConfig.identityProviders.issuerUrl')}
          value={issuerUrl}
          onChange={(e) => setIssuerUrl(e.target.value)}
          disabled={disabled}
          required
          type="url"
          sx={{ gridColumn: { xs: '1', sm: 'span 2' } }}
        />

        <TextField
          label={t('systemConfig.identityProviders.uiClientId')}
          value={publicClientId}
          onChange={(e) => setPublicClientId(e.target.value)}
          disabled={disabled}
          required
          helperText={t('systemConfig.identityProviders.uiClientIdHint')}
          placeholder="parthenon-api-ui"
        />

        <TextField
          label={t('systemConfig.identityProviders.scopes')}
          value={scopes}
          disabled
          helperText={t('systemConfig.identityProviders.scopesFixedHint')}
          sx={{ gridColumn: { xs: '1', sm: 'span 2' } }}
        />
      </Box>

      {/* Advanced options */}
      <Box mt={2}>
        <Button
          onClick={() => setAdvancedOpen(!advancedOpen)}
          endIcon={advancedOpen ? <ExpandLess /> : <ExpandMore />}
          size="small"
        >
          {t('systemConfig.identityProviders.advancedOptions')}
        </Button>
        <Collapse in={advancedOpen}>
          <Box mt={1} p={2} bgcolor="grey.50" borderRadius={1}>
            <Typography variant="subtitle2" gutterBottom>
              {t('systemConfig.identityProviders.confidentialSection')}
            </Typography>

            <TextField
              label={t('systemConfig.identityProviders.clientId')}
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={disabled}
              size="small"
              fullWidth
              helperText={t('systemConfig.identityProviders.clientIdHint')}
              sx={{ mb: 2 }}
            />

            <TextField
              label={t('systemConfig.identityProviders.clientSecret')}
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              disabled={disabled}
              size="small"
              fullWidth
              type={showSecret ? 'text' : 'password'}
              placeholder={currentConfig?.encrypted_client_secret ? '(configured)' : ''}
              helperText={t('systemConfig.identityProviders.clientSecretHint')}
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton onClick={() => setShowSecret(!showSecret)} edge="end" size="small">
                      {showSecret ? <VisibilityOff /> : <Visibility />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
              sx={{ mb: 2 }}
            />

            <TextField
              label={t('systemConfig.identityProviders.claimsMapping')}
              value={claimsMapping}
              onChange={(e) => setClaimsMapping(e.target.value)}
              disabled={disabled}
              multiline
              minRows={2}
              maxRows={6}
              size="small"
              fullWidth
              placeholder="email:email&#10;name:display_name"
              helperText={t('systemConfig.identityProviders.claimsMappingHint')}
              sx={{ mb: 2 }}
            />
            <Typography variant="caption" color="text.secondary" display="block" mb={1}>
              {t('systemConfig.identityProviders.advancedOptions')} (auto-discovered from issuer)
            </Typography>
            <Box display="grid" gridTemplateColumns={{ xs: '1fr', sm: '1fr 1fr' }} gap={1}>
              <TextField size="small" label={t('systemConfig.identityProviders.authorizationEndpoint')} disabled fullWidth />
              <TextField size="small" label={t('systemConfig.identityProviders.tokenEndpoint')} disabled fullWidth />
              <TextField size="small" label={t('systemConfig.identityProviders.jwksEndpoint')} disabled fullWidth />
              <TextField size="small" label={t('systemConfig.identityProviders.userInfoEndpoint')} disabled fullWidth />
            </Box>
          </Box>
        </Collapse>
      </Box>

      {/* Action buttons */}
      <Box mt={3} display="flex" gap={1}>
        <Button variant="contained" onClick={() => void handleSave()} disabled={disabled || saving}>
          {saving ? t('app.saving') : t('systemConfig.identityProviders.save')}
        </Button>
        <Button
          variant="outlined"
          onClick={() => setTestConfigOpen(true)}
          disabled={disabled || !issuerUrl}
        >
          {t('systemConfig.identityProviders.testConfig')}
        </Button>
        <Button
          variant="outlined"
          onClick={() => setTestLoginOpen(true)}
          disabled={disabled || !issuerUrl || !clientId}
        >
          {t('systemConfig.identityProviders.testLogin')}
        </Button>
      </Box>

      {/* Test modals */}
      <OIDCTestConfigModal
        open={testConfigOpen}
        onClose={() => setTestConfigOpen(false)}
        issuerUrl={issuerUrl}
        clientId={clientId}
      />
      <OIDCTestLoginModal
        open={testLoginOpen}
        onClose={() => setTestLoginOpen(false)}
        issuerUrl={issuerUrl}
        clientId={clientId}
        clientSecret={clientSecret || undefined}
      />
    </Box>
  )
}
