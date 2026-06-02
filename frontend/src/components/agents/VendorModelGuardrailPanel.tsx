import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Stack,
  Switch,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { type ReactNode, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  useModelAvailability,
  useSetModelDisabled,
  useSetVendorDisabled,
} from '../../hooks/useModelAvailability'
import {
  useDeleteModelUsageLimit,
  useUpdateModelUsageLimit,
} from '../../hooks/useModelUsageGuardrailMutations'
import { useModelUsagePosture } from '../../hooks/useModelUsagePosture'
import { useAvailableModels } from '../../hooks/useAvailableModels'
import type {
  ModelAvailabilityEntry,
  ModelAvailabilityHierarchy,
  ModelUsageGuardrailLimit,
  ModelUsagePosture,
  ModelUsagePostureState,
  VendorAvailabilityNode,
} from '../../types'
import { AddGuardrailForm } from './AddGuardrailForm'

interface VendorModelGuardrailPanelProps {
  /** Optional override: the hierarchy payload (for tests). */
  hierarchy?: ModelAvailabilityHierarchy
  /** Optional override: posture data (for tests). */
  posture?: ModelUsagePosture[]
  /** Optional override: refetch interval for the availability query. */
  refetchInterval?: number
  /**
   * When true, the panel renders as a read-only dashboard:
   * - all enable/disable switches, edit buttons, and remove buttons
   *   are hidden
   * - the per-model "Add guardrail" form is not shown
   * - vendor and model accordions auto-expand on first load
   * - a summary card is rendered above the hierarchy
   *
   * Used by surfaces that observe guardrail state without the
   * intent to mutate (e.g. the runtime control dashboard).
   */
  readonly?: boolean
}

function postureColor(
  state: ModelUsagePostureState | null,
): 'default' | 'warning' | 'error' | 'success' {
  if (state === 'breached') return 'error'
  if (state === 'approaching_limit') return 'warning'
  if (state === 'within_limit') return 'success'
  return 'default'
}

function modelChipColor(
  model: ModelAvailabilityEntry,
  vendorDisabled: boolean,
): { label: string; color: 'default' | 'warning' | 'error' | 'success' } {
  if (vendorDisabled) {
    return {
      label: 'disabled_vendor_cascade',
      color: 'warning',
    }
  }
  if (model.is_disabled) {
    return { label: 'disabled_manual', color: 'error' }
  }
  return { label: 'enabled', color: 'success' }
}

/**
 * Hierarchy-aware panel rendering vendor rows → model rows → guardrail rows.
 *
 * - Vendor row: name, enabled-model count, vendor enable/disable switch.
 * - Model row: name, status chip (enabled / disabled / vendor-cascaded),
 *   per-model enable/disable switch, inline "Add guardrail" form.
 * - Guardrail row: period, limit + unit, posture chip, per-guardrail
 *   enable/disable switch, remove button.
 */
export function VendorModelGuardrailPanel({
  hierarchy: hierarchyOverride,
  posture: postureOverride,
  readonly = false,
}: VendorModelGuardrailPanelProps): ReactNode {
  const { t } = useTranslation()
  const {
    dialogError: hierarchyError,
    setDialogError: setHierarchyError,
    clearDialogError: clearHierarchyError,
  } = useDialogErrorHandler()
  const {
    dialogError: vendorError,
    setDialogError: setVendorError,
    clearDialogError: clearVendorError,
  } = useDialogErrorHandler()
  const {
    dialogError: modelError,
    setDialogError: setModelError,
    clearDialogError: clearModelError,
  } = useDialogErrorHandler()
  const {
    dialogError: guardrailError,
    setDialogError: setGuardrailError,
    clearDialogError: clearGuardrailError,
  } = useDialogErrorHandler()

  const availabilityQuery = useModelAvailability()
  const postureQuery = useModelUsagePosture()
  const setVendorMutation = useSetVendorDisabled()
  const setModelMutation = useSetModelDisabled()
  const updateGuardrail = useUpdateModelUsageLimit()
  const deleteGuardrail = useDeleteModelUsageLimit()
  const { data: availableModels = [] } = useAvailableModels()

  const hierarchy = hierarchyOverride ?? availabilityQuery.data ?? []
  const posture = postureOverride ?? postureQuery.data ?? []
  const isLoading = availabilityQuery.isLoading && !hierarchyOverride

  const postureByGuardrailId = useMemo(() => {
    const m = new Map<string, ModelUsagePosture>()
    for (const p of posture) {
      m.set(p.model_guardrail_configuration_id, p)
    }
    return m
  }, [posture])

  const summary = useMemo(() => {
    const vendorTotal = hierarchy.length
    const vendorEnabled = hierarchy.filter((v) => !v.is_disabled).length
    let modelTotal = 0
    let modelEnabled = 0
    let guardrailTotal = 0
    let guardrailActive = 0
    let guardrailBreached = 0
    for (const vendor of hierarchy) {
      for (const model of vendor.models) {
        modelTotal += 1
        if (!model.is_disabled && !vendor.is_disabled) {
          modelEnabled += 1
        }
        for (const guardrail of model.guardrails) {
          guardrailTotal += 1
          if (guardrail.is_active) {
            guardrailActive += 1
          }
          const p = postureByGuardrailId.get(guardrail.id)
          if (p?.posture_state === 'breached') {
            guardrailBreached += 1
          }
        }
      }
    }
    return {
      vendorTotal,
      vendorEnabled,
      modelTotal,
      modelEnabled,
      guardrailTotal,
      guardrailActive,
      guardrailBreached,
    }
  }, [hierarchy, postureByGuardrailId])

  if (isLoading) {
    return (
      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="body2" color="text.secondary">
          {t('app.loading')}
        </Typography>
      </Paper>
    )
  }

  if (hierarchyError != null) {
    return (
      <Paper sx={{ p: 2, mb: 3 }}>
        <PermissionDeniedAlert
          error={hierarchyError}
          fallbackMessage={t('app.error')}
        />
        <Button onClick={() => void availabilityQuery.refetch()}>
          {t('app.refresh')}
        </Button>
      </Paper>
    )
  }

  return (
    <Paper sx={{ p: 2, mb: 3 }} data-testid="vendor-model-guardrail-panel">
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
        <Typography variant="h6" fontWeight={700}>
          {readonly
            ? t('agents.sessions.modelUsageDashboardTitle')
            : t('agents.sessions.modelUsageHierarchyTitle')}
        </Typography>
        <Button
          variant="outlined"
          size="small"
          onClick={() => void availabilityQuery.refetch()}
        >
          {t('app.refresh')}
        </Button>
      </Box>
      <Typography variant="body2" color="text.secondary" mb={2}>
        {readonly
          ? t('agents.sessions.modelUsageDashboardSubtitle')
          : t('agents.sessions.modelUsageHierarchySubtitle')}
      </Typography>

      {readonly && (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, 1fr)' },
            gap: 1.5,
            mb: 2,
          }}
          data-testid="guardrail-dashboard-summary"
        >
          <SummaryTile
            label={t('agents.sessions.modelUsageDashboardVendors')}
            value={`${summary.vendorEnabled} / ${summary.vendorTotal}`}
            tone={summary.vendorEnabled === summary.vendorTotal ? 'ok' : 'warn'}
            testId="summary-vendors"
          />
          <SummaryTile
            label={t('agents.sessions.modelUsageDashboardModels')}
            value={`${summary.modelEnabled} / ${summary.modelTotal}`}
            tone={summary.modelEnabled === summary.modelTotal ? 'ok' : 'warn'}
            testId="summary-models"
          />
          <SummaryTile
            label={t('agents.sessions.modelUsageDashboardGuardrailsActive')}
            value={`${summary.guardrailActive} / ${summary.guardrailTotal}`}
            tone={
              summary.guardrailActive === summary.guardrailTotal ? 'ok' : 'neutral'
            }
            testId="summary-guardrails-active"
          />
          <SummaryTile
            label={t('agents.sessions.modelUsageDashboardGuardrailsBreached')}
            value={String(summary.guardrailBreached)}
            tone={summary.guardrailBreached > 0 ? 'error' : 'ok'}
            testId="summary-guardrails-breached"
          />
        </Box>
      )}

      {hierarchy.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.modelUsageHierarchyEmpty')}
        </Typography>
      ) : (
        <Stack spacing={1.5}>
          {hierarchy.map((vendor) => (
            <VendorRow
              key={vendor.vendor_config_id}
              vendor={vendor}
              postureByGuardrailId={postureByGuardrailId}
              availableModels={availableModels}
              vendorError={vendorError}
              onVendorError={setVendorError}
              clearVendorError={clearVendorError}
              setVendorMutation={setVendorMutation}
              modelError={modelError}
              onModelError={setModelError}
              clearModelError={clearModelError}
              setModelMutation={setModelMutation}
              guardrailError={guardrailError}
              onGuardrailError={setGuardrailError}
              clearGuardrailError={clearGuardrailError}
              updateGuardrail={updateGuardrail}
              deleteGuardrail={deleteGuardrail}
              onHierarchyError={setHierarchyError}
              clearHierarchyError={clearHierarchyError}
              readonly={readonly}
              defaultExpanded={readonly}
            />
          ))}
        </Stack>
      )}
    </Paper>
  )
}

interface SummaryTileProps {
  label: string
  value: string
  tone: 'ok' | 'warn' | 'error' | 'neutral'
  testId?: string
}

function SummaryTile({ label, value, tone, testId }: SummaryTileProps): ReactNode {
  const toneColor: Record<SummaryTileProps['tone'], 'success' | 'warning' | 'error' | 'default'> = {
    ok: 'success',
    warn: 'warning',
    error: 'error',
    neutral: 'default',
  }
  return (
    <Paper
      variant="outlined"
      sx={{ p: 1.5 }}
      data-testid={testId}
    >
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="h6" fontWeight={700} color={`${toneColor[tone]}.main`}>
        {value}
      </Typography>
    </Paper>
  )
}

interface VendorRowProps {
  vendor: VendorAvailabilityNode
  postureByGuardrailId: Map<string, ModelUsagePosture>
  availableModels: ReturnType<typeof useAvailableModels>['data'] extends infer T
    ? NonNullable<T>
    : never
  vendorError: unknown
  onVendorError: (err: unknown) => void
  clearVendorError: () => void
  setVendorMutation: ReturnType<typeof useSetVendorDisabled>
  modelError: unknown
  onModelError: (err: unknown) => void
  clearModelError: () => void
  setModelMutation: ReturnType<typeof useSetModelDisabled>
  guardrailError: unknown
  onGuardrailError: (err: unknown) => void
  clearGuardrailError: () => void
  updateGuardrail: ReturnType<typeof useUpdateModelUsageLimit>
  deleteGuardrail: ReturnType<typeof useDeleteModelUsageLimit>
  onHierarchyError: (err: unknown) => void
  clearHierarchyError: () => void
  readonly: boolean
  defaultExpanded: boolean
}

function VendorRow({
  vendor,
  postureByGuardrailId,
  availableModels,
  vendorError,
  onVendorError,
  clearVendorError,
  setVendorMutation,
  modelError,
  onModelError,
  clearModelError,
  setModelMutation,
  guardrailError,
  onGuardrailError,
  clearGuardrailError,
  updateGuardrail,
  deleteGuardrail,
  readonly,
  defaultExpanded,
}: VendorRowProps): ReactNode {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded)
  const enabledModelCount = vendor.models.filter(
    (m) => !m.is_disabled && !vendor.is_disabled,
  ).length

  const handleVendorToggle = async (next: boolean) => {
    try {
      clearVendorError()
      await setVendorMutation.mutateAsync({
        configId: vendor.vendor_config_id,
        is_disabled: !next,
      })
    } catch (err) {
      onVendorError(err)
    }
  }

  return (
    <Accordion
      expanded={expanded}
      onChange={(_, isExp) => setExpanded(isExp)}
      data-testid={`vendor-row-${vendor.vendor_config_id}`}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack
          direction="row"
          spacing={2}
          alignItems="center"
          sx={{ width: '100%' }}
        >
          <Box sx={{ flex: 1 }}>
            <Typography variant="subtitle1" fontWeight={600}>
              {vendor.vendor_display_name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t('agents.sessions.modelUsageVendorEnabledCount', {
                count: enabledModelCount,
                total: vendor.models.length,
              })}
            </Typography>
          </Box>
          <Chip
            size="small"
            label={
              vendor.is_disabled
                ? t('agents.sessions.modelUsageVendorDisabled')
                : t('agents.sessions.modelUsageVendorEnabled')
            }
            color={vendor.is_disabled ? 'warning' : 'success'}
            variant="outlined"
          />
          {!readonly && (
            <FormControlLabelSwitch
              checked={!vendor.is_disabled}
              disabled={setVendorMutation.isPending}
              onChange={(next) => void handleVendorToggle(next)}
              label={t('agents.sessions.modelUsageVendorEnabled')}
              testId={`vendor-switch-${vendor.vendor_config_id}`}
            />
          )}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        {vendorError != null && (
          <Box mb={1}>
            <PermissionDeniedAlert
              error={vendorError}
              fallbackMessage={t('app.error')}
            />
          </Box>
        )}
        {vendor.models.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            {t('agents.sessions.modelUsageHierarchyVendorNoModels')}
          </Typography>
        ) : (
          <Stack spacing={1}>
            {vendor.models.map((model) => (
              <ModelRow
                key={`${vendor.vendor_config_id}:${model.model_name}`}
                model={model}
                vendor={vendor}
                postureByGuardrailId={postureByGuardrailId}
                availableModels={availableModels}
                modelError={modelError}
                onModelError={onModelError}
                clearModelError={clearModelError}
                setModelMutation={setModelMutation}
                guardrailError={guardrailError}
                onGuardrailError={onGuardrailError}
                clearGuardrailError={clearGuardrailError}
                updateGuardrail={updateGuardrail}
                deleteGuardrail={deleteGuardrail}
                readonly={readonly}
                defaultExpanded={defaultExpanded}
              />
            ))}
          </Stack>
        )}
      </AccordionDetails>
    </Accordion>
  )
}

interface ModelRowProps {
  model: ModelAvailabilityEntry
  vendor: VendorAvailabilityNode
  postureByGuardrailId: Map<string, ModelUsagePosture>
  availableModels: NonNullable<ReturnType<typeof useAvailableModels>['data']>
  modelError: unknown
  onModelError: (err: unknown) => void
  clearModelError: () => void
  setModelMutation: ReturnType<typeof useSetModelDisabled>
  guardrailError: unknown
  onGuardrailError: (err: unknown) => void
  clearGuardrailError: () => void
  updateGuardrail: ReturnType<typeof useUpdateModelUsageLimit>
  deleteGuardrail: ReturnType<typeof useDeleteModelUsageLimit>
  readonly: boolean
  defaultExpanded: boolean
}

function ModelRow({
  model,
  vendor,
  postureByGuardrailId,
  availableModels,
  modelError,
  onModelError,
  clearModelError,
  setModelMutation,
  guardrailError,
  onGuardrailError,
  clearGuardrailError,
  updateGuardrail,
  deleteGuardrail,
  readonly,
  defaultExpanded,
}: ModelRowProps): ReactNode {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState<boolean>(defaultExpanded)
  const [showAddForm, setShowAddForm] = useState<boolean>(false)
  const [editingGuardrailId, setEditingGuardrailId] = useState<string | null>(null)
  const chip = modelChipColor(model, vendor.is_disabled)

  const handleModelToggle = async (next: boolean) => {
    try {
      clearModelError()
      await setModelMutation.mutateAsync({
        configId: vendor.vendor_config_id,
        modelName: model.model_name,
        is_disabled: !next,
      })
    } catch (err) {
      onModelError(err)
    }
  }

  return (
    <Paper
      variant="outlined"
      sx={{ p: 1 }}
      data-testid={`model-row-${vendor.vendor_config_id}:${model.model_name}`}
    >
      <Stack direction="row" spacing={2} alignItems="center">
        <IconButton
          size="small"
          onClick={() => setExpanded((v) => !v)}
          aria-label={t('agents.sessions.modelUsageModelExpand')}
          data-testid={`model-expand-${vendor.vendor_config_id}:${model.model_name}`}
        >
          <ExpandMoreIcon
            fontSize="small"
            sx={{ transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)' }}
          />
        </IconButton>
        <Box sx={{ flex: 1 }}>
          <Typography variant="body2" fontWeight={600}>
            {model.model_name}
          </Typography>
          <Stack direction="row" spacing={0.5} alignItems="center" mt={0.25}>
            <Chip
              size="small"
              color={chip.color}
              label={t(`agents.sessions.modelUsageModelState.${chip.label}`)}
              data-testid={`model-chip-${vendor.vendor_config_id}:${model.model_name}`}
            />
            {chip.label === 'disabled_vendor_cascade' && (
              <Chip
                size="small"
                color="warning"
                variant="outlined"
                label={t('agents.sessions.modelUsageModelCascadedFromVendor')}
              />
            )}
            <Typography variant="caption" color="text.secondary">
              {t('agents.sessions.modelUsageModelGuardrailCount', {
                count: model.guardrails.length,
              })}
            </Typography>
          </Stack>
        </Box>
        {!readonly && (
          <FormControlLabelSwitch
            checked={!model.is_disabled}
            disabled={
              setModelMutation.isPending ||
              (vendor.is_disabled && model.is_disabled)
            }
            onChange={(next) => void handleModelToggle(next)}
            label={t('agents.sessions.modelUsageModelEnabled')}
            testId={`model-switch-${vendor.vendor_config_id}:${model.model_name}`}
          />
        )}
      </Stack>
      {modelError != null && (
        <Box mt={1}>
          <PermissionDeniedAlert
            error={modelError}
            fallbackMessage={t('app.error')}
          />
        </Box>
      )}
      {expanded && (
        <Box mt={1.5} pl={5}>
          <Stack spacing={1}>
            {model.guardrails.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('agents.sessions.modelUsageModelNoGuardrails')}
              </Typography>
            ) : (
              model.guardrails.map((g) => (
                <Box key={g.id}>
                  <GuardrailRow
                    guardrail={g}
                    posture={postureByGuardrailId.get(g.id) ?? null}
                    guardrailError={guardrailError}
                    onGuardrailError={onGuardrailError}
                    clearGuardrailError={clearGuardrailError}
                    updateGuardrail={updateGuardrail}
                    deleteGuardrail={deleteGuardrail}
                    isEditing={editingGuardrailId === g.id}
                    onEdit={() => setEditingGuardrailId(g.id)}
                    onCancelEdit={() => setEditingGuardrailId(null)}
                    readonly={readonly}
                  />
                  {editingGuardrailId === g.id && (
                    <AddGuardrailForm
                      model={model}
                      vendorConfigId={vendor.vendor_config_id}
                      vendorDisplayName={vendor.vendor_display_name}
                      availableModels={availableModels}
                      existing={g}
                      onSaved={() => setEditingGuardrailId(null)}
                      onCancel={() => setEditingGuardrailId(null)}
                    />
                  )}
                </Box>
              ))
            )}
            {!readonly && !showAddForm && (
              <Box>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setShowAddForm(true)}
                  data-testid={`add-guardrail-button-${vendor.vendor_config_id}:${model.model_name}`}
                >
                  {t('agents.sessions.modelUsageAddGuardrail')}
                </Button>
              </Box>
            )}
            {!readonly && showAddForm && (
              <AddGuardrailForm
                model={model}
                vendorConfigId={vendor.vendor_config_id}
                vendorDisplayName={vendor.vendor_display_name}
                availableModels={availableModels}
                onSaved={() => setShowAddForm(false)}
                onCancel={() => setShowAddForm(false)}
              />
            )}
          </Stack>
        </Box>
      )}
    </Paper>
  )
}

interface GuardrailRowProps {
  guardrail: ModelUsageGuardrailLimit
  posture: ModelUsagePosture | null
  guardrailError: unknown
  onGuardrailError: (err: unknown) => void
  clearGuardrailError: () => void
  updateGuardrail: ReturnType<typeof useUpdateModelUsageLimit>
  deleteGuardrail: ReturnType<typeof useDeleteModelUsageLimit>
  isEditing: boolean
  onEdit: () => void
  onCancelEdit: () => void
  readonly: boolean
}

function GuardrailRow({
  guardrail,
  posture,
  guardrailError,
  onGuardrailError,
  clearGuardrailError,
  updateGuardrail,
  deleteGuardrail,
  isEditing,
  onEdit,
  readonly,
}: GuardrailRowProps): ReactNode {
  const { t } = useTranslation()
  const handleActiveToggle = async (next: boolean) => {
    try {
      clearGuardrailError()
      await updateGuardrail.mutateAsync({
        limitId: guardrail.id,
        payload: { is_active: next },
      })
    } catch (err) {
      onGuardrailError(err)
    }
  }
  const handleRemove = async () => {
    try {
      clearGuardrailError()
      await deleteGuardrail.mutateAsync(guardrail.id)
    } catch (err) {
      onGuardrailError(err)
    }
  }

  return (
    <Paper
      variant="outlined"
      sx={{ p: 1 }}
      data-testid={`guardrail-row-${guardrail.id}`}
    >
      <Stack direction="row" spacing={2} alignItems="center">
        <Box sx={{ flex: 1 }}>
          <Typography variant="body2" fontWeight={500}>
            {t('agents.sessions.modelUsageGuardrailPeriod', { period: guardrail.period })}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('agents.sessions.modelUsageGuardrailLimitValue', {
              value: posture?.usage_value ?? 0,
              limit: guardrail.limit_value,
              unit: guardrail.unit,
            })}
          </Typography>
        </Box>
        <Chip
          size="small"
          color={postureColor(posture?.posture_state ?? null)}
          label={
            posture
              ? t(`agents.sessions.modelUsageState.${posture.posture_state}`)
              : t('agents.sessions.modelUsageGuardrailNoPosture')
          }
        />
        <Chip
          size="small"
          variant="outlined"
          label={t(`agents.sessions.modelUsageGuardrailPosture.${guardrail.enforcement_posture}`)}
        />
        {!readonly && (
          <>
            <FormControlLabelSwitch
              checked={guardrail.is_active}
              disabled={updateGuardrail.isPending || isEditing}
              onChange={(next) => void handleActiveToggle(next)}
              label={t('agents.sessions.modelUsageDialogActive')}
              testId={`guardrail-switch-${guardrail.id}`}
            />
            <IconButton
              size="small"
              onClick={onEdit}
              aria-label={t('agents.sessions.modelUsageEditLimit')}
              data-testid={`guardrail-edit-${guardrail.id}`}
              disabled={isEditing}
            >
              <EditIcon fontSize="small" />
            </IconButton>
            <IconButton
              size="small"
              onClick={() => void handleRemove()}
              aria-label={t('agents.sessions.modelUsageDeleteLimit')}
              data-testid={`guardrail-remove-${guardrail.id}`}
              disabled={isEditing}
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </>
        )}
      </Stack>
      {guardrailError != null && (
        <Box mt={1}>
          <PermissionDeniedAlert
            error={guardrailError}
            fallbackMessage={t('app.error')}
          />
        </Box>
      )}
    </Paper>
  )
}

interface FormControlLabelSwitchProps {
  checked: boolean
  disabled?: boolean
  onChange: (next: boolean) => void
  label: string
  testId?: string
}

function FormControlLabelSwitch({
  checked,
  disabled,
  onChange,
  label,
  testId,
}: FormControlLabelSwitchProps): ReactNode {
  return (
    <Box
      onClick={(e) => e.stopPropagation()}
      data-testid={testId}
    >
      <Stack direction="row" spacing={0.5} alignItems="center">
        <Switch
          checked={checked}
          disabled={disabled}
          onChange={(_, v) => onChange(v)}
          size="small"
        />
        <Typography variant="caption">{label}</Typography>
      </Stack>
    </Box>
  )
}
