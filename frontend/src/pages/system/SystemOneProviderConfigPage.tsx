import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
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
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { VendorModelGuardrailPanel } from '../../components/agents/VendorModelGuardrailPanel'
import {
  listSystemOneProviders,
  createSystemOneProvider,
  updateSystemOneProvider,
  deleteSystemOneProvider,
  testSystemOneProviderConnection,
  listDecisionModelHierarchy,
  listSystemOneProviderTypes,
  listVendorModels,
  importVendorModels,
  SYSTEM_ONE_PRESET_BASE_URL,
} from '../../api/systemOneApi'
import type {
  SystemOneProvider,
  SystemOneProviderUpdate,
  SystemOneTestConnectionResult,
  DecisionModelHierarchyEntry,
} from '../../api/systemOneApi'

interface ProviderFormState {
  provider_type: string
  display_name: string
  base_url: string
  default_model: string
  enabled: boolean
  /** Selected enabled models (the chips rendered by the multi-select). */
  enabled_models: string[]
  /** Write-only: never prefilled from fetched data. */
  api_key: string
}

const EMPTY_FORM: ProviderFormState = {
  provider_type: '',
  display_name: '',
  base_url: SYSTEM_ONE_PRESET_BASE_URL,
  default_model: 'jev-latest',
  enabled: true,
  enabled_models: [],
  api_key: '',
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
  const [saveSuccessOpen, setSaveSuccessOpen] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{
    providerId: string
    result: SystemOneTestConnectionResult
  } | null>(null)
  // Confirm-on-delete dialog state (Dialog Error Handling Standard).
  const [deleteTarget, setDeleteTarget] = useState<SystemOneProvider | null>(null)
  const [deleteDialogError, setDeleteDialogError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState(false)
  // Vendor model sync (Dialog Error Handling Standard): per-source error +
  // in-flight flag; models discovered in the edit dialog update the form.
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState<unknown>(null)
  /** Models available for the default-model select (refreshed by sync). */
  const [dialogModels, setDialogModels] = useState<string[]>([])
  // Embedded guardrail section (FIX-20261014-003000): collapsible, fed with
  // decision-scoped data for the selected provider.
  const [guardrailsOpen, setGuardrailsOpen] = useState(false)
  const [guardrailProviderId, setGuardrailProviderId] = useState<string | null>(null)

  const { data: providers, isLoading, error } = useQuery<SystemOneProvider[]>({
    queryKey: ['system-one', 'providers'],
    queryFn: listSystemOneProviders,
  })

  const { data: providerTypes } = useQuery<
    { value: string; label: string }[]
  >({
    queryKey: ['system-one', 'provider-types'],
    queryFn: listSystemOneProviderTypes,
  })

  // Defensive: a non-array payload (e.g. mocked/error response) must not
  // crash the page render — vendor types are only an enrichment.
  const typeOptions = Array.isArray(providerTypes) ? providerTypes : []
  // Form default before the types query resolves (single-vendor today).
  const effectiveFormType =
    form.provider_type || typeOptions[0]?.value || 'typesafe'

  const { data: hierarchy } = useQuery<DecisionModelHierarchyEntry[]>({
    queryKey: ['system-one', 'models'],
    queryFn: listDecisionModelHierarchy,
  })

  const invalidateCatalogue = async () => {
    await queryClient.invalidateQueries({ queryKey: ['system-one', 'providers'] })
    await queryClient.invalidateQueries({ queryKey: ['system-one', 'models'] })
  }

  const hierarchyFor = (providerId: string) =>
    (hierarchy ?? []).find((h) => h.provider_id === providerId)

  /** Options for the enabled-models multi-select: models already selected
   * (chips), models imported via vendor sync in this dialog session, and —
   * in edit mode — the provider's catalogued availability rows. */
  const modelOptions = useMemo(() => {
    const catalogue = editing
      ? (hierarchyFor(editing.id)?.models.map((m) => m.model_name) ?? [])
      : []
    return Array.from(
      new Set([...form.enabled_models, ...dialogModels, ...catalogue]),
    )
  }, [editing, form.enabled_models, dialogModels, hierarchy])

  const openCreate = () => {
    clearDialogError()
    setEditing(null)
    setForm(EMPTY_FORM)
    setFormError(null)
    setSyncError(null)
    setDialogModels([])
    setDialogOpen(true)
  }

  const openEdit = (provider: SystemOneProvider) => {
    clearDialogError()
    setEditing(provider)
    // API key is write-only: NEVER prefilled from fetched data.
    setForm({
      provider_type: provider.provider_type,
      display_name: provider.display_name,
      base_url: provider.base_url,
      default_model: provider.default_model,
      enabled: provider.enabled,
      enabled_models: provider.enabled_models ?? [],
      api_key: '',
    })
    setFormError(null)
    setSyncError(null)
    // Gate the default-model select on the provider's ENABLED models —
    // not the full hierarchy catalogue.
    setDialogModels(provider.enabled_models ?? [])
    setDialogOpen(true)
  }

  const closeDialog = () => {
    setDialogOpen(false)
    clearDialogError()
  }

  const validate = (): string | null => {
    if (!effectiveFormType) return t('systemOne.validation.providerTypeRequired')
    if (!form.display_name.trim()) return t('systemOne.validation.displayNameRequired')
    if (!form.base_url.trim()) return t('systemOne.validation.baseUrlRequired')
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
      const enabledModels =
        form.enabled_models.length > 0 ? form.enabled_models : null
      if (editing) {
        // Update: only include api_key when the user typed a new one.
        // base_url is editable per tenant (each tenant has its own deployment).
        const body: SystemOneProviderUpdate = {
          display_name: form.display_name.trim(),
          base_url: form.base_url.trim(),
          default_model: form.default_model.trim(),
          enabled: form.enabled,
          enabled_models: enabledModels,
        }
        if (form.api_key) body.api_key = form.api_key
        await updateSystemOneProvider(editing.id, body)
      } else {
        // Create: base_url defaults to the preset in the form; sent explicitly.
        const body = {
          provider_type: effectiveFormType,
          display_name: form.display_name.trim(),
          base_url: form.base_url.trim(),
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
    void invalidateCatalogue()
  }

  const openDeleteDialog = (provider: SystemOneProvider) => {
    setDeleteDialogError(null)
    setDeleteTarget(provider)
  }

  const closeDeleteDialog = () => {
    setDeleteTarget(null)
    setDeleteDialogError(null)
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    try {
      setDeleteDialogError(null)
      setDeleting(true)
      await deleteSystemOneProvider(deleteTarget.id)
      await invalidateCatalogue()
      closeDeleteDialog()
    } catch (err) {
      setDeleteDialogError(err)
    } finally {
      setDeleting(false)
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

  /**
   * Sync models from the vendor: discover via the OpenAI-compatible
   * /models endpoint and import the ids as availability rows (enabled by
   * default). Failures surface in-dialog / in-panel; manual entry stays
   * available as the fallback. When called from the edit dialog the
   * default-model select is refreshed afterwards.
   */
  const handleSyncModels = async (provider: SystemOneProvider) => {
    try {
      setSyncError(null)
      setSyncing(true)
      const { models } = await listVendorModels(provider.id)
      if (models.length === 0) {
        setSyncError(new Error(t('systemOne.syncEmpty')))
        return
      }
      await importVendorModels(provider.id, models)
      await invalidateCatalogue()
      if (editing?.id === provider.id) {
        setDialogModels(models)
        setForm((f) => ({
          ...f,
          // Imported models become enabled: pre-select them in the
          // enabled-models multi-select so the default-model select
          // stays in sync.
          enabled_models: Array.from(new Set([...f.enabled_models, ...models])),
          // Keep a still-valid default; otherwise fall back to the first
          // imported model so the select never goes stale.
          default_model: models.includes(f.default_model)
            ? f.default_model
            : (models[0] ?? f.default_model),
        }))
      }
    } catch (err) {
      setSyncError(err)
    } finally {
      setSyncing(false)
    }
  }

  const statusLabel = useMemo(() => {
    const enabled = (providers ?? []).some((p) => p.enabled)
    return enabled
      ? t('systemOne.status.configured')
      : t('systemOne.status.notConfigured')
  }, [providers, t])

  /** Provider whose guardrails are shown (explicit selection, else first). */
  const effectiveGuardrailProviderId =
    guardrailProviderId ??
    ((providers ?? [])[0]?.id as string | undefined) ??
    null

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

      {/* Guardrail management embedded in this module (FIX-20261014-003000):
          reuses VendorModelGuardrailPanel fed with decision-scoped data —
          guardrails created here are evaluated by the decision pre-call
          check. LLM guardrails (Model Configurations page) are untouched. */}
      <Paper variant="outlined" sx={{ mb: 2 }}>
        <Box
          display="flex"
          alignItems="center"
          gap={1}
          px={2}
          py={1.5}
          sx={{ cursor: 'pointer' }}
          onClick={() => setGuardrailsOpen((v) => !v)}
          data-testid="guardrails-section-toggle"
        >
          <IconButton size="small" aria-label={t('systemOne.guardrailsToggle')}>
            {guardrailsOpen ? (
              <ExpandLessIcon fontSize="small" />
            ) : (
              <ExpandMoreIcon fontSize="small" />
            )}
          </IconButton>
          <Typography variant="subtitle1" fontWeight={600}>
            {t('systemOne.guardrailsTitle')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('systemOne.guardrailsSubtitle')}
          </Typography>
          <Box flexGrow={1} />
        </Box>
        {guardrailsOpen && (
          <Box px={2} pb={2} data-testid="guardrails-section">
            {(providers ?? []).length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('systemOne.noProviders')}
              </Typography>
            ) : (
              <>
                <TextField
                  select
                  SelectProps={{ native: true }}
                  label={t('systemOne.guardrailsProviderLabel')}
                  value={effectiveGuardrailProviderId ?? ''}
                  onChange={(e) => setGuardrailProviderId(e.target.value)}
                  size="small"
                  sx={{ minWidth: 260, mb: 2 }}
                >
                  {(providers ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.display_name}
                    </option>
                  ))}
                </TextField>
                {effectiveGuardrailProviderId != null && (
                  <VendorModelGuardrailPanel
                    decisionProviderId={effectiveGuardrailProviderId}
                  />
                )}
              </>
            )}
          </Box>
        )}
      </Paper>

      {isLoading ? (
        <CircularProgress />
      ) : (
        <TableContainer component={Paper}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('systemOne.displayName')}</TableCell>
                <TableCell>{t('systemOne.vendorType')}</TableCell>
                <TableCell>{t('systemOne.baseUrl')}</TableCell>
                <TableCell>{t('systemOne.defaultModel')}</TableCell>
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
                    <Chip
                      label={p.provider_type}
                      size="small"
                      variant="outlined"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                      {p.base_url}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <code>{p.default_model}</code>
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
                        <IconButton size="small" onClick={() => openDeleteDialog(p)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
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
          {syncError != null && (
            <Alert severity="error" sx={{ mt: 1 }} onClose={() => setSyncError(null)}>
              <PermissionDeniedAlert
                error={syncError}
                fallbackMessage={t('app.error')}
              />
            </Alert>
          )}
          {formError && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              {formError}
            </Alert>
          )}
          <TextField
            select
            SelectProps={{ native: true }}
            label={t('systemOne.vendorType')}
            value={effectiveFormType}
            onChange={(e) => setForm((f) => ({ ...f, provider_type: e.target.value }))}
            fullWidth
            margin="normal"
            required
            // Vendor type is locked on edit: changing it would invalidate the
            // provider's models and credentials.
            disabled={!!editing}
            helperText={
              editing
                ? t('systemOne.providerTypeLockedHint')
                : t('systemOne.providerTypeHint')
            }
          >
            {typeOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </TextField>
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
            placeholder={SYSTEM_ONE_PRESET_BASE_URL}
            helperText={t('systemOne.baseUrlHint')}
          />
          {/* Enabled models multi-select — chips ARE the enabled models
              sent in the payload; typed entries still allowed (freeSolo). */}
          <Autocomplete
            multiple
            freeSolo
            options={modelOptions}
            value={form.enabled_models}
            onChange={(_, v) => {
              const selected = (v as (string | undefined)[]).filter(
                (m): m is string => typeof m === 'string' && m.length > 0,
              )
              setForm((f) => ({
                ...f,
                enabled_models: selected,
                // Never leave a stale default: prune when the previous
                // default is no longer among the selected models.
                default_model: selected.includes(f.default_model)
                  ? f.default_model
                  : '',
              }))
            }}
            renderInput={(params) => (
              <TextField
                {...params}
                label={t('systemOne.enabledModels')}
                margin="normal"
                helperText={t('systemOne.enabledModelsSelectHint')}
              />
            )}
          />
          <TextField
            select
            SelectProps={{ native: true }}
            label={t('systemOne.defaultModel')}
            value={form.enabled_models.includes(form.default_model)
              ? form.default_model
              : ''}
            onChange={(e) => setForm((f) => ({ ...f, default_model: e.target.value }))}
            fullWidth
            margin="normal"
            required
            // Gated on the enabled-models chips: with none selected there is
            // nothing valid to pick — the user must select/sync first.
            disabled={form.enabled_models.length === 0}
            helperText={
              form.enabled_models.length === 0
                ? t('systemOne.defaultModelSyncFirst')
                : t('systemOne.defaultModelHint')
            }
          >
            {/* Blank entry so the cleared state is representable when the
                current default is no longer among the enabled models. */}
            {!form.enabled_models.includes(form.default_model) && (
              <option value=""></option>
            )}
            {form.enabled_models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </TextField>
          <Box display="flex" justifyContent="flex-end" sx={{ mt: -0.5 }}>
            <Button
              size="small"
              disabled={syncing}
              startIcon={syncing ? <CircularProgress size={16} /> : undefined}
              onClick={() => {
                if (editing) void handleSyncModels(editing)
              }}
            >
              {t('systemOne.syncModels')}
            </Button>
          </Box>
          <Box>
            <TextField
              label={t('systemOne.apiKey')}
              type="password"
              value={form.api_key}
              onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
              fullWidth
              margin="normal"
              required={!editing}
              placeholder={
                editing && editing.has_api_key
                  ? t('systemOne.apiKeySavedPlaceholder')
                  : '••••'
              }
              helperText={
                editing
                  ? t('systemOne.apiKeyUnchangedHint')
                  : t('systemOne.apiKeyWriteOnlyHint')
              }
              autoComplete="new-password"
            />
            {editing && editing.has_api_key && (
              <Chip
                label={t('systemOne.apiKeyConfigured')}
                color="success"
                size="small"
                sx={{ mt: -1 }}
              />
            )}
          </Box>
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

      <Dialog open={deleteTarget !== null} onClose={closeDeleteDialog}>
        <DialogTitle>{t('systemOne.deleteProviderTitle')}</DialogTitle>
        <DialogContent>
          {deleteDialogError != null && (
            <PermissionDeniedAlert
              error={deleteDialogError}
              fallbackMessage={t('app.error')}
            />
          )}
          <DialogContentText>
            {t('systemOne.deleteProviderConfirm', {
              name: deleteTarget?.display_name ?? '',
            })}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDeleteDialog}>{t('app.cancel')}</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => void handleDelete()}
            disabled={deleting}
          >
            {deleting ? <CircularProgress size={20} /> : t('app.delete')}
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
