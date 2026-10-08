import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  IconButton,
  Paper,
  Snackbar,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import {
  listSystemOneProviders,
  createSystemOneProvider,
  updateSystemOneProvider,
  deleteSystemOneProvider,
  testSystemOneProviderConnection,
  SYSTEM_ONE_PRESET_BASE_URL,
} from '../../api/systemOneApi'
import type {
  SystemOneProvider,
  SystemOneProviderUpdate,
  SystemOneTestConnectionResult,
} from '../../api/systemOneApi'

interface ProviderFormState {
  display_name: string
  base_url: string
  default_model: string
  enabled: boolean
  enabled_models: string
  /** Write-only: never prefilled from fetched data. */
  api_key: string
}

const EMPTY_FORM: ProviderFormState = {
  display_name: '',
  base_url: SYSTEM_ONE_PRESET_BASE_URL,
  default_model: 'jev-latest',
  enabled: true,
  enabled_models: '',
  api_key: '',
}

function parseEnabledModels(raw: string): string[] | null {
  const models = raw
    .split(',')
    .map((m) => m.trim())
    .filter((m) => m.length > 0)
  return models.length > 0 ? models : null
}

export function SystemOneProviderConfigPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  const [dialogOpen, setDialogOpen] = useState(false)
  const [editing, setEditing] = useState<SystemOneProvider | null>(null)
  const [form, setForm] = useState<ProviderFormState>(EMPTY_FORM)
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    providerId: string
    result: SystemOneTestConnectionResult
  } | null>(null)

  const { data: providers, isLoading, error } = useQuery<SystemOneProvider[]>({
    queryKey: ['system-one', 'providers'],
    queryFn: listSystemOneProviders,
  })

  const openCreate = () => {
    clearDialogError()
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setDialogOpen(true)
  }

  const openEdit = (provider: SystemOneProvider) => {
    clearDialogError()
    setEditing(provider)
    // API key is write-only: NEVER prefilled from fetched data.
    setForm({
      display_name: provider.display_name,
      base_url: provider.base_url,
      default_model: provider.default_model,
      enabled: provider.enabled,
      enabled_models: (provider.enabled_models ?? []).join(', '),
      api_key: '',
    })
    setFormError(null)
    setDialogOpen(true)
  }

  const closeDialog = () => {
    setDialogOpen(false)
    clearDialogError()
  }

  const validate = (): string | null => {
    if (!form.display_name.trim()) return t('systemOne.validation.displayNameRequired')
    if (!form.default_model.trim()) return t('systemOne.validation.defaultModelRequired')
    // API key required on create only; on edit empty means "unchanged".
    if (!editing && !form.api_key) return t('systemOne.validation.apiKeyRequired')
    return null
  }

  const handleSave = async () => {
    const validationError = validate()
    if (validationError) {
      setFormError(validationError)
      return
    }
    try {
      clearDialogError()
      setFormError(null)
      setSaving(true)
      const enabledModels = parseEnabledModels(form.enabled_models)
      if (editing) {
        // Update: only include api_key when the user typed a new one.
        // base_url is preset and not editable.
        const body: SystemOneProviderUpdate = {
          display_name: form.display_name.trim(),
          default_model: form.default_model.trim(),
          enabled: form.enabled,
          enabled_models: enabledModels,
        }
        if (form.api_key) body.api_key = form.api_key
        await updateSystemOneProvider(editing.id, body)
      } else {
        // Create: base_url defaults to the preset server-side; sent read-only.
        const body = {
          display_name: form.display_name.trim(),
          base_url: SYSTEM_ONE_PRESET_BASE_URL,
          default_model: form.default_model.trim(),
          enabled: form.enabled,
          enabled_models: enabledModels,
          api_key: form.api_key,
        }
        await createSystemOneProvider(body)
      }
      await queryClient.invalidateQueries({ queryKey: ['system-one', 'providers'] })
      setDialogOpen(false)
      clearDialogError()
      setSaveSuccessOpen(true)
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (provider: SystemOneProvider) => {
    try {
      clearDialogError()
      setDeletingId(provider.id)
      await deleteSystemOneProvider(provider.id)
      await queryClient.invalidateQueries({ queryKey: ['system-one', 'providers'] })
    } catch (err) {
      setDialogError(err)
    } finally {
      setDeletingId(null)
    }
  }

  const handleTestConnection = async (provider: SystemOneProvider) => {
    try {
      clearDialogError()
      setTestingId(provider.id)
      setTestResult(null)
      const result = await testSystemOneProviderConnection(provider.id)
      setTestResult({ providerId: provider.id, result })
    } catch (err) {
      setDialogError(err)
    } finally {
      setTestingId(null)
    }
  }

  const statusLabel = useMemo(() => {
    const enabled = (providers ?? []).some((p) => p.enabled)
    return enabled
      ? t('systemOne.status.configured')
      : t('systemOne.status.notConfigured')
  }, [providers, t])

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {t('systemOne.title')}
      </Typography>

      {dialogError != null && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        </Alert>
      )}

      {error != null && (
        <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
      )}

      <Box display="flex" alignItems="center" gap={2} mb={2}>
        <Chip
          label={statusLabel}
          color={(providers ?? []).some((p) => p.enabled) ? 'success' : 'default'}
          size="small"
        />
        <Box flexGrow={1} />
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          {t('systemOne.addProvider')}
        </Button>
      </Box>

      {testResult && (
        <Alert
          severity={testResult.result.ok ? 'success' : 'error'}
          sx={{ mb: 2 }}
          onClose={() => setTestResult(null)}
        >
          {testResult.result.ok
            ? t('systemOne.testSuccess', {
                latency: testResult.result.latency_ms ?? '—',
              })
            : t('systemOne.testFailure', { message: testResult.result.message })}
        </Alert>
      )}

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('systemOne.displayName')}</TableCell>
                <TableCell>{t('systemOne.baseUrl')}</TableCell>
                <TableCell>{t('systemOne.defaultModel')}</TableCell>
                <TableCell>{t('systemOne.enabledModels')}</TableCell>
                <TableCell>{t('systemOne.enabled')}</TableCell>
                <TableCell>{t('systemOne.apiKey')}</TableCell>
                <TableCell>{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {(providers ?? []).map((p) => (
                <TableRow key={p.id}>
                  <TableCell>{p.display_name}</TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                      {p.base_url}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <code>{p.default_model}</code>
                  </TableCell>
                  <TableCell>
                    {(p.enabled_models ?? []).join(', ') || '—'}
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={p.enabled ? t('app.yes') : t('app.no')}
                      color={p.enabled ? 'success' : 'default'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    {p.has_api_key ? (
                      <Chip label={t('systemOne.apiKeyStored')} size="small" />
                    ) : (
                      <Chip
                        label={t('systemOne.apiKeyMissing')}
                        size="small"
                        color="warning"
                      />
                    )}
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={0.5}>
                      <Button
                        size="small"
                        disabled={testingId === p.id}
                        onClick={() => void handleTestConnection(p)}
                      >
                        {testingId === p.id ? (
                          <CircularProgress size={16} />
                        ) : (
                          t('systemOne.testConnection')
                        )}
                      </Button>
                      <Tooltip title={t('app.edit')}>
                        <IconButton size="small" onClick={() => openEdit(p)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title={t('app.delete')}>
                        <span>
                          <IconButton
                            size="small"
                            disabled={deletingId === p.id}
                            onClick={() => void handleDelete(p)}
                          >
                            {deletingId === p.id ? (
                              <CircularProgress size={16} />
                            ) : (
                              <DeleteIcon fontSize="small" />
                            )}
                          </IconButton>
                        </span>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
              {(providers ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Typography variant="body2" color="text.secondary">
                      {t('systemOne.noProviders')}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog
        open={dialogOpen}
        onClose={closeDialog}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>
          {editing ? t('systemOne.editProvider') : t('systemOne.addProvider')}
        </DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert
              error={dialogError}
              fallbackMessage={t('app.error')}
            />
          )}
          {formError && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              {formError}
            </Alert>
          )}
          <TextField
            label={t('systemOne.displayName')}
            value={form.display_name}
            onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
            fullWidth
            margin="normal"
            required
          />
          <TextField
            label={t('systemOne.baseUrl')}
            value={form.base_url}
            onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
            fullWidth
            margin="normal"
            required
            disabled
            helperText={t('systemOne.baseUrlPresetHint')}
          />
          <TextField
            label={t('systemOne.defaultModel')}
            value={form.default_model}
            onChange={(e) => setForm((f) => ({ ...f, default_model: e.target.value }))}
            fullWidth
            margin="normal"
            required
          />
          <TextField
            label={t('systemOne.enabledModels')}
            value={form.enabled_models}
            onChange={(e) => setForm((f) => ({ ...f, enabled_models: e.target.value }))}
            fullWidth
            margin="normal"
            helperText={t('systemOne.enabledModelsHint')}
          />
          <TextField
            label={t('systemOne.apiKey')}
            type="password"
            value={form.api_key}
            onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
            fullWidth
            margin="normal"
            required={!editing}
            placeholder={editing ? t('systemOne.apiKeyUnchanged') : '••••'}
            helperText={
              editing
                ? t('systemOne.apiKeyUnchangedHint')
                : t('systemOne.apiKeyWriteOnlyHint')
            }
            autoComplete="new-password"
          />
          <FormControlLabel
            control={
              <Switch
                checked={form.enabled}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
            }
            label={t('systemOne.enabled')}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog}>{t('app.cancel')}</Button>
          <Button
            variant="contained"
            onClick={() => void handleSave()}
            disabled={saving}
          >
            {saving ? <CircularProgress size={20} /> : t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={saveSuccessOpen}
        autoHideDuration={3000}
        onClose={() => setSaveSuccessOpen(false)}
        message={t('systemOne.saveSuccess')}
      />
    </Box>
  )
}
