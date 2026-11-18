import type { ReactNode } from 'react'
import { Alert, Button, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  isOptimizerModelReasonCode,
  OPTIMIZER_REASON_MODEL_NOT_CONFIGURED,
  OPTIMIZER_REASON_MODEL_NOT_ENABLED,
} from '../../utils/errorUtils'

export interface OptimizerModelAlertProps {
  /** `optimizer_model_not_configured` / `optimizer_model_not_enabled` (or free text). */
  reasonCode: string | null | undefined
  /** Raw stored selection, echoed for the "no longer available" case. */
  modelId?: string | null
  /** Optional System Config shortcut (an isolated button is provided). */
  action?: ReactNode
  testId?: string
}

/**
 * Model-unavailable guidance for the optimization conversation.
 *
 * Shown when no usable optimizer model exists in this workspace — nothing
 * configured and no plan-authoring model to inherit, or the chosen model is no
 * longer enabled. The composer is disabled while this alert is shown: work must
 * never start on an unapproved model, and no fallback is ever substituted.
 */
export function OptimizerModelAlert({
  reasonCode,
  modelId,
  action,
  testId = 'optimizer-model-alert',
}: OptimizerModelAlertProps) {
  const { t } = useTranslation()

  const body =
    reasonCode === OPTIMIZER_REASON_MODEL_NOT_ENABLED
      ? t('agents.optimizer.modelAlertBodyNotEnabled', {
          modelId: modelId ?? t('agents.optimizer.modelAlertUnknownModel'),
        })
      : isOptimizerModelReasonCode(reasonCode) ||
          reasonCode === OPTIMIZER_REASON_MODEL_NOT_CONFIGURED
        ? t('agents.optimizer.modelAlertBodyNotConfigured')
        : t('agents.optimizer.modelAlertBodyGeneric')

  return (
    <Alert severity="warning" data-testid={testId} action={action}>
      <Typography variant="body2" fontWeight={700}>
        {t('agents.optimizer.modelAlertTitle')}
      </Typography>
      <Typography variant="body2">{body}</Typography>
    </Alert>
  )
}

/**
 * "Open System Config" shortcut, isolated in its own component so ONLY this
 * button requires a Router context (the chat dialog is also rendered in
 * non-router harnesses, mirroring the assistant-model guidance pattern).
 */
export function OptimizerSystemConfigButton({ testId = 'optimizer-open-system-config' }: { testId?: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  return (
    <Button
      color="inherit"
      size="small"
      variant="outlined"
      data-testid={testId}
      onClick={() => navigate('/system-config')}
    >
      {t('agents.optimizer.openSystemConfig')}
    </Button>
  )
}
