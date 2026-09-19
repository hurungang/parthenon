import {
  Box,
  Button,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
  FormControlLabel,
} from '@mui/material'
import { type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import {
  useCreateModelUsageLimit,
  useUpdateModelUsageLimit,
  type ModelUsageGuardrailCreatePayload,
} from '../../hooks/useModelUsageGuardrailMutations'
import type {
  ModelAvailabilityEntry,
  ModelGuardrailEnforcementPosture,
  ModelGuardrailPeriod,
  ModelUsageGuardrailLimit,
  ModelUsageUnit,
} from '../../types'
import type { AvailableModel } from './AvailableModel'

const ALL_PERIODS: ModelGuardrailPeriod[] = ['hour', 'day', 'week', 'month']

interface GuardrailFormProps {
  /** The model row in the hierarchy this form is attached to. */
  model: ModelAvailabilityEntry
  /** The vendor config id that owns this model. */
  vendorConfigId: string
  /** The operator-visible display name for the vendor. */
  vendorDisplayName: string
  /** Available models, used to resolve the (config_id, model_name) pair. */
  availableModels: AvailableModel[]
  /**
   * When provided, the form operates in *edit* mode: the fields are
   * pre-populated from this guardrail and the submit button calls
   * ``useUpdateModelUsageLimit`` instead of the create mutation. The
   * period select is locked to the existing period (the
   * ``(model_id, model_name, period)`` unique constraint makes changing
   * the period a no-go — operators must delete + recreate).
   */
  existing?: ModelUsageGuardrailLimit
  /** Optional callback fired after the guardrail is created/updated. */
  onSaved?: () => void
  /** Optional callback fired when the user cancels the inline form. */
  onCancel?: () => void
}

interface GuardrailFormErrors {
  period?: string
  limit?: string
}

/**
 * Inline (non-modal) form for adding or editing a single per-period
 * guardrail to a model inside the expanded `VendorModelGuardrailPanel`
 * row. When ``existing`` is provided the form is in edit mode; otherwise
 * the period select is filtered to only periods not yet configured on
 * this model so the operator cannot duplicate a
 * ``(model_id, model_name, period)`` pair. Follows the standard dialog
 * error-handling convention (try/catch + PermissionDeniedAlert).
 */
export function AddGuardrailForm({
  model,
  vendorConfigId,
  vendorDisplayName,
  availableModels,
  existing,
  onSaved,
  onCancel,
}: GuardrailFormProps): ReactNode {
  const { t } = useTranslation()
  const createMutation = useCreateModelUsageLimit()
  const updateMutation = useUpdateModelUsageLimit()
  const isEdit = existing != null
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [period, setPeriod] = useState<ModelGuardrailPeriod | ''>(
    existing?.period ?? '',
  )
  const [limitValue, setLimitValue] = useState<string>(
    existing ? String(existing.limit_value) : '',
  )
  const [unit, setUnit] = useState<ModelUsageUnit>(existing?.unit ?? 'k')
  const [posture, setPosture] = useState<ModelGuardrailEnforcementPosture>(
    existing?.enforcement_posture ?? 'terminate',
  )
  const [isActive, setIsActive] = useState<boolean>(existing?.is_active ?? true)
  const [errors, setErrors] = useState<GuardrailFormErrors>({})

  // When the existing record prop changes (e.g. user clicks Edit on a
  // different guardrail), re-seed the local form state.
  useEffect(() => {
    if (existing == null) return
    setPeriod(existing.period)
    setLimitValue(String(existing.limit_value))
    setUnit(existing.unit)
    setPosture(existing.enforcement_posture)
    setIsActive(existing.is_active)
    setErrors({})
    setDialogError(null)
  }, [existing])

  const configuredPeriods = new Set(model.guardrails.map((g) => g.period))
  const availablePeriods = isEdit
    ? ALL_PERIODS
    : ALL_PERIODS.filter((p) => !configuredPeriods.has(p))

  const matchingAvailableModel = availableModels.find(
    (m) => m.model_config_id === vendorConfigId && m.model_name === model.model_name,
  )

  const validate = (): GuardrailFormErrors => {
    const next: GuardrailFormErrors = {}
    if (!period) {
      next.period = t('agents.sessions.modelUsageGuardrailPeriodRequired')
    }
    if (!limitValue || Number.isNaN(Number(limitValue)) || Number(limitValue) <= 0) {
      next.limit = t('agents.sessions.modelUsageGuardrailLimitRequired')
    }
    return next
  }

  const handleSubmit = async () => {
    setDialogError(null)
    const validation = validate()
    setErrors(validation)
    if (Object.keys(validation).length > 0) return
    if (!period) return

    try {
      if (isEdit && existing != null) {
        await updateMutation.mutateAsync({
          limitId: existing.id,
          payload: {
            limit_value: Number(limitValue),
            unit,
            enforcement_posture: posture,
            is_active: isActive,
          },
        })
      } else {
        const payload: ModelUsageGuardrailCreatePayload = {
          model_id: model.model_name,
          model_name: model.model_name,
          model_config_id: vendorConfigId,
          period,
          limit_value: Number(limitValue),
          unit,
          enforcement_posture: posture,
          is_active: isActive,
        }
        await createMutation.mutateAsync(payload)
        setPeriod('')
        setLimitValue('')
        setUnit('k')
        setPosture('terminate')
        setIsActive(true)
      }
      setErrors({})
      onSaved?.()
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleCancel = () => {
    setDialogError(null)
    setErrors({})
    if (!isEdit) {
      setPeriod('')
      setLimitValue('')
    }
    onCancel?.()
  }

  const isPending = isEdit ? updateMutation.isPending : createMutation.isPending
  const dataTestId = isEdit ? 'edit-guardrail-form' : 'add-guardrail-form'

  return (
    <Box
      sx={{
        mt: 1,
        p: 1.5,
        border: 1,
        borderColor: 'divider',
        borderRadius: 1,
        backgroundColor: 'background.default',
      }}
      data-testid={dataTestId}
    >
      {dialogError != null && (
        <Box mb={1}>
          <PermissionDeniedAlert
            error={dialogError}
            fallbackMessage={t('app.error')}
          />
        </Box>
      )}

      <Typography variant="caption" color="text.secondary" display="block" mb={1}>
        {isEdit
          ? t('agents.sessions.modelUsageGuardrailEditForModel', {
              modelName: model.model_name,
              vendor: vendorDisplayName,
              period: existing?.period,
            })
          : t('agents.sessions.modelUsageGuardrailAddForModel', {
              modelName: model.model_name,
              vendor: vendorDisplayName,
            })}
      </Typography>

      {availablePeriods.length === 0 && !isEdit ? (
        <Typography variant="body2" color="text.secondary">
          {t('agents.sessions.modelUsageGuardrailAllPeriodsConfigured')}
        </Typography>
      ) : (
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems="flex-start">
          <FormControl size="small" sx={{ minWidth: 140 }} error={Boolean(errors.period)} disabled={isEdit}>
            <InputLabel id={isEdit ? 'edit-guardrail-period-label' : 'add-guardrail-period-label'}>
              {t('agents.sessions.modelUsagePeriodLabel')}
            </InputLabel>
            <Select
              labelId={isEdit ? 'edit-guardrail-period-label' : 'add-guardrail-period-label'}
              label={t('agents.sessions.modelUsagePeriodLabel')}
              value={period}
              onChange={(e) => setPeriod(e.target.value as ModelGuardrailPeriod)}
              inputProps={{ 'data-testid': isEdit ? 'edit-guardrail-period' : 'add-guardrail-period' }}
            >
              {availablePeriods.map((p) => (
                <MenuItem key={p} value={p}>
                  {p}
                </MenuItem>
              ))}
            </Select>
            {errors.period && (
              <FormHelperText role="alert" data-testid={isEdit ? 'edit-guardrail-period-error' : 'add-guardrail-period-error'}>
                {errors.period}
              </FormHelperText>
            )}
          </FormControl>

          <TextField
            size="small"
            label={t('agents.sessions.modelUsageGuardrailLimitLabel')}
            value={limitValue}
            onChange={(e) => setLimitValue(e.target.value)}
            type="number"
            sx={{ minWidth: 120 }}
            error={Boolean(errors.limit)}
            helperText={errors.limit ?? ' '}
            slotProps={{
              htmlInput: {
                min: 1,
                'data-testid': isEdit ? 'edit-guardrail-limit' : 'add-guardrail-limit',
              },
            }}
            inputProps={{ 'data-testid': isEdit ? 'edit-guardrail-limit' : 'add-guardrail-limit' }}
            FormHelperTextProps={errors.limit ? { role: 'alert' } : {}}
          />

          <FormControl size="small" sx={{ minWidth: 120 }}>
            <InputLabel id={isEdit ? 'edit-guardrail-unit-label' : 'add-guardrail-unit-label'}>
              {t('agents.sessions.modelUsageDialogUnit')}
            </InputLabel>
            <Select
              labelId={isEdit ? 'edit-guardrail-unit-label' : 'add-guardrail-unit-label'}
              label={t('agents.sessions.modelUsageDialogUnit')}
              value={unit}
              onChange={(e) => setUnit(e.target.value as ModelUsageUnit)}
              inputProps={{ 'data-testid': isEdit ? 'edit-guardrail-unit' : 'add-guardrail-unit' }}
            >
              <MenuItem value="k">{t('agents.sessions.modelUsageUnitK')}</MenuItem>
              <MenuItem value="tokens">{t('agents.sessions.modelUsageUnitTokens')}</MenuItem>
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 160 }}>
            <InputLabel id={isEdit ? 'edit-guardrail-posture-label' : 'add-guardrail-posture-label'}>
              {t('agents.sessions.modelUsageDialogEnforcement')}
            </InputLabel>
            <Select
              labelId={isEdit ? 'edit-guardrail-posture-label' : 'add-guardrail-posture-label'}
              label={t('agents.sessions.modelUsageDialogEnforcement')}
              value={posture}
              onChange={(e) =>
                setPosture(e.target.value as ModelGuardrailEnforcementPosture)
              }
              inputProps={{ 'data-testid': isEdit ? 'edit-guardrail-posture' : 'add-guardrail-posture' }}
            >
              <MenuItem value="terminate">terminate</MenuItem>
              <MenuItem value="observe_only">observe_only</MenuItem>
            </Select>
          </FormControl>

          <FormControlLabel
            control={
              <Switch
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                inputProps={{ 'data-testid': isEdit ? 'edit-guardrail-active' : 'add-guardrail-active' } as Record<string, unknown>}
              />
            }
            label={t('agents.sessions.modelUsageDialogActive')}
          />

          <Stack direction="row" spacing={1}>
            <Button
              variant="contained"
              size="small"
              onClick={() => void handleSubmit()}
              disabled={isPending}
            >
              {isEdit ? t('app.save') : t('app.save')}
            </Button>
            <Button variant="outlined" size="small" onClick={handleCancel}>
              {t('app.cancel')}
            </Button>
          </Stack>
        </Stack>
      )}

      {!isEdit && matchingAvailableModel == null && (
        <Typography variant="caption" color="warning.main" display="block" mt={1}>
          {t('agents.sessions.modelUsageGuardrailMissingAvailableModel')}
        </Typography>
      )}
    </Box>
  )
}
