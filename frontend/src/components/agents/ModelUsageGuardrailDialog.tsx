import { Alert, Box, Stack } from '@mui/material'
import { type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import type { ModelUsageGuardrailLimit } from '../../types'
import type { AvailableModel } from './AvailableModel'

/**
 * @deprecated Superseded by the inline `AddGuardrailForm` inside
 * `VendorModelGuardrailPanel`. This re-export shim is retained for any
 * remaining consumer that still imports the dialog shape. New code should
 * use the hierarchy panel + inline form.
 */
export type { AvailableModel }

/**
 * @deprecated Form data shape for the old per-model row. Retained so legacy
 * callers (e.g. `ModelUsageGuardrailDialog`) can compile; new callers
 * should use `ModelUsageGuardrailCreatePayload` from
 * `useModelUsageGuardrailMutations`.
 */
export interface ModelUsageGuardrailFormData {
  model_id: string
  model_name: string
  enforcement_posture: 'terminate' | 'observe_only'
  unit: 'k' | 'tokens'
  usage_limit_hour: number | null
  usage_limit_day: number | null
  usage_limit_week: number | null
  usage_limit_month: number | null
  is_active: boolean
}

/**
 * @deprecated Replaced by the hierarchy panel. Renders a notice pointing
 * operators to the new UI and surfaces any pending error.
 */
export function ModelUsageGuardrailDialog(props: {
  open: boolean
  onClose: () => void
  onSave?: (data: ModelUsageGuardrailFormData) => Promise<void> | void
  initialData?: ModelUsageGuardrailLimit | null
  isSubmitting?: boolean
  availableModels?: AvailableModel[]
}): ReactNode {
  const { t } = useTranslation()
  if (!props.open) return null
  return (
    <Alert severity="info" sx={{ m: 2 }}>
      <Stack spacing={1}>
        <Box>{t('agents.sessions.modelUsageDialogDeprecatedNotice')}</Box>
        <PermissionDeniedAlert
          error={null}
          fallbackMessage={t('agents.sessions.modelUsageDialogDeprecatedNotice')}
        />
      </Stack>
    </Alert>
  )
}
