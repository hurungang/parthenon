import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Alert, Button, IconButton, Snackbar, Tooltip } from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import {
  localizeOptimizationGateReason,
  useOptimizationGate,
} from '../../hooks/useOptimizationGate'
import { extractOptimizeGateFailure } from '../../utils/errorUtils'
import type { AgentJob } from '../../types'

export interface AgentOptimizeActionProps {
  agentTypeId: string
  agentTypeName?: string | null
  /**
   * `icon` for dense action rows / headers, `button` for dialog footers.
   */
  variant?: 'icon' | 'button'
  /** Extra disabling (e.g. the agent itself is inactive). */
  disabled?: boolean
  /**
   * Fallback conversational hint from the caller (`input_type`). The gate's
   * `is_conversational` is authoritative once loaded; this keeps the action
   * hidden from the first render for conversational agents.
   */
  isConversational?: boolean
  /** Called with the created optimization session id on success. */
  onTriggered?: (sessionId: string) => void
}

/**
 * Shared one-shot Optimize action — distinct from Run.
 *
 * Starts directly (no pre-run confirmation dialog: the explanation lives in the
 * Optimized Plan tab's help icon and in the chat). The gate is still read first:
 * conversational agents hide the action; other blockers disable it with the
 * localized reason in the tooltip. A rare post-click failure is shown as a
 * lightweight snackbar.
 */
export function AgentOptimizeAction({
  agentTypeId,
  variant = 'icon',
  disabled = false,
  isConversational = false,
  onTriggered,
}: AgentOptimizeActionProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const { data: gate, isError: gateError } = useOptimizationGate(agentTypeId)

  const optimizeMutation = useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post<AgentJob>('/agents/sessions/optimize', {
        agent_type_id: agentTypeId,
      })
      return data
    },
  })

  // No plan and no optimization capability exist for conversational agents.
  if (isConversational || gate?.is_conversational === true) {
    return null
  }

  const canOptimize = gate?.can_optimize === true
  const isDisabled = disabled || !canOptimize || optimizeMutation.isPending
  const tooltip = gateError
    ? t('agents.optimize.gateUnmetFallback')
    : gate === undefined
      ? t('agents.optimize.gateChecking')
      : canOptimize
        ? t('agents.optimize.actionTooltip')
        : (localizeOptimizationGateReason(t, gate.reason_code, gate.reason) ??
          t('agents.optimize.gateUnmetFallback'))

  const label = t('agents.optimize.action')

  const handleTrigger = async () => {
    if (isDisabled) return
    setErrorMessage(null)
    try {
      const job = await optimizeMutation.mutateAsync()
      // The plan is authored asynchronously — refresh the agent scope, the
      // optimized plan and the sessions list so the dialog picks it up.
      await queryClient.invalidateQueries({ queryKey: ['agents', 'types', agentTypeId] })
      await queryClient.invalidateQueries({ queryKey: ['agents', 'sessions'] })
      onTriggered?.(job.id)
    } catch (err) {
      const failure = extractOptimizeGateFailure(err)
      const message = failure
        ? (localizeOptimizationGateReason(t, failure.reason_code, failure.reason) ??
          t('agents.optimize.gateUnmetFallback'))
        : err instanceof Error
          ? err.message
          : t('agents.optimize.gateUnmetFallback')
      setErrorMessage(message)
    }
  }

  return (
    <>
      <Tooltip title={tooltip}>
        {/* Disabled buttons do not emit hover events — the span keeps the
            explanatory tooltip reachable while the action is gated. */}
        <span style={{ display: 'inline-flex' }}>
          {variant === 'button' ? (
            <Button
              variant="outlined"
              color="secondary"
              size="small"
              startIcon={<AutoAwesomeIcon />}
              disabled={isDisabled}
              onClick={() => void handleTrigger()}
              aria-label={label}
              data-testid="optimize-agent-action"
            >
              {label}
            </Button>
          ) : (
            <IconButton
              size="small"
              color="secondary"
              aria-label={label}
              disabled={isDisabled}
              onClick={() => void handleTrigger()}
              data-testid="optimize-agent-action"
            >
              <AutoAwesomeIcon fontSize="small" />
            </IconButton>
          )}
        </span>
      </Tooltip>

      <Snackbar
        open={errorMessage !== null}
        autoHideDuration={8000}
        onClose={() => setErrorMessage(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert
          severity="warning"
          onClose={() => setErrorMessage(null)}
          data-testid="optimize-start-error"
        >
          {errorMessage}
        </Alert>
      </Snackbar>
    </>
  )
}
