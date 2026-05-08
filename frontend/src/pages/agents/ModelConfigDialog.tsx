import { useEffect, useState } from 'react'
import {
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import type { ModelConfig, ModelProviderType } from '../../types'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'

interface ModelConfigDialogProps {
  open: boolean
  config: ModelConfig | null
  onClose: () => void
  onSaved: () => void
}

const PROVIDERS: { value: ModelProviderType; label: string }[] = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'litellm_proxy', label: 'LiteLLM Proxy' },
  { value: 'azure_openai', label: 'Azure OpenAI' },
]

const API_KEY_PLACEHOLDER = '••••••••••••••••'

export function ModelConfigDialog({ open, config, onClose, onSaved }: ModelConfigDialogProps) {
  const { t } = useTranslation()
  const isEdit = config !== null

  const [displayName, setDisplayName] = useState('')
  const [providerType, setProviderType] = useState<ModelProviderType>('openai')
  const [apiBaseUrl, setApiBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [enabledModels, setEnabledModels] = useState<string[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)

  useEffect(() => {
    if (open) {
      setDisplayName(config?.display_name ?? '')
      setProviderType(config?.provider_type ?? 'openai')
      setApiBaseUrl(config?.api_base_url ?? '')
      setApiKey(config?.has_credentials ? API_KEY_PLACEHOLDER : '')
      setDialogError(null)
      setAvailableModels([])
      setEnabledModels(config?.enabled_models ?? [])
    }
  }, [open, config])

  const handleClose = () => {
    setDialogError(null)
    onClose()
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      setSaving(true)
      const payload: Record<string, unknown> = {
        display_name: displayName,
        provider_type: providerType,
        api_base_url: apiBaseUrl || null,
        enabled_models: enabledModels,
      }
      // Only include api_key if user changed it (not the placeholder)
      if (apiKey && apiKey !== API_KEY_PLACEHOLDER) {
        payload.api_key = apiKey
      }

      if (isEdit) {
        await apiClient.put(`/agents/model-configs/${config!.id}`, payload)
      } else {
        await apiClient.post('/agents/model-configs', payload)
      }
      onSaved()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleFetchModels = async () => {
    if (!isEdit) return
    try {
      setFetchingModels(true)
      const { data } = await apiClient.get<string[]>(`/agents/model-configs/${config!.id}/models`)
      setAvailableModels(data)
    } catch {
      setAvailableModels([])
    } finally {
      setFetchingModels(false)
    }
  }

  const toggleModel = (model: string) => {
    setEnabledModels((prev) =>
      prev.includes(model) ? prev.filter((m) => m !== model) : [...prev, model]
    )
  }

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="lg">
      <DialogTitle>
        {isEdit ? t('agents.modelConfigs.editTitle') : t('agents.modelConfigs.createTitle')}
      </DialogTitle>
      <DialogContent>
        {!!dialogError && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}

        <Box display="flex" flexDirection="column" gap={2} mt={1}>
          <TextField
            label={t('agents.modelConfigs.displayName')}
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            fullWidth
            required
          />

          <FormControl fullWidth>
            <InputLabel>{t('agents.modelConfigs.providerType')}</InputLabel>
            <Select
              value={providerType}
              label={t('agents.modelConfigs.providerType')}
              onChange={(e) => setProviderType(e.target.value as ModelProviderType)}
            >
              {PROVIDERS.map((p) => (
                <MenuItem key={p.value} value={p.value}>{p.label}</MenuItem>
              ))}
            </Select>
          </FormControl>

          <TextField
            label={t('agents.modelConfigs.apiBaseUrl')}
            value={apiBaseUrl}
            onChange={(e) => setApiBaseUrl(e.target.value)}
            fullWidth
            placeholder={
              providerType === 'litellm_proxy'
                ? 'http://litellm-proxy:4000'
                : providerType === 'azure_openai'
                ? 'https://<resource>.openai.azure.com'
                : t('agents.modelConfigs.apiBaseUrlOptional')
            }
          />

          <TextField
            label={t('agents.modelConfigs.apiKey')}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            fullWidth
            helperText={
              isEdit && config?.has_credentials
                ? t('agents.modelConfigs.apiKeySet')
                : isEdit
                ? t('agents.modelConfigs.apiKeyNotSet')
                : undefined
            }
            FormHelperTextProps={{
              sx: { color: isEdit && config?.has_credentials ? 'success.main' : 'text.secondary' },
            }}
          />

          {isEdit && (
            <Box>
              <Box display="flex" alignItems="center" gap={1} mb={1}>
                <Typography variant="subtitle2">{t('agents.modelConfigs.enabledModels')}</Typography>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={fetchingModels ? <CircularProgress size={14} /> : <RefreshIcon />}
                  onClick={() => void handleFetchModels()}
                  disabled={fetchingModels}
                >
                  {t('agents.modelConfigs.fetchModels')}
                </Button>
              </Box>

              {enabledModels.length > 0 && availableModels.length === 0 && (
                <Box display="flex" flexWrap="wrap" gap={0.5} mb={1}>
                  {enabledModels.map((model) => (
                    <Chip key={model} label={model} size="small" variant="outlined" />
                  ))}
                </Box>
              )}

              {availableModels.length > 0 && (
                <>
                  <Divider sx={{ mb: 1 }} />
                  <Typography variant="caption" color="text.secondary" display="block" mb={0.5}>
                    {t('agents.modelConfigs.selectEnabledModels')}
                  </Typography>
                  <Box
                    sx={{
                      maxHeight: 220,
                      overflowY: 'auto',
                      border: 1,
                      borderColor: 'divider',
                      borderRadius: 1,
                      px: 1,
                    }}
                  >
                    {availableModels.map((model) => (
                      <FormControlLabel
                        key={model}
                        control={
                          <Checkbox
                            checked={enabledModels.includes(model)}
                            onChange={() => toggleModel(model)}
                            size="small"
                          />
                        }
                        label={<Typography variant="body2">{model}</Typography>}
                        sx={{ display: 'flex', m: 0 }}
                      />
                    ))}
                  </Box>
                </>
              )}

              {availableModels.length === 0 && !fetchingModels && enabledModels.length === 0 && (
                <Typography variant="caption" color="text.secondary" display="block">
                  {t('agents.modelConfigs.fetchModelsHint')}
                </Typography>
              )}
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>{t('app.cancel')}</Button>
        <Button variant="contained" onClick={() => void handleSave()} disabled={saving || !displayName}>
          {saving ? t('app.loading') : t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
